"""Re-verify ONE engine stage in isolation, against the real local model.

    python -m scripts.engine_stage_check --stage segment
    python -m scripts.engine_stage_check --stage all

This is the gate a stage build (or revamp) must pass before the next stage is
wired — and the harness you come back to when a stage misbehaves later. Cases
are corpus-derived traps for that stage alone: the runner builds the stage's
input state directly, runs only that stage, and checks properties of its
output, so a failure names the stage by construction.

Stages whose cases need the LLM are skipped (loudly) when Ollama is not
reachable — deterministic cases still run. Everything runs against scratch
stores; the real ~/.assistant_tools is never touched.
"""

from __future__ import annotations

import argparse
import os
import sys

from assistant.common.scratch_env import scratch_env

# --- isolate BEFORE importing anything from assistant ----------------------
_scratch = scratch_env("engine_stage_check_",
                       keep=("LOCATION", "MODELS", "LABEL_FEEDBACK",
                            "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET",
                            "DEVICES"))

GREEN, RED, YELLOW, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _ollama_up(cfg) -> bool:
    try:
        import requests
        return requests.get(f"{cfg.ollama.base_url}/api/tags", timeout=2).ok
    except Exception:
        return False


def _state(text: str):
    from assistant.engine.state import EngineState
    return EngineState(raw_text=text, text=text, source="test")


def _items_state(items):
    st = _state(" ".join(i.text for i in items))
    st.items = items
    return st


def _item(kind, text, id="item_1", action=None, intent=None):
    from assistant.engine.state import Item
    return Item(id=id, kind=kind, text=text, action=action, intent=intent)


# ---------------------------------------------------------------------------
# Cases. Each: (name, needs_llm, run() -> (ok, detail))
# ---------------------------------------------------------------------------

def _cases_transcript(cfg):
    from assistant.engine.ingest import repair as transcript

    def strip_case():
        st = _state("add lunch tomorrow at one execute")
        transcript.run(st, cfg)
        return st.text == "add lunch tomorrow at one", st.text

    def trivial_case():
        st = _state("I need a b-")
        transcript.run(st, cfg)
        return st.ignored, f"ignored={st.ignored}"

    return [("stop word stripped", False, strip_case),
            ("false start ignored", False, trivial_case)]


def _cases_segment(cfg):
    from assistant.engine.segmentation.old_seg import segment

    def case(text, want_n, want_kinds=None, needs_llm=True):
        def run():
            st = _state(text)
            segment.run(st, cfg)
            got = [(i.kind, i.text) for i in st.items]
            ok = len(st.items) == want_n
            if ok and want_kinds:
                ok = [k for k, _ in got] == want_kinds
            return ok, f"{len(st.items)} item(s): {got}"
        return (text[:56], needs_llm, run)

    return [
        case("book gym tomorrow at 7am and remind me to buy milk", 2,
             ["event", "task"]),
        case("meeting with Tal and Ravid at Kems tomorrow evening", 1),
        case("buy a gift for mom and dad", 1, needs_llm=True),
        case("schedule lunch with Danny on friday at noon and add pasta to the shopping list", 2),
        case("what do I have this week", 1, ["review"], needs_llm=False),
        case("[gym tomorrow at 7am] [lunch with Tal at noon]", 2, needs_llm=False),
    ]


def _cases_decompose(cfg):
    from assistant.engine.decompose_validate import decompose

    def two_walks():
        st = _items_state([_item("event", "walk the dog at 9am and 2:30pm")])
        decompose.run(st, cfg)
        return len(st.items) == 2, f"{[i.text for i in st.items]}"

    def wordy_two_times():
        st = _items_state([_item("event", "take Saba to physio at 10am and later on at 4:30pm")])
        decompose.run(st, cfg)
        return len(st.items) == 2, f"{[i.text for i in st.items]}"

    def range_is_one():
        st = _items_state([_item("event", "lunch with Ima from 12:00 to 1:00 and bring the photos")])
        decompose.run(st, cfg)
        return len(st.items) == 1, f"{[i.text for i in st.items]}"

    def task_list():
        st = _items_state([_item("task", "buy chicken and rice")])
        decompose.run(st, cfg)
        return [i.text for i in st.items] == ["buy chicken", "buy rice"], \
            f"{[i.text for i in st.items]}"

    def quantity():
        st = _items_state([_item("task", "buy 5 apples")])
        decompose.run(st, cfg)
        one = len(st.items) == 1 and st.items[0].slots.get("quantity") == 5
        return one, f"{[(i.text, i.slots) for i in st.items]}"

    return [("two adjacent times → two events", False, two_walks),
            ("wordy double time → two events", True, wordy_two_times),
            ("a range stays one event", False, range_is_one),
            ("task list splits, verb handed down", False, task_list),
            ("a count is one task × N", False, quantity)]


def _cases_validate(cfg):
    import datetime as dt
    from types import SimpleNamespace
    from assistant.engine.decompose_validate import stage as validate

    def ev(**kw):
        base = dict(title="x", date=None, start_time=None, end_time=None,
                    recurrence=None, recur_until=None, description="")
        base.update(kw)
        return SimpleNamespace(**base)

    def until_case():
        it = _item("event", "", action="create_event",
                   intent=ev(date="2026-10-01", recurrence="daily", recur_until="2026-10-06"))
        st = _items_state([it])
        st.text = "every day at 7pm until Oct 6"
        validate.run_objects(st, cfg)
        return it.intent.recur_until == "2026-10-05", it.intent.recur_until

    def past_case():
        it = _item("event", "", action="create_event", intent=ev(date="2026-01-15"))
        st = _items_state([it])
        st.text = "meeting on January 15"
        validate.run_objects(st, cfg)
        return it.intent.date == "2027-01-15", it.intent.date

    def shabbat_gym():
        d = dt.date.today() + dt.timedelta(days=1)
        while d.weekday() != 5:
            d += dt.timedelta(days=1)
        it = _item("event", "", action="create_event",
                   intent=ev(title="gym session", date=d.isoformat(), start_time="10:00"))
        st = _items_state([it])
        st.text = "gym saturday morning"
        validate.run_objects(st, cfg)
        return bool(it.blocked), f"blocked={it.blocked!r}"

    def repair_case():
        st = _items_state([_item("event", "book the the meeting tomorrow at 3pm")])
        validate.run(st, cfg)
        return st.items[0].text == "book the meeting tomorrow at 3pm", st.items[0].text

    return [("until excludes the day", False, until_case),
            ("past date bumps a year", False, past_case),
            ("Shabbat gym refused", False, shabbat_gym),
            ("stutter repaired", False, repair_case)]


def _cases_generate(cfg):
    from assistant.engine.fastrule import stage as generate

    def case(text, kind, want_actions, needs_llm):
        def run():
            st = _items_state([_item(kind, text)])
            generate.run(st, cfg)
            got = [i.action for i in st.items if i.intent is not None]
            return got == want_actions, f"{got}"
        return (text[:56], needs_llm, run)

    def update_defers():
        # `stage._COMMITTABLE = ("create", "query")` (2026-09-10 restructure):
        # a target-taking action names an EXISTING record, and confirming it
        # names a REAL one needs a store lookup the stage cannot do — so an
        # update no longer commits here at all, it always defers to LLMJudge.
        # This case used to expect `["update_event"]` straight out of this
        # stage; that behaviour moved on purpose, not a regression.
        st = _items_state([_item("event", "move my haircut to 6pm")])
        generate.run(st, cfg)
        it = st.items[0]
        ok = it.action is None and bool((it.slots or {}).get("fastrule_defer"))
        return ok, f"action={it.action!r} defer={(it.slots or {}).get('fastrule_defer')!r}"

    return [
        case("book gym tomorrow at 7am", "event", ["create_event"], False),
        case("add milk to my shopping list", "task", ["create_todo"], False),
        case("what do I have on friday", "review", ["query_schedule"], False),
        ("move my haircut to 6pm (defers, not committed)", False, update_defers),
    ]


def _cases_crosscheck(cfg):
    """Extraction quality against a seeded mistake: the check must notice an
    invented row and stay quiet when all is covered.

    A third case — "a dropped ask is noticed", asserting `f.type == "missing"`
    — is GONE, not fixed: the RE-CUT judge (2026-09-10, PLAN.md §6) removed ask
    EXTRACTION entirely ("that defeats the point of what segmentation →
    decompose_validate → FastRule did", Gil), and `findings.py` has no
    `"missing"` type any more (`ungrounded_subject` / `unsupported_field` /
    `not_an_ask` replaced it). There is nothing to port forward — the
    capability was deliberately deleted, not lost.
    """
    from types import SimpleNamespace
    from assistant.engine.llmjudge import llmjudge as crosscheck

    def _ev(id, title, text=""):
        return _item("event", text or title, id=id, action="create_event",
                     intent=SimpleNamespace(title=title))

    def _td(id, title, text=""):
        return _item("task", text or title, id=id, action="create_todo",
                     intent=SimpleNamespace(title=title))

    def clean():
        st = _items_state([_ev("item_1", "gym", "book gym tomorrow at 7am"),
                           _td("item_2", "buy milk")])
        st.raw_text = "book gym tomorrow at 7am and remind me to buy milk"
        crosscheck.run(st, cfg)
        return st.findings == [], f"{[(f.type, f.detail) for f in st.findings]}"

    def invented_row():
        # Was `("extra", "item_2")` — the RE-CUT judge routes an unsupported
        # object through `not_an_ask` now (findings.py), not a separate
        # "extra" type.
        st = _items_state([_td("item_1", "buy milk"),
                           _td("item_2", "buy groceries")])
        st.raw_text = "add buy milk to my shopping list"
        crosscheck.run(st, cfg)
        ok = [(f.type, f.item_id) for f in st.findings] == [("not_an_ask", "item_2")]
        return ok, f"{[(f.type, f.item_id, f.detail) for f in st.findings]}"

    return [("all asks covered → quiet", True, clean),
            ("an invented row is noticed", True, invented_row)]


# Keyed by the engine's OWN stage names (`assistant.engine.state.STAGES` is
# authoritative), with the pre-rewrite names kept as aliases so existing
# invocations and docs keep working. The old set listed six stages that no
# longer all exist and omitted `ingest`, `fastrule`, `llmjudge` and `label`
# entirely, which is how `--stage all` came to mean "four of seven".
STAGES = {
    "transcript":         _cases_transcript,   # ingest/repair.py
    "segment":            _cases_segment,      # NOTE: exercises old_seg, the
                                               # rollback path, NOT the live
                                               # FastSeg. Its own board is
                                               # segmentation/experiments/.
    "decompose_validate": _cases_decompose,
    "fastrule":           _cases_generate,     # fastrule/stage.py (objects.py deleted 2026-09-10)
    "llmjudge":           _cases_crosscheck,   # llmjudge/llmjudge.py
    # Pre-2026-09-08 names, kept so older commands and docs still resolve.
    "decompose":          _cases_decompose,
    "validate":           _cases_validate,
    "generate":           _cases_generate,
    "crosscheck":         _cases_crosscheck,
}

# Stages with NO case set here, so `--stage all` does not quietly imply they
# were checked: `ingest` (coalesce.py) and `commit`/`label`. Both are covered
# by `assistant-cli check engine`'s wiring layer, not by behaviour cases.
UNCOVERED_STAGES = ("ingest", "commit")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", required=True, choices=[*STAGES, "all"])
    args = ap.parse_args()

    from assistant.engine import load_config
    cfg = load_config()
    llm = _ollama_up(cfg)
    if not llm:
        print(f"{YELLOW}Ollama not reachable — LLM cases will be skipped{END}")

    names = list(STAGES) if args.stage == "all" else [args.stage]
    failed = 0
    for name in names:
        print(f"\n── stage: {name} " + "─" * (58 - len(name)))
        for label, needs_llm, run in STAGES[name](cfg):
            if needs_llm and not llm:
                print(f"  {YELLOW}skip{END}  {label} {DIM}(needs Ollama){END}")
                continue
            try:
                ok, detail = run()
            except Exception as e:
                ok, detail = False, f"raised {type(e).__name__}: {e}"
            mark = f"{GREEN}pass{END}" if ok else f"{RED}FAIL{END}"
            print(f"  {mark}  {label}  {DIM}{detail}{END}")
            failed += 0 if ok else 1
    print()
    if failed:
        print(f"{RED}{failed} case(s) failed{END}")
        return 1
    print(f"{GREEN}all run cases passed{END}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Score FastRule against its PRODUCT SHAPE (Gil, 2026-09-07).

FastRule is the atomic-item executor. So the only two questions that matter:

PRIMARY (Gil, 2026-09-07 — "I just want to see that it succeeds on
recognising and executing well on atomic items"):

    ATOMIC rows  → did it HANDLE them, and was it RIGHT?

NON-ATOMIC rows are DIAGNOSTIC, not a target. Gil's ruling: a compound runs
through FastRule anyway, and whatever it finds is PASSED TO THE NEXT STAGE
for the engine to decide (that is what the REFUSAL / STRUCTURE / INCAPACITY
deferral contract carries). So the three outcomes are reported without one
being "the metric":

    covered       committed, and every ask is present — the "easy enough to
                  complete" case Gil's product shape explicitly allows, and
                  the only path that still works with the LLM unreachable
    half-executed committed but an ask is MISSING — the real defect, and the
                  only one worth driving to zero
    deferred      handed up with a reason — also correct

    python -m assistant.engine.fastrule.experiments.fastrule_shape                # test split (reported)
    python -m assistant.engine.fastrule.experiments.fastrule_shape --split train  # mining
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import pathlib
import re
import sys

from assistant.common.scratch_env import scratch_env

_T = scratch_env("fr_shape_", keep=("MODELS", "LABEL_FEEDBACK", "HEARTBEATS",
                                    "HUD_STATE", "DEVICE_SECRET", "DEVICES"))

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: The dataset moved into this stage's folder in the per-stage restructure;
#: this line still pointed at `dataset/fastrule/` until 2026-09-09, so THE
#: PRIMARY BOARD RAISED FileNotFoundError and could not be run at all.
DATA = ROOT / "datasets" / "fastrule_7200.jsonl"   # ROOT is the STAGE folder
_CLOCK = _dt.datetime(2026, 9, 9, 10, 0)
#: the layer-0 verdicts — a defer carrying one of these means FastRule
#: RECOGNISED the compound, rather than tripping over it by luck
_ATOMICITY_REASONS = {"strong-compound", "clause-coordination", "mixed-mode-compound", "model-compound"}

from assistant.common.similarity import token_prf, words  # noqa: E402

#: Classes of words a built title carries that the gold does not, first match
#: wins. "attendee" and "errand verb" are where the gold's own convention is
#: split (some families keep them); the rest are defects.
_LEAK_CLASSES = (
    ("time residue", re.compile(r"^(?:\d+\w*|from|to|at|am|pm|before|after|every|other|"
                                r"twice|daily|weekly|monthly|until|till|by|on|in|o'clock)$")),
    ("attendee", re.compile(r"^with$")),
    ("errand verb", re.compile(r"^(?:buy|grab|get|pick|up|purchase|order)$")),
    ("speaker frame", re.compile(r"^(?:i|i've|we|have|need|needs|got|gotta|must|should|"
                                 r"guess|remind|remember|me|please|ok|okay|add|book|"
                                 r"schedule|put|set|make|create|note|mark|plan)$")),
)


def _leak_class(extra: set) -> str:
    for name, pat in _LEAK_CLASSES:
        if name == "attendee":
            if "with" in extra:
                return name
        elif any(pat.match(w) for w in extra) and (
                name != "errand verb" or all(pat.match(w) for w in extra)):
            return name
    return "other"
from assistant.engine.fastrule.experiments.gold import (  # noqa: E402  pure gold converters
    CONTRADICTORY,
    _AFTERNOON,
    _AMPM,
    _CLOCK24,
    _EMPTY_TITLE_RE,
    _EVENING,
    _EXPLICIT_TIME_RE,
    _HHMM,
    _ISO,
    _MORNING,
    _NOW_RE,
    _SEVERITY,
    _phrase_to_date,
    _phrase_to_hhmm,
    _ruled_hhmm,
    time_is_unambiguous,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("train", "test"), default="test")
    a = ap.parse_args()
    mining = a.split == "train"

    from freezegun import freeze_time
    from assistant.engine.fastrule.fastrule import FastRule
    from assistant.intent.rule_parser import RULE_THRESHOLD

    fr = FastRule(RULE_THRESHOLD)
    fr.run("book gym tomorrow at 7am")          # warm outside the frozen clock

    rows = [json.loads(l) for l in DATA.open() if f'"{a.split}"' in l]
    rows = [r for r in rows if r["split"] == a.split]

    # atomic buckets: a propose row is atomic-but-must-not-commit (Q9), so it
    # gets its own bucket rather than polluting either side
    A_OK = A_MISS = A_WRONG = 0          # atomic: committed-right / deferred / committed-wrong
    N_DEFER = N_COMMIT = N_COMMIT_OK = 0  # non-atomic: deferred / committed (violation)
    N_DEFER_KNEW = 0                      # ...deferred BECAUSE it saw the compound
    P_DEFER = P_COMMIT = 0                # propose rows
    T_OK = T_N = 0                        # explicit times: right / scored (either kind)
    TU_OK = TU_N = 0                      # ...said with am/pm/24h/noon: a miss is a DEFECT
    TB_OK = TB_N = 0                      # ...bare, scored against the ruled convention
    T_CONTRA = 0                          # words that contradict themselves: not scored
    t_miss: list = []                     # (train only) the misses, to read
    INVENT = INVENT_N = 0                 # a time produced where none was said
    # LEAD TIME (2026-09-25). The gold has carried `lead_time` on 241 rows all
    # along and nothing here scored it — so FastRule reading "remind me 30
    # minutes before", computing the minutes and THROWING THEM AWAY committed
    # every such event with no reminder, and no board could see it.
    L_OK = L_N = 0
    D_OK = D_N = 0                        # resolvable dates: right / scored
    # BOUNDED SERIES. The gold marks these with `end_inclusive`, and nothing here
    # scored them until 2026-09-18 — so a series created with NO END, firing
    # forever where the speaker named a stop, was invisible on every board this
    # file has ever printed. It cost a cycle: the fix read as a pure handle-rate
    # LOSS because the only thing it improved had no line.
    B_N = B_HELD = B_WITH = B_RIGHT = B_RIGHT_N = B_FOREVER = 0
    HARM = 0
    TITLE_N = TITLE_BAD = NOW_N = NOW_MIDNIGHT = 0                              # severity-weighted cost of wrong commits
    # TITLE CORRECTNESS, added 2026-09-18. The gold has carried `slots.title`
    # all along and this board only ever asked whether a title NAMED NOTHING —
    # so "meeting" for "meeting with Omri for the project" scored as a perfect
    # title, which is the single largest real-usage failure class (42%,
    # DOCUMENTATION/experiments/real_usage/RESULTS.md). Exact after casefold and
    # whitespace, plus a CONTAINS count that separates "wrong" from "truncated".
    T_OK_EXACT = T_CONTAINED = T_SCORED = 0
    # ...and a SIMILARITY beside the two binary lines (Gil, 2026-09-25: "title
    # should be a similarity rather than binary score"): mean word precision,
    # recall and F1, so "checkup" for "annual checkup" scores 0.67, not 0.
    T_P = T_R = T_F = 0.0
    # WHAT LEAKED IN, by class — aggregate only, so it can be read on the TEST
    # half too, where rows may never be looked at. A train/test precision gap
    # is either a defect that did not generalise or a gold CONVENTION the test
    # families keep differently (an errand verb, an attendee); this says which.
    T_LEAK: collections.Counter = collections.Counter()
    HARM_BY: collections.Counter = collections.Counter()
    viol: collections.Counter = collections.Counter()
    miss_reason: collections.Counter = collections.Counter()
    samples: dict = collections.defaultdict(list)

    with freeze_time(_CLOCK):
        for r in rows:
            e = r["expect"]
            act = e.get("action", "")
            res = fr.run(r["text"])
            committed = bool(res and res.committed)

            # --- BOUNDED SERIES: did the end survive into the intent?
            _b_incl = e.get("slots", {}).get("end_inclusive")
            if _b_incl is not None:
                B_N += 1
                if not committed:
                    B_HELD += 1
                else:
                    _bi = next((i for n, i in res.intents if n.startswith("create")), None)
                    _until = getattr(_bi, "recur_until", None) if _bi else None
                    _rec = getattr(_bi, "recurrence", None) if _bi else None
                    if _until:
                        B_WITH += 1
                        # Scored only where the gold phrase resolves to ONE day:
                        # a range bound ("through next week") has the same "no
                        # single right answer" problem dates do.
                        _want = _phrase_to_date(e["slots"].get("date_phrase_2") or "",
                                                _CLOCK.date())
                        if _want:
                            if not _b_incl:
                                _want = (_dt.date.fromisoformat(_want)
                                         - _dt.timedelta(days=1)).isoformat()
                            B_RIGHT_N += 1
                            B_RIGHT += 1 if str(_until) == _want else 0
                    elif _rec:
                        B_FOREVER += 1      # a series with no end. The defect.
            if act == "propose":
                if committed:
                    P_COMMIT += 1
                    if mining and len(samples["propose-commit"]) < 5:
                        samples["propose-commit"].append(r["text"][:60])
                else:
                    P_DEFER += 1
                continue
            if not e.get("atomic", True):
                if committed:
                    N_COMMIT += 1
                    ev = sum(1 for n, _ in res.intents if n == "create_event")
                    td = sum(1 for n, _ in res.intents if n == "create_todo")
                    ok = ev >= e.get("events", 0) and td >= e.get("tasks", 0)
                    N_COMMIT_OK += 1 if ok else 0
                    viol[r["family"].rsplit("_", 1)[0]] += 1
                    if mining and len(samples["nonatomic-commit"]) < 8:
                        samples["nonatomic-commit"].append(
                            f"[{'ok' if ok else 'WRONG'}] {r['text'][:56]}")
                else:
                    N_DEFER += 1
                    # deferred for the RIGHT reason (the atomicity layer saw
                    # the compound) vs by accident (low confidence, missing
                    # slot) — only the former survives as FastRule improves
                    if (res.reason or "").split(":")[0] in _ATOMICITY_REASONS:
                        N_DEFER_KNEW += 1
                continue
            # atomic row
            if not committed:
                A_MISS += 1
                miss_reason[(res.reason or "none").split(":")[0]] += 1
                if mining and len(samples["atomic-deferred"]) < 10:
                    samples["atomic-deferred"].append(
                        f"[{(res.reason or '?').split(':')[0]}] {r['text'][:52]}")
                continue
            ev = sum(1 for n, _ in res.intents if n == "create_event")
            td = sum(1 for n, _ in res.intents if n == "create_todo")
            names = [n for n, _ in res.intents]
            if act in ("create_event", "create_todo"):
                ok = ev >= e.get("events", 0) and td >= e.get("tasks", 0)
            elif act == "query":
                ok = (ev + td) == 0 and any(n.startswith("query") for n in names)
            else:
                ok = (ev + td) == 0 and any(n.startswith(act.split("_")[0]) for n in names)
            # --- TIME CORRECTNESS (added 2026-09-07): neither scorer looked
            # at the time before, so a parser that invents plausible times
            # could only ever LOOK better. An autonomous loop must not be
            # blind to the field users care most about.
            # --- DATE CORRECTNESS: times were scored first and immediately
            # found a defect; dates had the same exposure and no metric.
            if act in ("create_event", "create_todo"):
                firstc = next((i for n, i in res.intents
                               if n.startswith("create")), None)
                got_d = str(getattr(firstc, "date", "")
                            or getattr(firstc, "due_date", "") or "")
                dphrase = (e.get("slots", {}) or {}).get("date_phrase") or ""
                if dphrase and _ISO.match(got_d):
                    want_d = _phrase_to_date(dphrase, _CLOCK.date())
                    if want_d:              # ranges resolve to None: not scored
                        D_N += 1
                        D_OK += 1 if got_d == want_d else 0
            _lt = (e.get("slots", {}) or {}).get("lead_time")
            if _lt and act.startswith("create_"):
                from assistant.intent import lead_time as _lead
                _, want_min = _lead.split(f"book the thing and remind me {_lt}")
                if want_min:
                    got_min = next((getattr(i, "reminder_minutes", None) for n, i in res.intents
                                    if n.startswith("create_")), None)
                    L_N += 1
                    L_OK += 1 if got_min == want_min else 0
            if act == "create_event":
                first = next((i for n, i in res.intents
                              if n == "create_event"), None)
                got_t = str(getattr(first, "start_time", "") or "")
                phrase = (e.get("slots", {}) or {}).get("time_phrase") or ""
                if phrase and _EXPLICIT_TIME_RE.search(phrase):
                    want = _ruled_hhmm(phrase, r["text"])
                    if want == CONTRADICTORY:
                        T_CONTRA += 1
                    elif want and _HHMM.match(got_t):
                        right = got_t == want
                        T_N += 1
                        T_OK += right
                        if time_is_unambiguous(phrase):
                            TU_N += 1
                            TU_OK += right
                        else:
                            TB_N += 1
                            TB_OK += right
                        if mining and not right:
                            t_miss.append((phrase, want, got_t, r["text"]))
                elif not phrase:
                    # Nothing was said about a time: 00:00 (all-day) is the
                    # honest answer, anything else is an invention — EXCEPT a
                    # meal, which names its own hour (Gil, 2026-09-20:
                    # breakfast 09:00, lunch 13:00, dinner 19:00). The
                    # instrument is changed in the same commit as the rule,
                    # because otherwise this line measures the old convention
                    # and charges the engine for obeying the new one: it read
                    # 3.5% -> 5.1% on the 370 untimed events the moment the
                    # rule landed, which is the board's premise moving, not
                    # the engine inventing anything. Narrow on purpose — only
                    # the meal's OWN hour is exempt, so a meal stamped 21:00
                    # is still an invention.
                    from assistant.actions.calendar.intent import meal_hour
                    INVENT_N += 1
                    # 09:00 joined 2026-09-20 (Gil, DEVQA Q36): an untimed
                    # dated event is nine on both tracks, and all-day is what
                    # the speaker ASKS for rather than the fallback. Same
                    # discipline as the meal hour a fortnight of lines above —
                    # the instrument learns a ruling in the commit that makes
                    # it, or it measures the old convention and charges the
                    # engine for obeying the new one.
                    honest = {"00:00", "09:00",
                              meal_hour(getattr(first, "title", "")) or "00:00"}
                    # A PART OF THE DAY's documented start ("this evening" 19:00,
                    # "this afternoon" 12:00) is a convention both tracks apply,
                    # not an invention — this board's own header already says
                    # "vague dayparts … the engine maps them by a documented
                    # convention", and the line did not exempt them. It
                    # surfaced when the front door took its values from the
                    # deep reader (DEVQA Q53, 2026-09-25).
                    from assistant.engine.decompose_validate.resolve import PART_OF_DAY
                    tl = r["text"].lower()
                    honest |= {w[0] for k, w in PART_OF_DAY.items()
                               if re.search(rf"\b{re.escape(k)}\b", tl)}
                    if _HHMM.match(got_t) and got_t not in honest:
                        INVENT += 1
            # --- TITLE QUALITY (added 2026-09-08). Until now this board
            # mentioned the word "title" once and scored it nowhere, so an
            # event called "event" at midnight was a PERFECT commit by its
            # arithmetic: right count, right action family. That is exactly
            # what reached the user from the phone, at confidence 1.00.
            if act in ("create_event", "create_todo"):
                for nm, iv in res.intents:
                    if not nm.startswith("create"):
                        continue
                    for tt in ([str(getattr(iv, "title", "") or "")]
                               + [str(x) for x in (getattr(iv, "titles", None) or [])]):
                        tt = tt.strip()
                        if not tt:
                            continue
                        TITLE_N += 1
                        if _EMPTY_TITLE_RE.match(tt):
                            TITLE_BAD += 1
                # Against the gold, one title per row: `slots.title` is
                # singular, so a multi-title row is scored on its first, which
                # is the one the gold names.
                want = str((e.get("slots") or {}).get("title") or "").strip()
                got = ""
                for nm, iv in res.intents:
                    if nm.startswith("create"):
                        got = str(getattr(iv, "title", "")
                                  or (getattr(iv, "titles", None) or [""])[0] or "")
                        break
                if want and got:
                    T_SCORED += 1
                    # NOT `a`/`b`: `a` is the argparse namespace in this scope,
                    # and rebinding it printed the header as
                    # "[<built-in method split ...>]" instead of "[train]".
                    want_n = " ".join(want.lower().split())
                    got_n = " ".join(got.lower().split())
                    _p, _r, _f = token_prf(want_n, got_n)
                    _extra = words(got_n) - words(want_n)
                    if _extra:
                        T_LEAK[_leak_class(_extra)] += 1
                    T_P += _p
                    T_R += _r
                    T_F += _f
                    if want_n == got_n:
                        T_OK_EXACT += 1
                        T_CONTAINED += 1
                    elif want_n in got_n or got_n in want_n:
                        # One is a truncation or an extension of the other —
                        # "meeting" for "meeting with Omri". A different defect
                        # from naming the wrong thing entirely, and the one a
                        # subtractive title is meant to move.
                        T_CONTAINED += 1
            # --- "NOW" ROWS. `time correctness` only scores an EXPLICIT clock
            # phrase, so every row whose time is the word "now" was skipped —
            # 152 of them in this dataset alone. They are the rows that landed
            # at midnight, scored as fine.
            if act == "create_event" and _NOW_RE.search(r["text"]):
                firste = next((i for n, i in res.intents
                               if n == "create_event"), None)
                got_now = str(getattr(firste, "start_time", "") or "")
                NOW_N += 1
                if got_now == "00:00":
                    NOW_MIDNIGHT += 1
            if ok:
                A_OK += 1
            else:
                A_WRONG += 1
                # what did this wrong commit COST? (severity, not just count)
                for nm, _ in res.intents:
                    w = _SEVERITY.get(nm, 1)
                    HARM += w
                    if w >= 2:
                        HARM_BY[nm] += 1
                if mining and len(samples["atomic-wrong"]) < 8:
                    samples["atomic-wrong"].append(f"[{act}→{names}] {r['text'][:48]}")

    A_N = A_OK + A_WRONG + A_MISS
    N_N = N_DEFER + N_COMMIT
    P_N = P_DEFER + P_COMMIT
    def pc(x, n): return f"{x/n:.1%}" if n else "—"
    print(f"[{a.split}] FastRule product-shape board\n")
    print(f"ATOMIC rows ({A_N}) — should HANDLE")
    print(f"   handled (committed)      {pc(A_OK + A_WRONG, A_N)}")
    print(f"   correct-on-handled       {pc(A_OK, A_OK + A_WRONG)}")
    print(f"   deferred (missed work)   {pc(A_MISS, A_N)}")
    if D_N:
        print(f"\nDATE CORRECTNESS (on committed creates)")
        print(f"   resolvable date right    {pc(D_OK, D_N)}  (n={D_N}; "
              f"range phrases like 'next week' excluded, no single right answer)")
    if B_N:
        print(f"\nBOUNDED SERIES (the gold names an end: \"every monday until "
              f"the end of the month\")")
        print(f"   rows                     {B_N}   ({B_HELD} deferred, {B_N - B_HELD} committed)")
        print(f"   carried an end           {pc(B_WITH, B_N - B_HELD)}  (of the committed)")
        print(f"   ...and it was the right day {pc(B_RIGHT, B_RIGHT_N)}  (n={B_RIGHT_N}; "
              f"range phrases excluded, same reason as dates)")
        print(f"   FIRES FOREVER            {B_FOREVER}  <- a series committed with no end")
    if T_SCORED:
        print(f"\nTITLE CORRECTNESS (committed creates whose gold names a title)")
        print(f"   word F1 (similarity)     {100.0 * T_F / T_SCORED:.1f}%  "
              f"precision {100.0 * T_P / T_SCORED:.1f}% (words leaked in) · "
              f"recall {100.0 * T_R / T_SCORED:.1f}% (words cut)  (n={T_SCORED})")
        print(f"   exactly right            {pc(T_OK_EXACT, T_SCORED)}  (n={T_SCORED})")
        if T_LEAK:
            print("   leaked words, by class   "
                  + " · ".join(f"{k} {pc(v, T_SCORED)}" for k, v in T_LEAK.most_common())
                  + f"  (rows of n={T_SCORED})")
        print(f"   right or a substring of it {pc(T_CONTAINED, T_SCORED)}  "
              f"— the gap to exact is TRUNCATION, not a wrong name")
    if TITLE_N:
        print(f"\nTITLE QUALITY (on committed creates)")
        print(f"   titles that name nothing  {pc(TITLE_BAD, TITLE_N)}  "
              f"({TITLE_BAD}/{TITLE_N}) — 'event', 'the appointment', 'a task'")
    if NOW_N:
        print(f"\n\"NOW\" ROWS (the word is a time; `time correctness` skips them)")
        print(f"   booked at midnight        {pc(NOW_MIDNIGHT, NOW_N)}  "
              f"({NOW_MIDNIGHT}/{NOW_N})")
    if A_WRONG:
        print(f"\nHARM (severity-weighted cost of wrong commits)")
        print(f"   harm score               {HARM}  over {A_WRONG} wrong commits "
              f"(delete=4 · update/complete=2 · create=1 · query=0)")
        if HARM_BY:
            print(f"   DESTRUCTIVE errors       "
                  + " · ".join(f"{k} {v}" for k, v in HARM_BY.most_common(4)))
        else:
            print(f"   DESTRUCTIVE errors       none — every wrong commit was "
                  f"a spurious row, not a loss")
    if L_N:
        print(f"\nLEAD TIME (committed creates whose gold names one)")
        print(f"   reminder carried         {pc(L_OK, L_N)}  (n={L_N})")
    if T_N or INVENT_N:
        print(f"\nTIME CORRECTNESS (on committed events)")
        print(f"   explicit time right      {pc(T_OK, T_N)}  (n={T_N}; by the rulings, "
              f"Q28 + day words — before 2026-09-25 this read every bare hour as AM)")
        print(f"     said with its half     {pc(TU_OK, TU_N)}  (n={TU_N}; am/pm, 24h, noon — "
              f"a miss here is a DEFECT)")
        print(f"     bare, by convention    {pc(TB_OK, TB_N)}  (n={TB_N})")
        if T_CONTRA:
            print(f"     not scored             {T_CONTRA} rows whose words contradict "
                  f"themselves ('this afternoon at 9:15')")
        print(f"   INVENTED a time          {pc(INVENT, INVENT_N)}  "
              f"(n={INVENT_N} events where the speaker named no time)")
    print(f"\nNON-ATOMIC rows ({N_N}) — diagnostic; the engine decides")
    print(f"   deferred, handed up      {pc(N_DEFER, N_N)}")
    print(f"     ...knew it was compound {pc(N_DEFER_KNEW, N_N)}  (layer 0 said so)")
    print(f"     ...by accident          {pc(N_DEFER - N_DEFER_KNEW, N_N)}  (low confidence / missing slot)")
    print(f"   covered (all asks present) {N_COMMIT_OK} ({pc(N_COMMIT_OK, N_N)})  — acceptable")
    print(f"   HALF-EXECUTED             {N_COMMIT - N_COMMIT_OK} "
          f"({pc(N_COMMIT - N_COMMIT_OK, N_N)})  <- the defect that matters")
    print(f"\nPROPOSE rows ({P_N}) — should DEFER (Q9)")
    print(f"   defer rate               {pc(P_DEFER, P_N)}  · violations {P_COMMIT}")
    if not mining:
        print("\n(test split: aggregates only — leakage guard)")
        return 0
    print("\n--- mining (train only) ---")
    if t_miss:
        print(f"time misses ({len(t_miss)}), by phrase:")
        seen = collections.Counter(m[0] for m in t_miss)
        shown = set()
        for phrase, want, got, text in t_miss:
            if phrase in shown or len(shown) >= 12:
                continue
            shown.add(phrase)
            print(f"   {seen[phrase]:>4}  {phrase!r:22} want {want} got {got} | {text[:80]}")
    print("atomic rows deferred, by reason:")
    for k, v in miss_reason.most_common(8):
        print(f"   {v:>4}  {k}")
    for k in ("atomic-deferred", "atomic-wrong", "nonatomic-commit", "propose-commit"):
        if samples[k]:
            print(f"\n{k}:")
            for s in samples[k]:
                print(f"   {s}")
    if viol:
        print("\nviolating families:")
        for k, v in viol.most_common(6):
            print(f"   {v:>3}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""LLMJudge — the last check before anything is trusted.

Contract (see DOCUMENTATION/ENGINE.md):
  reads   state.raw_text, state.text, state.items, state.executed
  writes  state.findings (CheckFinding), state.mistakes, trace steps (VERIFY)
  run(state, cfg) NEVER touches the database or loops itself — the orchestrator
  owns the loop-back (foreground, pre-commit) and the patch application
  (background, post-commit).

TWO JOBS, in this order:

  0. ANSWER FASTRULE'S DEFERS (`rescue.py`). FastRule leaves a `Defer` on each
     item it could not build and stops; this stage is next in the chain and owns
     the model, so the hand-off happens here. Before the check, because the
     check compares what was PRODUCED against what was said and a deferred item
     has not been produced yet.
  1. JUDGE what came out, against the raw text.

## How job 1 is split, and why the split is the whole design

    render.py    what an object SAYS — one canonical string, defaults dropped
    verdict.py   deterministic code, which does all the deciding
    findings.py  the taxonomy and the router — what goes where
    rewrite.py   X1', when and only when an honest one exists

**The model extracts; deterministic code judges.** Asked "is this object
correct?" an 8B says yes — the accept bias, and the same family as the
verbosity, position and rubric-order effects the judge literature measures. So
it is asked instead to LIST the asks in the words, and to QUOTE the words behind
each field. Both are copying. `verdict.py` turns the two lists into findings, and
the model never sees a score, never names a stage, and never decides what
commits.

**The temporal fields never reach the model at all.** `CalendarIntent` stamps
`date = today` / `start_time = the current hour` / `end_time = start + 1h` the
moment an object exists, so an object's date is present whether or not anyone
said one — and grounding it against the words would flag every correct event
that happens to be today. `item.slots` is the honest record of what
`decompose_validate` actually resolved, and `render.unsupported_by_slots` reads
it. Deterministic-first, exactly as the rest of the engine works.

On transport failure (model offline, disabled) there are simply no
model-derived findings — a command must never fail because its checker could not
run. The slot check still runs; it never needed a model.
"""

from __future__ import annotations

from assistant.engine.llmjudge import findings as F, rewrite, verdict
from assistant.engine.llmjudge.findings import ROUTE            # noqa: F401
from assistant.engine.llmjudge.rewrite import rewrite_for_retry  # noqa: F401

MAX_REENTRIES = 3   # total per command, all stages combined


def run(state, cfg):
    """X4 + the raw text -> findings. Nothing is committed and nothing loops."""
    from assistant.trace import VERIFY
    from assistant.engine.llmjudge import rescue as _rescue

    _rescue.take_deferrals(state, cfg)

    produced = verdict.collect(state)
    found = verdict.judge(state, produced)
    state.findings = found
    state.mistakes = [f.detail for f in found]
    _flag_panel_items(state, found)

    if state.trace:
        if found:
            state.trace.step(
                VERIFY, "Cross-check",
                "; ".join(f.detail for f in found), ok=False,
                findings=[f.type for f in found],
                routes=sorted({F.route(f.type) for f in found}))
        else:
            state.trace.step(
                VERIFY, "Cross-check",
                f"{len(produced)} object(s) — every field traced back to the "
                f"words")
    return state


def _flag_panel_items(state, found) -> None:
    """Mark PANEL-routed objects so the review panel can DRAW them.

    A SIBLING key to FastRule's `slots["fastrule_result"]`, not the same one:
    FastRule's says the converter refused to build, this one says the judge
    found nothing that asked for it. The panel draws them in the same row and
    the two must stay distinguishable, because only one of them is a bug.

    **It does not block the commit, and that is deliberate.** Gil's third bucket
    is *"objects which are not meant to be committed"*, and blocking is where
    this is going — but `extra` is the finding this engine is measurably worst
    at: segment is under-split-biased, so an extra is far more often the
    matcher's artefact than real over-production (run 8: 39 loop storms, mostly
    exactly that). Dropping a correct object on a false positive is a worse
    failure than mentioning a real one. **The gate is the isolation board's
    false-flag rate on `extra`** — `experiments/judge_board.py` — and flipping
    this to blocking is a one-line change once that number says it is safe.
    """
    from assistant.trace import VERIFY

    by_id = {it.id: it for it in state.items}
    for f in found:
        if F.route(f.type) != F.PANEL or not f.item_id:
            continue
        it = by_id.get(f.item_id)
        if it is None:
            continue
        it.slots = dict(it.slots or {})
        it.slots["judge_result"] = "not_asked"
        it.slots["judge_detail"] = f.detail
        # AND A TRACE STEP, because the panel is downstream of the trace: an
        # outcome that emits no step cannot be drawn however the panel is
        # written. Writing only to `slots` made this bucket exist on the server
        # and nowhere the user could see it — the same silent shape FastRule's
        # `not_an_ask` had before it got a step of its own (2026-09-10).
        #
        # `ok=True`: this is a correct reading held back, not a failure. Red is
        # reserved for something fatal.
        if state.trace:
            title = getattr(it.intent, "title", None) or (it.text or "")[:40]
            state.trace.step(VERIFY, "Not a calendar ask",
                             f"“{title}” — {f.detail}", ok=True,
                             judge_result="not_asked", item_id=it.id)


def notices(state) -> "list[str]":
    """What to TELL the speaker about objects that committed with an assumption.

    Called once by the orchestrator after the loop settles, never from `run`:
    `run` executes on every round, and appending here would apologise three
    times for one doubt. `COMMIT_FLAGGED` is the only route that owes the user a
    sentence — REWRITE is handled by looping and PANEL by the panel.
    """
    out, seen = [], set()
    for f in state.findings:
        if F.route(f.type) != F.COMMIT_FLAGGED:
            continue
        msg = f"I went ahead, but {f.detail}."
        if msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out

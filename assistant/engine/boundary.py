"""What crosses between two stages, rendered short enough to watch.

`engine/ARCHITECTURE.md` names the chain in terms of `X0 … X4` — the value each
box hands the next — but until now nothing ever SHOWED one. The published page
describes them, the contracts pin them, and the review panel drew the steps
without the data flowing between them.

    X0  the raw transcript
    X1  one repaired command string
    X2  typed items — (action, time, tag), the time still as spoken
    X3  items, complete: every field an object needs, resolved
    X4  the objects themselves

## Rendered for a HUMAN, and truncated on purpose

These are watched live in a floating card a few hundred pixels wide, so a
boundary that dumps a whole item list is a boundary nobody reads. Each renderer
gives the SHAPE first (how many items, of what kind) and the content second,
clipped. The full values are already in the trace steps for anyone who needs
them; this is the flow, not the record.
"""
from __future__ import annotations

_CLIP = 120


def _clip(s: str, n: int = _CLIP) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _items(state) -> str:
    items = list(getattr(state, "items", []) or [])
    if not items:
        return "no items"
    parts = []
    for it in items[:4]:
        when = (it.time or "").strip()
        parts.append(f"({it.kind}) {it.text}" + (f" · {when}" if when else ""))
    more = f" +{len(items) - 4} more" if len(items) > 4 else ""
    return _clip(" | ".join(parts)) + more


def _resolved(state) -> str:
    """X3 is the items PLUS what decompose_validate resolved, so showing the
    items again would hide the only thing that changed."""
    items = list(getattr(state, "items", []) or [])
    if not items:
        return "no items"
    parts = []
    for it in items[:3]:
        vals = {k: v for k, v in (it.slots or {}).items()
                if k in ("date", "start_time", "end_time", "recurrence",
                         "recur_days", "recur_until", "quantity",
                         "reminder_minutes") and v not in (None, "", [], {})}
        shown = " ".join(f"{k}={v}" for k, v in list(vals.items())[:4]) or "nothing resolved"
        parts.append(f"{it.text[:22]} → {shown}")
    more = f" +{len(items) - 3} more" if len(items) > 3 else ""
    return _clip(" | ".join(parts)) + more


def _objects(state) -> str:
    from assistant.engine.llmjudge import render
    built = [it for it in getattr(state, "items", []) or []
             if it.intent is not None and it.action]
    if not built:
        return "nothing built"
    lines = [render.render_line(it.action, it.intent, it.slots) for it in built[:3]]
    more = f" +{len(built) - 3} more" if len(built) > 3 else ""
    return _clip(" | ".join(lines), 160) + more


def _verdict(state) -> str:
    findings = list(getattr(state, "findings", []) or [])
    if not findings:
        return "every field traced back to the words"
    from assistant.engine.llmjudge import findings as F
    by = {}
    for f in findings:
        by[F.route(f.type)] = by.get(F.route(f.type), 0) + 1
    return _clip(" · ".join(f"{n} to {route}" for route, n in sorted(by.items())))


#: stage name → (boundary label, renderer, one-line meaning). Only the stages
#: that produce a NAMED boundary appear; `ingest` and `commit` bracket the chain
#: rather than sitting inside it.
BOUNDARIES = {
    "transcript":         ("X1", lambda s: _clip(s.text), "one repaired command string"),
    "segment":            ("X2", _items, "typed items — the time still as spoken"),
    "decompose_validate": ("X3", _resolved, "items, complete — every field resolved"),
    "fastrule":           ("X4", _objects, "the objects, ready to write"),
    "llmjudge":           ("verdict", _verdict, "what the judge decided about each"),
}


def emit(stage_name: str, state) -> None:
    """Record the boundary this stage just produced, if it has one.

    Never raises and never blocks: a display feature must not be able to fail a
    command. A renderer that throws simply produces no boundary.
    """
    spec = BOUNDARIES.get(stage_name)
    trace = getattr(state, "trace", None)
    if spec is None or trace is None or not hasattr(trace, "boundary"):
        return
    label, render, detail = spec
    try:
        trace.boundary(label, render(state), detail)
    except Exception:
        pass


def emit_fast(state) -> None:
    """The fast track's boundary. It has no X2 and no X3.

    `fast_propose` reads the WHOLE command with rules and produces objects in
    one move — that is what makes it fast. Publishing an empty X2 and X3 would
    draw a gap and invite the reader to think something failed; publishing X4
    with the reason names what actually happened.
    """
    trace = getattr(state, "trace", None)
    if trace is None or not hasattr(trace, "boundary"):
        return
    try:
        trace.boundary("X4", _objects(state),
                       "the rules read the whole command at once — no X2 or X3")
    except Exception:
        pass

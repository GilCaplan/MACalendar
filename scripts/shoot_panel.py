#!/usr/bin/env python3
"""Render the REAL review panel offscreen against a REAL trace, and save a PNG.

    python -m scripts.shoot_panel "book dentist tomorrow at 3" /tmp/panel.png
    python -m scripts.shoot_panel "thanks so much" /tmp/p.png light

WHY THIS EXISTS. Two panel defects shipped green and were found only by looking
at a picture of the widget (2026-09-10):

  - the chain rail drew the WORD "skipped" into a slot fixed at 14x14, so every
    unused step rendered as "pp". A test asserted `text() == "skipped"` and
    passed — it was pinning the bug.
  - a sanity-fix note was the whole transcript twice, which the 3-line clamp
    then cut mid-word.

Neither is visible in the code, and CLAUDE.md's standing warning about UI tests
that never send a mouse event is the same lesson from the other side: read the
rendering, do not reason about it.

It drives the real engine, so the trace is real — the panel is fed exactly what
a live command produces, not a fixture that could drift from it.

Every store is redirected to a scratch directory first (CLAUDE.md: the paths are
read at import time, so this has to happen before `assistant` is imported), and
the source is "test" so nothing lands in the real trace-bus history.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_SCRATCH = pathlib.Path(os.environ.get(
    "PANEL_SHOT_SCRATCH", tempfile.mkdtemp(prefix="panel_shot_")))
_SCRATCH.mkdir(parents=True, exist_ok=True)
for _v, _n in (("DB", "calendar.db"), ("MEMORY_DB", "mem.db"),
               ("VOCAB", "vocab.json"), ("CATEGORIES", "cats.json"),
               ("TRACE_BUS", "trace_bus.jsonl")):
    os.environ[f"MACALENDAR_{_v}"] = str(_SCRATCH / _n)
os.environ["MACALENDAR_NO_WARMUP"] = "1"
# Background: yields the model to the live assistant between calls.
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
os.environ.setdefault("MACALENDAR_OBSERVANCE", "0")
# Offscreen, so this never steals focus or needs a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else "book dentist tomorrow at 3"
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/panel.png"
    dark = (len(sys.argv) < 4) or sys.argv[3] != "light"

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import assistant.engine as engine
    from assistant.trace import Trace
    from assistant.calendar_ui.thinking_panel import ThinkingPanel

    tr = Trace()
    res = engine.run_transcript(text, trace=tr, source="test")

    panel = ThinkingPanel()
    panel.apply_theme(dark)
    panel.begin(source="Mac")
    panel.set_input(res.get("transcript") or text)
    for step in tr.to_list():
        panel.add_step(step)
    for b in tr.boundaries:
        panel.add_boundary(b)
    panel.finish(res)
    app.processEvents()

    panel.grab().save(out)
    print(f"{out}  {panel.width()}x{panel.height()}  "
          f"steps={len(tr.to_list())}  "
          f"boundaries={[b['label'] for b in tr.boundaries]}")

    # The objective half of "is it cluttered": what the content wants vs what
    # the card gives it.
    from assistant.calendar_ui import thinking_panel as tp
    h = lambda w: w.sizeHint().height() if w else 0
    rail = panel.findChildren(tp._ChainRail)
    strip = panel.findChildren(tp._FlowStrip)
    rows = panel.findChildren(tp._StepRow)
    content = ((h(rail[0]) if rail else 0) + (h(strip[0]) if strip else 0)
               + sum(h(r) for r in rows))
    print(f"  rail {h(rail[0]) if rail else 0}px · strip "
          f"{h(strip[0]) if strip else 0}px · {len(rows)} rows "
          f"{sum(h(r) for r in rows)}px  =  {content}px of content in "
          f"{panel.height()}px of card ({content / max(1, panel.height()):.1f}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

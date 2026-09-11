"""Render the real thinking panel against a real engine trace, and measure it.

    python -m scripts.shoot_panel "book gym tomorrow at 7" /tmp/p.png [light|dark]

Two defects in this card shipped green because every test called a handler and
read a string back: the chain rail drew the word "skipped" into a 14x14 slot
(it rendered as "pp"), and a note repeated the whole transcript twice. Neither
is visible from an assertion — you have to look at the picture. So this runs a
transcript through the engine, feeds the resulting trace to the same
`ThinkingPanel` the HUD shows, writes a PNG, and prints the one number the
clutter work is judged on: how much content the fixed-height card is holding.

It is a dev tool, not a test: it writes nothing personal (every store is
redirected to a scratch directory, the trace bus included, and the run is
labelled `source: "test"`), and it needs no Ollama — the engine's LLM stages
self-skip, so an offline run still produces a real trace of the fast track.
"""

from __future__ import annotations

import os
import sys
import tempfile

# BEFORE importing anything from `assistant`: the personal stores' paths are
# read at import time, so this is the only moment they can be redirected.
# CLAUDE.md, "Personal data lives outside the repo".
_SCRATCH = tempfile.mkdtemp(prefix="macalendar-shoot-")
for _var, _name in (("MACALENDAR_DB", "calendar.db"),
                    ("MACALENDAR_MEMORY_DB", "nlu_memory.db"),
                    ("MACALENDAR_VOCAB", "vocab.json"),
                    ("MACALENDAR_CATEGORIES", "categories.json"),
                    ("MACALENDAR_LOCATION", "location.json"),
                    ("MACALENDAR_TRACE_BUS", "trace_bus.jsonl")):
    os.environ.setdefault(_var, os.path.join(_SCRATCH, _name))
os.environ.setdefault("MACALENDAR_NO_WARMUP", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer                     # noqa: E402
from PyQt6.QtWidgets import QApplication            # noqa: E402

from assistant import trace as _trace               # noqa: E402
from assistant.calendar_ui.thinking_panel import (  # noqa: E402
    PANEL_HEIGHT, PANEL_WIDTH, ThinkingPanel,
)


def _run(text: str) -> tuple[list[dict], dict]:
    """The engine's real trace for `text`, plus the result it answered with."""
    from assistant.engine import run_transcript

    tr = _trace.Trace(source="test")
    steps: list[dict] = []
    tr.on_step(lambda s: steps.append(s.to_dict()))
    try:
        result = run_transcript(text, trace=tr, source="test")
    except Exception as e:                      # a parse error is a trace too
        result = {"transcript": text, "message": f"{type(e).__name__}: {e}"}
    result.setdefault("transcript", text)
    result.setdefault("brain", _trace.BRAIN_VERSION)
    return steps, result


def _measure(panel: ThinkingPanel) -> str:
    """Content-vs-card: what the run wants to show against what the card has.

    The card is a fixed 400x440; everything above that height is behind a
    scrollbar. The rail's share is reported beside it because the rail is the
    one block whose size is ours to choose — it is a map of a chain we already
    know, drawn above the steps that are the journey.
    """
    body = panel._body
    body.adjustSize()
    content = body.sizeHint().height()
    # The card's own chrome: header + rule. The rest is the scrolled body.
    chrome = panel._header.sizeHint().height() + panel._rule.height()
    viewport = PANEL_HEIGHT - chrome
    rail = panel._rail.sizeHint().height() if panel._rail is not None else 0
    steps = sum(r.sizeHint().height() for r in panel._rows)
    card = panel._result_card.sizeHint().height() if panel._result_card else 0

    over = content / viewport if viewport else 0
    share = (100.0 * rail / content) if content else 0
    slots = len(panel._rail._slots) if panel._rail else 0
    folded = len(panel._rail.folded_slots()) if panel._rail else 0
    return (
        f"  content {content}px in a {viewport}px viewport ({over:.2f}x)\n"
        f"  chain rail {rail}px ({share:.0f}% of content, "
        f"{slots - folded} of {slots} slots shown, {folded} folded away)\n"
        f"  step rows  {steps}px ({len(panel._rows)} rows)\n"
        f"  result card {card}px\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    text = argv[0]
    out = argv[1]
    dark = (argv[2].lower() != "light") if len(argv) > 2 else True

    steps, result = _run(text)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    panel = ThinkingPanel(dark=dark)
    panel.resize(PANEL_WIDTH, PANEL_HEIGHT)
    panel.begin(source="Mac")
    for step in steps:
        panel.add_step(step)
    panel.finish(result)
    panel.show()
    app.processEvents()
    QTimer.singleShot(0, lambda: None)
    app.processEvents()

    # Grab the card UNROLLED — stretched to its content height rather than
    # clipped to 440px. The question this tool answers is "what is this run
    # asking the card to show", and half of it is behind a scrollbar in the
    # real thing; a shot of the visible half hides exactly the clutter.
    panel._body.adjustSize()
    chrome = panel._header.sizeHint().height() + panel._rule.height()
    panel.setFixedSize(PANEL_WIDTH, chrome + panel._body.sizeHint().height())
    app.processEvents()

    panel.grab().save(out)

    print(f"{text!r} -> {out}  ({'dark' if dark else 'light'})")
    print(f"  {len(steps)} trace steps, brain {result.get('brain')}")
    print(_measure(panel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

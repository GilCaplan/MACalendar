"""A scrollbar the code reads is one PyQt can see die (TASKS 53).

`verticalScrollBar()` on a plain scroll area returns a wrapper for a
scrollbar Qt made, which PyQt keeps alive on the area's wrapper and is never
told about when Qt frees it. The next widget allocated at that address came
back from `findChildren` as a dead "QScrollBar", and the process segfaulted.
On CI that was the crash at teardown in test_hud_history_view (run 285, #65's
first run). It reproduced locally once each test deleted its HUD on time,
about one run in two, and this fix took it to 0 in 25.
"""

from __future__ import annotations

import gc
import pathlib
import re

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QObject  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _strays() -> list[str]:
    """Live wrappers for Qt objects Python did not create: each one can go
    stale without PyQt knowing."""
    gc.collect()
    return [type(o).__name__ for o in gc.get_objects()
            if isinstance(o, QObject) and not sip.isdeleted(o) and not sip.ispycreated(o)]


def test_a_used_and_deleted_card_leaves_no_wrapper_behind(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_TRACE_BUS", str(tmp_path / "bus.jsonl"))
    from PyQt6.QtCore import QCoreApplication, QEvent

    from assistant.thinking_hud import ThinkingHUD
    hud = ThinkingHUD()
    hud.show()
    hud.panel._scroll_to_bottom()
    hud.panel._scroll_llm_to_bottom()
    qapp.processEvents()
    assert sip.ispycreated(hud.panel._scroll.verticalScrollBar())

    hud.close()
    hud.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    del hud
    assert _strays() == []


def test_every_scrollbar_the_code_reads_is_owned():
    """Any module that asks a scroll area for its scrollbar gives it owned
    ones; a new caller without the helper goes red here, naming the file."""
    asks = re.compile(r"\.(vertical|horizontal)ScrollBar\(\)")
    missing = []
    for path in (ROOT / "assistant").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if asks.search(text) and "own_scrollbars(" not in text and path.name != "scrollbars.py":
            missing.append(str(path.relative_to(ROOT)))
    assert missing == [], f"read a scrollbar without own_scrollbars(): {missing}"

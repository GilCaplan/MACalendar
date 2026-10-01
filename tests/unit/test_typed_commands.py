"""Typing a command instead of saying it, on the Mac (Gil, 2026-10-01).

The ⌨ button (and ⌘K) opens a box; Enter hands the words to
`Pipeline.submit_typed`, which takes the spoken command's road from the words
on — combine mode, view context, magic words, the brain — so a typed command
behaves exactly like the same words said.
"""
from __future__ import annotations

import threading

import pytest

pytest.importorskip("PyQt6.QtWidgets")


def test_the_box_sends_what_was_typed_on_enter():
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLineEdit, QPushButton, QWidget
    from assistant.calendar_ui.window import CalendarWindow

    app = QApplication.instance() or QApplication([])
    sent = []

    class Pipe:
        def submit_typed(self, text):
            sent.append(text)
            return True

    host = QWidget()
    host._pipeline = Pipe()
    host._type_btn = QPushButton("⌨", host)
    host.resize(500, 200)
    host.show()
    CalendarWindow._open_type_box(host)
    app.processEvents()
    field = host._type_box.findChild(QLineEdit, "type_command_field")
    assert field is not None and field.isVisible()
    QTest.keyClicks(field, "lunch with Dana tomorrow at 1")
    QTest.keyClick(field, Qt.Key.Key_Return)
    app.processEvents()
    assert sent == ["lunch with Dana tomorrow at 1"]
    assert not host._type_box.isVisible()
    host.close()


def _pipe():
    from assistant import pipeline
    p = pipeline.Pipeline.__new__(pipeline.Pipeline)
    p._trigger_lock = threading.Lock()
    p._busy = threading.Event()
    p._phase = pipeline.STATUS_IDLE
    p._statuses = []
    p._set_status = lambda *a, **k: p._statuses.append(a)
    return p


def test_a_typed_command_takes_the_spoken_road(monkeypatch):
    from assistant import pipeline
    p = _pipe()
    seen, done = {}, threading.Event()

    class Trace:
        steps = []

        def step(self, *a, **k):
            self.steps.append(a)
    tr = Trace()
    p._trace_begin = lambda: tr

    def send(transcript, trace, t_start, **k):
        seen.update(transcript=transcript, raw=k.get("raw_transcript"), busy=p._busy.is_set())
        done.set()
    p._send_transcript = send
    assert p.submit_typed("  buy milk  ")
    assert done.wait(5)
    assert seen == {"transcript": "buy milk", "raw": "buy milk", "busy": True}
    assert tr.steps[0][1] == "Typed"
    for _ in range(100):
        if not p._busy.is_set():
            break
        threading.Event().wait(0.02)
    assert not p._busy.is_set(), "the pipeline stayed busy after a typed command"


def test_nothing_typed_or_already_busy_is_refused():
    p = _pipe()
    assert not p.submit_typed("   ")
    p._busy.set()
    assert not p.submit_typed("buy milk")
    assert any("Still working" in str(a) for a in p._statuses)

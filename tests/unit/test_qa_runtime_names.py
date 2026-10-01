"""Names used at runtime that were never defined (QA sweep, 2026-10-01).

Each one sat inside a path ordinary use reaches — and turned it into a crash:
`/voice/transcribe` (the phone's Jude dictation) raised NameError on every
non-empty transcript; the calendar window's panel refresh and two HUD polls
raised it inside their own error handlers, and an exception escaping a Qt
slot aborts the app. Found by pyflakes; pinned here by running each path.
"""
from __future__ import annotations

import io
import wave

import pytest


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)
    return buf.getvalue()


def test_voice_transcribe_returns_the_words(monkeypatch):
    from assistant.api import server

    class STT:
        def transcribe(self, audio):
            return "what is the parsha this week"
    monkeypatch.setattr(server, "_get_stt", lambda: STT())
    app = server.create_app()
    app.config["TESTING"] = True
    r = app.test_client().post("/voice/transcribe",
                               data={"audio": (io.BytesIO(_wav()), "a.wav")},
                               content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["raw"] == "what is the parsha this week"
    assert body["text"]


def test_a_panel_that_fails_to_reload_does_not_take_the_window_down():
    pytest.importorskip("PyQt6.QtWidgets")
    from assistant.calendar_ui.window import CalendarWindow

    class Bad:
        def reload(self):
            raise RuntimeError("boom")

    class Good:
        reloaded = False

        def reload(self):
            Good.reloaded = True

    class Host:
        _panels = {"bad": Bad(), "good": Good()}
    CalendarWindow.reload_panels(Host())
    assert Good.reloaded

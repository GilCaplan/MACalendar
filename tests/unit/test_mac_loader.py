"""TASKS 48 — the loading screen on the Mac.

The drawing is the phone's (`EggLoaderRender`, Swift, in the magic-words
helper). Python's part is small and is what is pinned here: a command is
bracketed by `wait_begin` / `wait_end` whatever happens to it, and the
thinking card — a separate process that cannot ask the helper — plays the
frames the helper wrote beside the settings.
"""
from __future__ import annotations

import json

import pytest


def _frames(tmp_path, monkeypatch, n=6, enabled=True):
    from PyQt6.QtGui import QColor, QImage
    d = tmp_path / "loader" / "abc123"
    d.mkdir(parents=True)
    for i in range(n):
        img = QImage(44, 44, QImage.Format.Format_ARGB32)
        img.fill(QColor(255, 0, 0))             # loud, so the card's pixels show it
        img.save(str(d / f"{i:03d}.png"))
    (tmp_path / "loader" / "current.json").write_text(json.dumps(
        {"dir": str(d), "frames": n, "fps": 15, "enabled": enabled, "caption": "x"}))
    monkeypatch.setenv("MACALENDAR_MAGIC_WORDS", str(tmp_path))
    monkeypatch.setattr("sys.platform", "darwin")


def test_loader_frames_reads_what_the_helper_wrote(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6.QtGui")
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from assistant import magic_words
    _frames(tmp_path, monkeypatch)
    info = magic_words.loader_frames()
    assert info and info["frames"] == 6


def test_loader_off_means_no_frames(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6.QtGui")
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from assistant import magic_words
    _frames(tmp_path, monkeypatch, enabled=False)
    assert magic_words.loader_frames() is None


def test_the_thinking_card_plays_the_loader_while_working(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from assistant.calendar_ui import command_graph as cg
    _frames(tmp_path, monkeypatch)
    cg._LOADER.update(dir=None, pix=[], checked=-1e9)
    from assistant.calendar_ui.thinking_panel import _Theme
    w = cg.CommandGraphView(_Theme(True))
    w.resize(360, 200)
    w.set_graph(cg.Graph(running=True))
    img = w.grab().toImage()
    reds = sum(1 for x in range(0, 60) for y in range(img.height() - 30, img.height())
               if img.pixelColor(x, y).red() > 200 and img.pixelColor(x, y).green() < 60)
    assert reds > 50, "the loader's frame is drawn in the foot"
    w.set_graph(cg.Graph(running=False))       # done: the frames go
    img = w.grab().toImage()
    reds = sum(1 for x in range(0, 60) for y in range(img.height() - 30, img.height())
               if img.pixelColor(x, y).red() > 200 and img.pixelColor(x, y).green() < 60)
    assert reds == 0
    app.processEvents()


def test_a_command_closes_its_wait_even_when_the_api_is_down(monkeypatch):
    """`wait_end` runs in a `finally`: a wait left open would leave the
    "taking a while" card up over every app until the helper restarts."""
    import urllib.request
    from assistant import magic_words, pipeline
    seen = []
    monkeypatch.setattr(magic_words, "wait_begin", lambda: seen.append("begin") or "w1")
    monkeypatch.setattr(magic_words, "wait_end", lambda wid: seen.append(("end", wid)))

    def down(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", down)

    class Trace:
        def step(self, *a, **k): pass
    p = pipeline.Pipeline.__new__(pipeline.Pipeline)
    p.config = type("C", (), {"api": type("A", (), {"port": 1, "key": None})()})()
    p._tts = type("T", (), {"speak": lambda self, m: None})()
    p._set_status = lambda *a, **k: None
    p._trace_result = lambda **k: None
    p.current_view = "calendar"
    p._trace_run = None
    monkeypatch.setattr(pipeline, "_identity", lambda port: ("dev", "tok"))
    assert p._process_transcript("add milk", Trace(), 0.0) is False
    assert seen == ["begin", ("end", "w1")]

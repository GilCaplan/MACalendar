"""The live microphone meter beside the Mac's mic button (mic_meter.py).

Gil, 2026-10-09: see that the audio is being captured, "so that I know that
I'm not just talking to the air". The phone draws the same scale in
VoiceButton.swift's ListeningMeter.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from assistant.calendar_ui import mic_meter  # noqa: E402
from assistant.calendar_ui.mic_meter import MicLevelMeter, to_level  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_scale_runs_from_room_noise_to_a_raised_voice():
    assert to_level(0.0) == 0.0                       # silence: an empty bar
    assert to_level(10 ** (-55 / 20)) == pytest.approx(0.0, abs=1e-6)
    assert to_level(10 ** (-10 / 20)) == pytest.approx(1.0)
    assert to_level(1.0) == 1.0                       # clipped, never past full
    assert 0.3 < to_level(10 ** (-35 / 20)) < 0.6     # ordinary speech: mid-way


def test_it_shows_while_listening_and_hides_after(app):
    m = MicLevelMeter()
    assert m.isHidden()                               # nothing until it listens
    m.start(lambda: 0.1)
    assert not m.isHidden()
    m.stop()
    assert m.isHidden()


def test_the_bars_follow_the_source(app):
    m = MicLevelMeter()
    level = [0.0]
    m.start(lambda: level[0])
    m._tick()
    assert list(m._levels)[-1] == 0.0
    level[0] = 0.35                                   # −9 dB: past the top, full
    m._tick()
    assert list(m._levels)[-1] == pytest.approx(1.0)
    level[0] = 0.0                                    # falls over frames, not at once
    m._tick()
    assert 0.0 < list(m._levels)[-1] < 1.0
    m.stop()


def test_no_sound_after_two_seconds_turns_it_into_a_warning(app, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(mic_meter.time, "monotonic", lambda: clock[0])
    m = MicLevelMeter()
    m.start(lambda: 0.0)
    m._tick()
    assert not m.silent                               # too soon to say
    clock[0] += mic_meter.SILENT_AFTER_S + 0.1
    m._tick()
    assert m.silent
    assert "No sound" in m.toolTip()
    m.stop()


def test_one_loud_moment_clears_the_warning_for_the_take(app, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(mic_meter.time, "monotonic", lambda: clock[0])
    level = [0.2]
    m = MicLevelMeter()
    m.start(lambda: level[0])
    m._tick()
    level[0] = 0.0
    clock[0] += 10
    m._tick()
    assert not m.silent
    m.stop()


def test_a_broken_source_draws_silence_instead_of_raising(app):
    m = MicLevelMeter()

    def boom():
        raise RuntimeError("pipeline gone")

    m.start(boom)
    m._tick()
    m.repaint()
    assert list(m._levels)[-1] == 0.0
    m.stop()

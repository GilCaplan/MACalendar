"""No audio system is no microphone, not a calendar that cannot open.

CI's runner image started failing PortAudio's start-up on import
(2026-10-29: "PulseAudio_Initialize: Can't connect to server"). sounddevice
raises from its own import then, and assistant.audio.capture imported it at
module level, so everything that imports the pipeline (the calendar window,
eleven Qt test files) died at import. A Mac whose audio daemon is wedged
hits the same path.
"""
import builtins
import importlib
import sys

import pytest


@pytest.fixture
def broken_audio():
    real_import = builtins.__import__

    class PortAudioError(Exception):
        pass

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise PortAudioError("Error initializing PortAudio: Can't connect to server")
        return real_import(name, *args, **kwargs)

    import assistant.audio.capture as capture
    import assistant.audio.probe as probe
    real_sd = sys.modules.pop("sounddevice", None)
    cached = probe._cached_profile
    probe._cached_profile = None
    builtins.__import__ = fake_import
    try:
        yield importlib.reload(capture), probe
    finally:
        # The real module back FIRST: reloading without it would import a
        # second sounddevice, and other files' patches of it would miss.
        builtins.__import__ = real_import
        if real_sd is not None:
            sys.modules["sounddevice"] = real_sd
        probe._cached_profile = cached
        importlib.reload(capture)


def test_capture_imports_and_recording_says_why(broken_audio):
    from assistant.config import AudioConfig
    from assistant.exceptions import AudioCaptureError
    capture, _probe = broken_audio
    assert capture.sd is None
    mic = capture.AudioCapture(AudioConfig())
    with pytest.raises(AudioCaptureError, match="microphone is unavailable"):
        mic.record_until_silence()


def test_probe_reports_no_audio_instead_of_raising(broken_audio):
    _capture, probe = broken_audio
    profile = probe.probe_audio(force=True)
    assert profile.permission_ok is False
    assert any("No audio system" in w for w in profile.warnings)

"""Each device transcribes its own recordings (Gil, 2026-10-10: "whatever
device it comes from, just use that one … we don't want to do double work").

The phone sends the words its on-device recogniser heard to /voice/stream
with `heard_on: "phone"`; the Mac must run them as the command WITHOUT
calling Whisper, and say where they came from. Model-free: the engine and
the STT are stubbed, as in test_voice_supports_edit.
"""
from __future__ import annotations

import json
import types

import pytest

import assistant.api.server as server


@pytest.fixture
def calls(monkeypatch):
    got = {"engine": [], "whisper": 0}
    import assistant.engine as engine

    def fake_run(transcript, **kw):
        got["engine"].append(transcript)
        return {"message": "ok", "actions": [], "refresh": "",
                "parse": "rule", "trace": [], "brain": "engine-v2"}

    def whisper(_np):
        got["whisper"] += 1
        return "whisper heard this"

    monkeypatch.setattr(engine, "run_transcript", fake_run)
    monkeypatch.setattr(server, "_get_stt", lambda: types.SimpleNamespace(transcribe=whisper))
    monkeypatch.setattr("assistant.api.audio_utils.audio_bytes_to_numpy", lambda _b: [0.0])
    return got


@pytest.fixture
def client():
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _steps(resp) -> list[dict]:
    lines = [json.loads(x) for x in resp.get_data(as_text=True).splitlines() if x.strip()]
    return [x for x in lines if x.get("type") == "step"]


def test_the_phones_words_run_without_whisper(client, calls):
    r = client.post("/voice/stream", json={"transcript": "lunch with dana at noon",
                                           "heard_on": "phone", "source": "test"})
    assert r.status_code == 200
    steps = _steps(r)
    assert calls["whisper"] == 0, "the Mac transcribed a command the phone already had"
    assert calls["engine"] == ["lunch with dana at noon"]
    stt = [s for s in steps if s.get("stage") == "stt"]
    assert [s["title"] for s in stt] == ["Heard on your phone"]
    assert not any("Whisper" in (s.get("detail") or "") for s in steps)


def test_typed_text_is_still_called_typed(client, calls):
    r = client.post("/voice/stream", json={"transcript": "buy eggs", "source": "test"})
    assert [s["title"] for s in _steps(r) if s.get("stage") == "stt"] == ["Typed"]
    assert calls["whisper"] == 0


def test_a_recording_with_no_phone_transcript_still_gets_whisper(client, calls):
    """The fallback: a phone that could not transcribe (no permission, no
    on-device recognition, or the setting off) sends audio, as before."""
    import io
    r = client.post("/voice/stream", data={"audio": (io.BytesIO(b"RIFFfake"), "a.wav")})
    assert r.status_code == 200
    assert calls["whisper"] == 1
    assert calls["engine"] == ["whisper heard this"]


def test_the_phone_side_sends_text_when_it_heard_some():
    """Pinned from the Swift source, as the other iOS behaviour pins are."""
    import pathlib
    app = pathlib.Path(__file__).resolve().parents[2] / "MACalendar-iOS" / "MACalendar-iOS"
    button = (app / "Views" / "VoiceButton.swift").read_text()
    client = (app / "API" / "APIClient.swift").read_text()
    store = (app / "LocalStore.swift").read_text()
    assert '"heard_on": "phone"' in client
    send = button[button.index("private func send(_ audioData: Data, heard: String"):]
    send = send[:send.index("\n    private func ", 10)]
    assert "heard.isEmpty" in send and "sendHeardStreaming(heard" in send
    assert "sendAudioStreaming(audioData" in send          # the fallback stays
    # a queued command the phone transcribed replays as text
    assert "heardOnPhone == true" in store[store.index("var outgoingText"):]

"""A queued command sent twice runs once.

2026-09-28: "Walk Jada every day…" reached the Mac three times in 55 s — the
phone's offline queue resends a command whose upload it lost track of — and
booked three identical 12-event series. The phone now sends its own id for a
queued command as `client_id`, and the server runs each id once.
"""
from __future__ import annotations

import threading
import time

import pytest

from assistant.api import receipts


@pytest.fixture(autouse=True)
def _fresh():
    receipts._reset()
    yield
    receipts._reset()


def test_a_resend_after_the_run_gets_the_same_answer_and_runs_nothing():
    calls = []
    fn = lambda: calls.append(1) or {"message": "Created 'walk jada'", "parse": "rule"}
    first = receipts.run_once("abc-1", fn)
    again = receipts.run_once("abc-1", fn)
    assert len(calls) == 1
    assert again["message"] == first["message"] and again["duplicate"] is True


def test_a_resend_while_the_first_is_still_running_waits_for_it():
    """The observed case: the second upload arrived 40 s into the first run."""
    calls, started = [], threading.Event()

    def slow():
        calls.append(1)
        started.set()
        time.sleep(0.3)
        return {"message": "done once", "parse": "rule"}

    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", receipts.run_once("abc-2", slow)))
    t.start()
    started.wait(2)
    out["b"] = receipts.run_once("abc-2", slow)
    t.join(2)
    assert len(calls) == 1
    assert out["a"]["message"] == out["b"]["message"] == "done once"


def test_no_id_means_no_dedupe():
    calls = []
    receipts.run_once("", lambda: calls.append(1) or {})
    receipts.run_once(None, lambda: calls.append(1) or {})
    assert len(calls) == 2


def test_a_failed_run_frees_its_id_so_a_real_retry_still_runs():
    def boom():
        raise RuntimeError("model down")
    with pytest.raises(RuntimeError):
        receipts.run_once("abc-3", boom)
    assert receipts.run_once("abc-3", lambda: {"message": "ok"})["message"] == "ok"


def test_an_error_response_is_not_kept():
    """A non-dict (a Flask error response) is passed through and not stored."""
    calls = []
    receipts.run_once("abc-4", lambda: calls.append(1) or ("err", 500))
    receipts.run_once("abc-4", lambda: calls.append(1) or ("err", 500))
    assert len(calls) == 2


def test_the_id_is_bounded_and_cleaned():
    assert receipts.clean("A1-b2_c3;DROP TABLE" + "x" * 100) == ("A1-b2_c3DROPTABLE" + "x" * 100)[:64]


def test_the_voice_text_route_runs_a_repeated_client_id_once(monkeypatch):
    """Through the real route, with the Flask test client."""
    from assistant.api import server
    runs = []

    def fake_run(transcript, trace=None, **kw):
        runs.append(transcript)
        return {"message": f"ran {transcript}", "actions": [], "refresh": "none", "parse": "rule"}

    app = server.create_app()
    # _run_transcript is a closure inside create_app; patch the engine entry it calls
    import assistant.engine as eng
    monkeypatch.setattr(eng, "run_transcript", fake_run)
    c = app.test_client()
    body = {"transcript": "walk jada every day", "source": "test", "client_id": "q-77"}
    r1 = c.post("/voice/text", json=body).get_json()
    r2 = c.post("/voice/text", json=body).get_json()
    assert runs == ["walk jada every day"]
    assert r1["message"] == r2["message"] and r2.get("duplicate") is True
    # a different id is a different command
    c.post("/voice/text", json=dict(body, client_id="q-78"))
    assert len(runs) == 2


def test_the_same_recording_uploaded_again_runs_once_even_without_an_id(monkeypatch):
    """An app too old to send `client_id` resent the same 493.3 KB recording a
    fourth time; the recording's own bytes are the id."""
    import io
    from assistant.api import server
    import assistant.engine as eng
    runs = []
    monkeypatch.setattr(eng, "run_transcript",
                        lambda t, trace=None, **kw: runs.append(t) or
                        {"message": "ran", "actions": [], "refresh": "none", "parse": "rule"})
    import assistant.api.audio_utils as au
    monkeypatch.setattr(au, "audio_bytes_to_numpy", lambda b: b)
    app = server.create_app()
    stt = type("S", (), {"transcribe": lambda self, a: "walk jada every day"})()
    monkeypatch.setattr(server, "_get_stt", lambda: stt, raising=False)
    c = app.test_client()

    def post(data):
        return c.post("/voice", data={"audio": (io.BytesIO(data), "a.wav")},
                      content_type="multipart/form-data")

    r1, r2 = post(b"RIFF-same-bytes"), post(b"RIFF-same-bytes")
    assert r1.status_code == r2.status_code == 200, (r1.data, r2.data)
    assert len(runs) == 1 and r2.get_json().get("duplicate") is True
    post(b"RIFF-other-bytes")
    assert len(runs) == 2

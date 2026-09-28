"""The phone's offline reader and its protocol with the Mac (assistant/offline).

Gil, 2026-09-28: the phone reads a command itself with Apple's on-device model
when the Mac is away, and the Mac's engine re-reads it on reconnect and wins.
These pin the Mac's half: the served spec, the comparison, the verdicts, the
log it is measured by, and that the Swift side was built for this protocol.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

import pytest

import assistant.api.server as server
from assistant.api import receipts
from assistant.offline import log, reconcile, spec

ROOT = pathlib.Path(__file__).resolve().parents[2]
SWIFT = ROOT / "MACalendar-iOS" / "MACalendar-iOS" / "Voice" / "OfflineReader.swift"


@pytest.fixture(autouse=True)
def _fresh_log(tmp_path, monkeypatch):
    monkeypatch.setattr(log, "OFFLINE_LOG", str(tmp_path / "offline_readings.jsonl"))
    receipts._reset()
    yield
    receipts._reset()


@pytest.fixture
def client(registry_with_real_actions):
    """The real rule parser: these commands are ones the rules answer on their
    own, so CI (no Ollama) runs the same path as the Mac."""
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _reading(*items, protocol=spec.PROTOCOL, text="book gym tomorrow at 7am"):
    return {"protocol": protocol, "schema": spec.SCHEMA, "reader": "apple-fm",
            "spec_version": spec.reader_spec()["version"], "text": text, "ms": 812,
            "items": list(items)}


def _tomorrow() -> str:
    return (dt.date.today() + dt.timedelta(days=1)).isoformat()


# -- the spec ------------------------------------------------------------------


def test_the_spec_is_versioned_by_its_text_not_by_a_number_someone_bumps(monkeypatch):
    a = spec.reader_spec()
    assert a["protocol"] == spec.PROTOCOL and a["schema"] == spec.SCHEMA
    assert a["may_commit"] == ["event", "todo"]          # never an edit or a delete
    assert spec.reader_spec()["version"] == a["version"]
    monkeypatch.setattr(spec, "INSTRUCTIONS", spec.INSTRUCTIONS + " Be brief.")
    assert spec.reader_spec()["version"] != a["version"]


def test_learning_a_word_is_not_a_new_reader_version(monkeypatch):
    before = spec.reader_spec()["version"]
    monkeypatch.setattr(spec, "_names", lambda limit=150: ["Technion"])
    after = spec.reader_spec()
    assert after["names"] == ["Technion"] and after["version"] == before


def test_every_example_is_in_the_compiled_shape():
    for ex in spec.EXAMPLES:
        for it in ex["items"]:
            assert set(it) == {"kind", "title", "date", "start", "end", "recurrence"}
            assert it["kind"] in spec.KINDS and it["recurrence"] in spec.RECURRENCES
            assert it["date"] == "" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", it["date"])


def test_the_phone_was_built_for_this_protocol_and_schema():
    """Bumping SCHEMA or PROTOCOL without the Swift side goes red here."""
    src = SWIFT.read_text()
    assert re.search(rf"static let schema\s*=\s*{spec.SCHEMA}\b", src)
    assert re.search(rf"static let protocolVersion\s*=\s*{spec.PROTOCOL}\b", src)
    for kind in spec.KINDS:
        assert f'"{kind}"' in src
    for rec in spec.RECURRENCES:
        assert f'"{rec}"' in src


# -- the comparison ---------------------------------------------------------------


def test_titles_match_on_the_words_not_the_spelling():
    assert reconcile.titles_match("Gym", "gym")
    assert reconcile.titles_match("Meeting with Avi", "meeting avi")
    assert reconcile.titles_match("Buy milk", "buy milk and eggs")
    assert not reconcile.titles_match("Dentist", "Gym")


def test_an_empty_end_on_the_phone_is_not_a_disagreement():
    phone = [{"kind": "event", "title": "Gym", "date": "2026-10-01", "start": "07:00",
              "end": "", "recurrence": ""}]
    mac = [{"kind": "event", "title": "gym", "date": "2026-10-01", "start": "07:00",
            "end": "08:00", "recurrence": ""}]
    assert reconcile.compare(phone, mac) == {"fields": [], "phone_only": [], "mac_only": []}


# -- end to end, through the real route -----------------------------------------------


def _post(client, reading, cid="c-1"):
    return client.post("/voice/text", json={
        "transcript": "book gym tomorrow at 7am", "source": "test",
        "client_id": cid, "offline_reading": reading}).get_json()


def test_the_mac_agreeing_says_same_and_logs_it(client):
    out = _post(client, _reading({"kind": "event", "title": "Gym", "date": _tomorrow(),
                                  "start": "07:00", "end": "", "recurrence": "none"}))
    assert out["committed"], "the engine lists what it wrote"
    assert out["offline"]["verdict"] == "same", out["offline"]
    assert out["offline"]["said"] == ""
    [row] = log.rows()
    assert row["verdict"] == "same" and row["reader"] == "apple-fm"
    assert row["phone_text"] == "book gym tomorrow at 7am"


def test_the_mac_reading_differently_says_changed_and_what_differed(client):
    out = _post(client, _reading({"kind": "event", "title": "Gym", "date": _tomorrow(),
                                  "start": "19:00", "end": "", "recurrence": "none"}))
    off = out["offline"]
    assert off["verdict"] == "changed"
    assert off["differences"]["fields"] == ["start"]
    assert "replaced the phone's" in off["said"]
    assert off["mac_items"][0]["start"] == "07:00"
    summary = client.get("/offline/agreement").get_json()
    assert summary["by_verdict"] == {"changed": 1} and summary["agreement"] == 0.0
    assert summary["differences"] == {"start": 1}


def test_a_resend_is_compared_and_logged_once(client):
    r = _reading({"kind": "event", "title": "Gym", "date": _tomorrow(), "start": "07:00",
                  "end": "", "recurrence": "none"})
    first = _post(client, r, cid="same-id")
    again = _post(client, r, cid="same-id")
    assert again["offline"] == first["offline"]
    assert len(log.rows()) == 1


def test_a_reading_that_booked_nothing_is_deferred(client):
    out = _post(client, _reading({"kind": "other", "title": "move my dentist", "date": "",
                                  "start": "", "end": "", "recurrence": "none"}))
    assert out["offline"]["verdict"] == "deferred"


def test_an_unknown_protocol_is_never_confirmed(client):
    out = _post(client, _reading({"kind": "event", "title": "Gym", "date": _tomorrow(),
                                  "start": "07:00", "end": "", "recurrence": "none"},
                                 protocol=99))
    assert out["offline"]["verdict"] == "unverified"


def test_no_reading_means_no_offline_block(client):
    out = client.post("/voice/text", json={"transcript": "book gym tomorrow at 7am",
                                            "source": "test"}).get_json()
    assert "offline" not in out and not log.rows()


def test_a_mac_whose_model_is_down_answers_pending():
    resp = {"parse": "error", "pending_id": 7, "message": "queued"}
    reconcile.attach(_reading({"kind": "todo", "title": "Buy milk", "date": "", "start": "",
                               "end": "", "recurrence": "none"}), resp)
    assert resp["offline"]["verdict"] == "pending"
    assert "stays until then" in resp["offline"]["said"]


def test_the_audio_route_takes_the_reading_as_a_form_field(client, monkeypatch):
    monkeypatch.setattr(server, "_get_stt", lambda: None, raising=False)
    reading = json.dumps(_reading({"kind": "todo", "title": "Buy milk", "date": "",
                                   "start": "", "end": "", "recurrence": "none"}))
    got = {}
    real = reconcile.attach

    def spy(r, resp, **kw):
        got["reading"] = r
        return real(r, resp, **kw)
    monkeypatch.setattr(reconcile, "attach", spy)
    from io import BytesIO
    client.post("/voice", data={"audio": (BytesIO(b"not audio"), "a.m4a"),
                                "client_id": "aud-1", "offline_reading": reading},
                content_type="multipart/form-data")
    assert json.loads(got["reading"])["items"][0]["title"] == "Buy milk"


def test_the_phone_can_ask_whether_a_queued_command_has_run(client):
    from assistant.intent.memory import get_memory
    pid = get_memory().add_pending("buy milk", "model offline", source="test")
    assert client.get(f"/offline/pending/{pid}").get_json()["status"] == "pending"
    get_memory().resolve_pending(pid, "done", "Added 'buy milk'")
    assert client.get(f"/offline/pending/{pid}").get_json()["status"] == "done"
    assert client.get("/offline/pending/999999").status_code == 404


def test_the_reader_spec_is_served(client):
    body = client.get("/offline/reader").get_json()
    assert body["version"] == spec.reader_spec()["version"]
    assert body["instructions"].startswith("You turn one spoken calendar command")

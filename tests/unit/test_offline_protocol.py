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
import shutil
import subprocess
import sys

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
            assert set(it) == {"kind", "title", "when", "start", "end", "recurrence"}
            assert it["kind"] in spec.KINDS and it["recurrence"] in spec.RECURRENCES
            assert not re.search(r"\d{4}-\d{2}-\d{2}", it["when"]), "the model gives WORDS, code the date"


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


# -- phone first, Mac behind (DEVQA Q87) -------------------------------------------


def _stream(client, reading):
    """The phone's live road: /voice/stream, NDJSON, the result last."""
    raw = client.post("/voice/stream", json={"transcript": "book gym tomorrow at 7am",
                                              "offline_reading": reading}).get_data(as_text=True)
    return [json.loads(line) for line in raw.splitlines() if line.strip()][-1]


def test_the_live_road_compares_what_the_phone_already_booked(client):
    r = _reading({"kind": "event", "title": "gym", "date": _tomorrow(), "start": "07:00",
                  "end": "", "recurrence": "none"})
    r.update(reader="phone-rules", live=True)
    out = _stream(client, r)
    assert out["type"] == "result" and out["offline"]["verdict"] == "same", out.get("offline")
    [row] = log.rows()
    assert row["live"] is True and row["reader"] == "phone-rules"


def test_the_live_road_says_changed_when_the_mac_read_it_differently(client):
    r = _reading({"kind": "event", "title": "gym", "date": _tomorrow(), "start": "19:00",
                  "end": "", "recurrence": "none"})
    r.update(reader="phone-rules", live=True)
    out = _stream(client, r)
    assert out["offline"]["verdict"] == "changed"
    assert out["offline"]["differences"]["fields"] == ["start"]


def test_a_live_command_without_a_reading_is_untouched(client):
    raw = client.post("/voice/stream", json={"transcript": "book gym tomorrow at 7am"})
    out = [json.loads(x) for x in raw.get_data(as_text=True).splitlines() if x.strip()][-1]
    assert "offline" not in out and not log.rows()


def test_agreement_is_reported_per_reader(client):
    rules = _reading({"kind": "event", "title": "gym", "date": _tomorrow(), "start": "07:00",
                      "end": "", "recurrence": "none"})
    rules.update(reader="phone-rules", live=True)
    _stream(client, rules)
    _post(client, _reading({"kind": "event", "title": "Gym", "date": _tomorrow(),
                            "start": "19:00", "end": "", "recurrence": "none"}), cid="fm-1")
    by = client.get("/offline/agreement").get_json()["by_reader"]
    assert by["phone-rules"] == {"scored": 1, "same": 1, "agreement": 1.0}
    assert by["apple-fm"] == {"scored": 1, "same": 0, "agreement": 0.0}


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


# -- the guard (DEVQA Q68 step 1) ---------------------------------------------------


GUARD_SWIFT = ROOT / "MACalendar-iOS" / "MACalendar-iOS" / "Voice" / "OfflineGuard.swift"


def test_the_guard_is_generated_from_the_engines_own_tables():
    """Every verb the engine routes to an edit, delete, completion or query —
    so the phone's guard and the Mac's routing cannot disagree."""
    from assistant.intent.rule_parser import INTENT_MAP
    g = spec.guard()
    for (verb, domain), action in INTENT_MAP.items():
        if action.startswith("create") or verb in ("set", "note"):
            continue
        if verb in spec.DONE_FRAMED:          # a completion only beside done/complete/…
            assert any(verb in f for f in g["frames"]), verb
            continue
        assert verb in g["leave_verbs"] + g["leave_verbs_with_domain"], verb
    assert "move" in g["leave_verbs"] and "remove" in g["leave_verbs_with_domain"]
    # a destructive verb LEADING the command is an edit even without a list word
    # (a miss books something wrong; a false guard only waits for the Mac)
    assert spec.LEAD_EDITS <= set(g["leave_verbs"])
    assert "book" not in g["leave_verbs"] + g["leave_verbs_with_domain"]


def test_the_phones_bundled_guard_is_the_served_one():
    """A phone that has never reached the Mac uses `GuardRules.bundled`; it must
    be exactly what the Mac would serve, or the two guard different things."""
    src = GUARD_SWIFT.read_text()
    src = src[src.index("static let bundled"):src.index("enum OfflineGuard")]
    g = spec.guard()

    def swift_array(name):
        m = re.search(rf"{name}: \[(.*?)\]", src, re.S)
        return re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))

    for key, name in (("leave_verbs", "leaveVerbs"), ("leave_verbs_with_domain", "leaveVerbsWithDomain"),
                      ("domain_words", "domainWords"), ("question_starts", "questionStarts"),
                      ("lead_ins", "leadIns")):
        assert swift_array(name) == g[key], key
    frames = re.findall(r'#"(.*?)"#', src)
    assert frames == g["frames"]


def test_the_served_spec_carries_the_guard(client):
    body = client.get("/offline/reader").get_json()
    assert body["guard"]["leave_verbs"] == spec.guard()["leave_verbs"]


# -- dates in code (DEVQA Q68 step 1) — the Swift resolver against the Python rules --


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"),
                    reason="needs the Swift compiler (the Mac; CI's Linux runner has none)")
def test_the_phones_day_resolver_matches_the_python_rules(tmp_path):
    """Every date phrase the FastRule set uses, plus the edge cases, resolved
    by OfflineDates.swift and by gold._phrase_to_date against four different
    todays — identical, or the phone reads dates by different rules."""
    from assistant.engine.fastrule.experiments.gold import _phrase_to_date
    exe = tmp_path / "dates"
    subprocess.run(["swiftc", "-O", "-parse-as-library",
                    str(ROOT / "assistant/offline/experiments/dates_parity.swift"),
                    str(ROOT / "MACalendar-iOS/MACalendar-iOS/Voice/OfflineDates.swift"),
                    "-o", str(exe)], check=True, capture_output=True)
    rows = [json.loads(l) for l in (ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl")
            .read_text().splitlines() if l.strip()]
    phrases = {(r["expect"].get("slots") or {}).get(k) or "" for r in rows
               for k in ("date_phrase", "date_phrase_2")} - {""}
    phrases |= {"this friday", "friday", "on the 15th", "next wednesday", "the 21st", "the 31st", "february 29th",
                "december 31st", "the end of next month", "in 3 days", "this weekend"}
    phrases = sorted(phrases)
    for today in ("2026-09-09", "2026-09-28", "2026-12-31", "2027-02-27"):
        out = subprocess.run([str(exe), today], input="\n".join(phrases) + "\n",
                             capture_output=True, text=True, check=True).stdout.splitlines()
        got = {o["p"]: o["d"] for o in map(json.loads, out)}
        for p in phrases:
            want = _phrase_to_date(p, dt.date.fromisoformat(today))
            if want is None and _phone_extension(p):
                # the phone's documented additions (a bare weekday, a leading
                # "on"): it resolves where the board's rules leave it open
                assert got[p] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", got[p]), (today, p)
                continue
            assert got[p] == want, (today, p)


def _phone_extension(p: str) -> bool:
    """Where the board's rules name no single day, the phone may still
    resolve a phrase that HAS one (a repeat's first day, a fixed offset, a
    named holiday) — never a range, which test_ranges_stay_with_the_mac pins."""
    return p not in _RANGES


_RANGES = {"next week", "next month", "this weekend", "next weekend", "this week", "this month"}


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"),
                    reason="needs the Swift compiler")
def test_the_phones_own_day_readings(tmp_path):
    """The phone's additions resolve to the ONE day they name; ranges stay open."""
    exe = tmp_path / "dates"
    subprocess.run(["swiftc", "-O", "-parse-as-library",
                    str(ROOT / "assistant/offline/experiments/dates_parity.swift"),
                    str(ROOT / "MACalendar-iOS/MACalendar-iOS/Voice/OfflineDates.swift"),
                    "-o", str(exe)], check=True, capture_output=True)
    cases = {                                   # today: Wednesday 2026-09-09
        "every sunday": "2026-09-13", "every other tuesday at 5 pm": "2026-09-15",
        "every tuesday and thursday": "2026-09-10", "daily": "2026-09-09",
        "every weekday": "2026-09-09", "this coming saturday": "2026-09-12",
        "in three weeks": "2026-09-30", "two weeks from now": "2026-09-23",
        "a week from today": "2026-09-16", "tomorrow week": "2026-09-17",
        "christmas day": "2026-12-25", "new year's eve": "2026-12-31",
        "next week": None, "next month": None, "this weekend": None,
    }
    out = subprocess.run([str(exe), "2026-09-09"], input="\n".join(cases) + "\n",
                         capture_output=True, text=True, check=True).stdout.splitlines()
    got = {o["p"]: o["d"] for o in map(json.loads, out)}
    assert got == cases

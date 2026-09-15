"""Only a real client may claim to be one.

An afternoon of testing this assistant with curl left 328 entries in the trace
bus that were indistinguishable from commands actually given to the phone,
because /voice/text defaulted an unlabelled caller to "ios". The history the
thinking card shows was then mostly noise, and there was nothing in the file to
tell the two apart afterwards.

Defaulting the other way makes the failure modes asymmetric in the right
direction: forgetting to label a test is harmless, and forgetting to label a
real client is immediately visible.
"""
from __future__ import annotations

import json

import pytest

import assistant.api.server as server


@pytest.fixture
def bus(tmp_path, monkeypatch):
    path = tmp_path / "bus.jsonl"
    monkeypatch.setattr("assistant.trace_bus.BUS_PATH", str(path))
    return path


@pytest.fixture
def client(registry_with_real_actions):
    """The real rule parser, deliberately.

    Stubbing it out forces the LLM path, and CI has no Ollama — the parse then
    errors before anything is written to the bus and every assertion here fails
    for a reason that has nothing to do with what is being tested. The commands
    below are ones the rules answer on their own.

    `registry_with_real_actions` is what makes that true, and its absence is
    why this file spent some time not testing what it says. `isolated_registry`
    empties the global ActionRegistry before EVERY test; without asking for the
    real actions back, the rule parser has nothing to build an intent from,
    scores 1.00 and still reports `missing-slots`, and the command falls
    through to the deep track. On a machine with Ollama running that is
    invisible — the model answers, the bus gets its line, the test passes
    green while exercising the exact path the docstring says it avoids. On CI,
    with no Ollama, it fails.
    """
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _sources(bus):
    """The distinct sources this bus recorded, in order.

    Reads only the lines that CARRY a source. Since the engine began streaming
    every run (2026-09-14) one command writes `begin` and `trace` — both
    labelled — plus `step` and `result` lines, which are keyed by run id and
    have no source of their own. Taking `["source"]` off every line raised
    KeyError on the first step; taking it off the labelled lines and
    de-duplicating keeps this test asserting exactly what it always asserted —
    which source a command was recorded under — rather than how many lines the
    bus happens to use to say it.
    """
    if not bus.exists():
        return []
    out = []
    for line in bus.read_text().splitlines():
        if not line.strip():
            continue
        src = json.loads(line).get("source")
        if src is not None and (not out or out[-1] != src):
            out.append(src)
    return out


@pytest.mark.parametrize("body, expected", [
    ({"transcript": "book gym tomorrow at 7am"}, "test"),                  # curl
    ({"transcript": "book gym tomorrow at 7am", "source": "mac"}, "mac"),  # the GUI
    ({"transcript": "book gym tomorrow at 7am", "source": "ios"}, "ios"),  # the phone
    ({"transcript": "book gym tomorrow at 7am", "source": "hax"}, "test"), # nonsense
    ({"transcript": "book gym tomorrow at 7am", "source": "  MAC  "}, "mac"),
])
def test_the_source_is_recorded_from_the_caller(client, bus, body, expected):
    client.post("/voice/text", json=body)
    assert _sources(bus) == [expected]


def test_an_unlabelled_caller_never_passes_as_a_phone(client, bus):
    """The specific regression: this used to default to "ios"."""
    client.post("/voice/text", json={"transcript": "remind me to buy milk"})
    assert "ios" not in _sources(bus)


# ---------------------------------------------------------------------------
# WHICH client, not just what KIND — the device half of the same rule
# ---------------------------------------------------------------------------

def test_the_device_id_reaches_the_engine(client, monkeypatch):
    """End to end over HTTP: a phone says which phone it is, and the engine
    holds it. Without this the whole two-iPhones fix is inert — the queue can
    only group on what the client actually sent."""
    seen = {}

    def _spy(text, trace=None, source="ios", device="", **kw):
        seen["source"], seen["device"] = source, device
        return {"message": "ok", "actions": [], "refresh": "", "parse": "fast",
                "transcript": text, "original_transcript": text,
                "corrections": [], "trace": [], "uncertain_words": []}

    monkeypatch.setattr("assistant.engine.run_transcript", _spy)
    client.post("/voice/text", json={"transcript": "book gym tomorrow at 7am",
                                     "source": "ios", "device_id": "phone-A"})
    assert seen == {"source": "ios", "device": "phone-A"}


def test_a_device_id_is_bounded_and_stripped(client, monkeypatch):
    """It is client-supplied, opaque, and reaches a log line and a SQL
    parameter. It is never parsed or matched, so the only properties that matter
    are stability and uniqueness — which means nothing is lost by refusing
    everything but id characters, and an unbounded string in a group key is a
    cheap way to be handed a 10MB one."""
    seen = {}

    def _spy(text, trace=None, source="ios", device="", **kw):
        seen["device"] = device
        return {"message": "ok", "actions": [], "refresh": "", "parse": "fast",
                "transcript": text, "original_transcript": text,
                "corrections": [], "trace": [], "uncertain_words": []}

    monkeypatch.setattr("assistant.engine.run_transcript", _spy)
    client.post("/voice/text", json={"transcript": "book gym tomorrow at 7am",
                                     "device_id": "a b/c;drop\ttable-1"})
    assert seen["device"] == "abcdroptable-1"

    client.post("/voice/text", json={"transcript": "book gym tomorrow at 7am",
                                     "device_id": "x" * 500})
    assert len(seen["device"]) == 64


def test_a_client_that_sends_no_device_id_is_accepted(client, monkeypatch):
    """Old clients must keep working — the field is additive."""
    seen = {}

    def _spy(text, trace=None, source="ios", device="", **kw):
        seen["device"] = device
        return {"message": "ok", "actions": [], "refresh": "", "parse": "fast",
                "transcript": text, "original_transcript": text,
                "corrections": [], "trace": [], "uncertain_words": []}

    monkeypatch.setattr("assistant.engine.run_transcript", _spy)
    r = client.post("/voice/text", json={"transcript": "book gym tomorrow at 7am",
                                         "source": "mac"})
    assert r.status_code == 200
    assert seen["device"] == ""


def test_two_phones_queue_separately_all_the_way_from_http(tmp_path, monkeypatch):
    """THE WHOLE POINT, through the real memory store rather than fake rows.

    Two phones each park a command while the model is away. The flush must run
    two batches, not one utterance containing both people's words.
    """
    from assistant.intent.memory import CommandMemory
    from assistant.api.server import retry_pending_once

    mem = CommandMemory(str(tmp_path / "mem.db"))
    mem.add_pending("book gym at 7", "offline", source="ios", device="phone-A")
    mem.add_pending("cancel my dentist", "offline", source="ios", device="phone-B")
    mem.add_pending("buy milk", "offline", source="ios", device="phone-A")

    seen: list = []
    ran = retry_pending_once(
        lambda text, **kw: (seen.append(text),
                            {"parse": "fast", "message": "ok"})[1], mem, 300)
    assert ran == 2, "two phones were spoken as one utterance"
    gym = next(t for t in seen if "gym" in t)
    assert "milk" in gym and "dentist" not in gym


def test_the_same_words_from_two_phones_are_two_rows(tmp_path):
    """Dedup is per stream. Two people asking "what's on today" are two
    questions; collapsing them answers one and silently drops the other."""
    from assistant.intent.memory import CommandMemory

    mem = CommandMemory(str(tmp_path / "mem.db"))
    a = mem.add_pending("what's on today", "offline", source="ios", device="phone-A")
    b = mem.add_pending("what's on today", "offline", source="ios", device="phone-B")
    again = mem.add_pending("what's on today", "offline", source="ios", device="phone-A")
    assert a != b, "two phones' identical questions collapsed into one row"
    assert again == a, "the same phone repeating itself is still a duplicate"


# ---------------------------------------------------------------------------
# Enrolment over HTTP, and what an imposter actually gets
# ---------------------------------------------------------------------------

def test_a_client_enrols_and_is_then_trusted(client, monkeypatch):
    """The whole loop: enrol once, then every request carries the token."""
    got = client.post("/devices/enroll",
                      json={"source": "ios", "label": "Gil's iPhone"}).get_json()
    assert got["device_id"].startswith("ios-")
    assert got["label"] == "Gil's iPhone"

    seen = {}

    def _spy(text, trace=None, source="ios", device="", stream="", **kw):
        seen["stream"], seen["device"] = stream, device
        return {"message": "ok", "actions": [], "refresh": "", "parse": "fast",
                "transcript": text, "original_transcript": text,
                "corrections": [], "trace": [], "uncertain_words": []}

    monkeypatch.setattr("assistant.engine.run_transcript", _spy)
    client.post("/voice/text",
                json={"transcript": "book gym tomorrow at 7am", "source": "ios",
                      "device_id": got["device_id"]},
                headers={"X-Device-Token": got["token"]})
    assert seen["stream"] == f"ios:{got['device_id']}", "a verified device was not trusted"


def test_an_imposter_with_the_real_id_lands_in_a_different_stream(client, monkeypatch):
    """THE ATTACK, end to end.

    Someone learns your phone's device id — from a log, a packet, a shoulder.
    They post as it, without the token. They must NOT join your phone's queue:
    if they did, their words would be concatenated into your backlog and
    executed as yours.
    """
    real = client.post("/devices/enroll",
                       json={"source": "ios", "label": "Gil's iPhone"}).get_json()
    streams: list = []

    def _spy(text, trace=None, source="ios", device="", stream="", **kw):
        streams.append(stream)
        return {"message": "ok", "actions": [], "refresh": "", "parse": "fast",
                "transcript": text, "original_transcript": text,
                "corrections": [], "trace": [], "uncertain_words": []}

    monkeypatch.setattr("assistant.engine.run_transcript", _spy)
    # the real phone
    client.post("/voice/text",
                json={"transcript": "buy milk", "source": "ios",
                      "device_id": real["device_id"]},
                headers={"X-Device-Token": real["token"]})
    # the imposter: same id, no token
    client.post("/voice/text",
                json={"transcript": "delete everything", "source": "ios",
                      "device_id": real["device_id"]})
    # …and with a made-up token
    client.post("/voice/text",
                json={"transcript": "delete everything", "source": "ios",
                      "device_id": real["device_id"], "device_token": "deadbeef"})

    assert streams[0] == f"ios:{real['device_id']}"
    assert streams[1] != streams[0], "an imposter joined the real phone's stream"
    assert streams[2] != streams[0], "a forged token was accepted"
    assert streams[1].startswith("ios:untrusted:")
    # The claimed id is never reflected verbatim into the grouping key.
    assert real["device_id"] not in streams[1]


def test_a_revoked_device_cannot_rejoin_its_old_stream(client, monkeypatch):
    real = client.post("/devices/enroll",
                       json={"source": "ios", "label": "old phone"}).get_json()
    assert client.post(f"/devices/{real['device_id']}/revoke").status_code == 200

    streams: list = []

    def _spy(text, trace=None, source="ios", device="", stream="", **kw):
        streams.append(stream)
        return {"message": "ok", "actions": [], "refresh": "", "parse": "fast",
                "transcript": text, "original_transcript": text,
                "corrections": [], "trace": [], "uncertain_words": []}

    monkeypatch.setattr("assistant.engine.run_transcript", _spy)
    client.post("/voice/text",
                json={"transcript": "buy milk", "source": "ios",
                      "device_id": real["device_id"]},
                headers={"X-Device-Token": real["token"]})
    assert streams[0] != f"ios:{real['device_id']}"
    assert streams[0].startswith("ios:untrusted:")


def test_enrolment_refuses_a_source_the_engine_does_not_know(client):
    r = client.post("/devices/enroll", json={"source": "hax", "label": "x"})
    assert r.status_code == 400


def test_the_user_can_see_what_is_talking_to_their_assistant(client, tmp_path,
                                                              monkeypatch):
    # A FRESH registry: the real one accumulates across a session, which is
    # correct behaviour (a device stays enrolled) and would make an exact-set
    # assertion here depend on which tests ran first.
    from assistant import model_protocol as mp
    monkeypatch.setattr(mp, "REGISTRY_PATH", tmp_path / "devices.json")
    a = client.post("/devices/enroll", json={"source": "ios", "label": "phone"}).get_json()
    client.post("/devices/enroll", json={"source": "mac", "label": "laptop"})
    listed = client.get("/devices").get_json()["devices"]
    assert {v["label"] for v in listed.values()} == {"phone", "laptop"}
    # …and the token is NEVER listed back. Knowing what enrolled must not be
    # the same as being able to impersonate it.
    assert all("token" not in v for v in listed.values())
    assert all(a["token"] not in str(v) for v in listed.values())

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

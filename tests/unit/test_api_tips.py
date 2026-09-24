"""GET /tips serves the one copy of the phrasing tips to every client.

The Mac reads `assistant.tips` in-process; the phone cannot, so it fetches
this (Gil, 2026-09-22, DEVQA Q41). Same words, same engine version — the
version test in `test_tips_current.py` covers both surfaces because there
is only one source.
"""
from __future__ import annotations

import assistant.trace as trace
from assistant.api import server
from assistant.tips import HINTS, STEPS, TIPS


def test_tips_endpoint_serves_the_tips_and_the_hints():
    app = server.create_app()
    got = app.test_client().get("/tips")
    assert got.status_code == 200
    body = got.get_json()
    assert body["brain"] == trace.BRAIN_VERSION
    # the "how it works" steps travel with the tips; the phone decodes the
    # key as optional, so an older host without it still loads
    assert body["steps"] == [{"text": t, "example": e} for t, e in STEPS]
    assert [t["headline"] for t in body["tips"]] == [h for h, _ in TIPS]
    assert all(t["body"] for t in body["tips"])
    assert set(body["hints"]) == set(HINTS)
    for code, (headline, text) in HINTS.items():
        assert body["hints"][code] == {"headline": headline, "body": text}

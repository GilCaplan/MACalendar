"""The iOS chain-info copy must match the host's STAGE_INFO.

The Mac review panel reads `assistant.trace.STAGE_INFO` directly; the iOS
`ThinkingView` carries a hand-mirrored Swift copy (`EngineChain.scaffold` in
ThinkingView.swift), because Swift can't import Python. This pins the two
together, so editing a step's explanation on one side but not the other fails
the build — the same drift guard `test_artifact_claims` gives the published
pages and `test_panel_agreement` gives the chain itself.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import assistant.trace as trace

from tests.unit._ios_sources import ios_source


def _norm(s: str) -> str:
    """Collapse whitespace so a body wrapped across Swift source lines still
    matches the single-line Python string."""
    return re.sub(r"\s+", " ", s).strip()


def test_ios_chain_info_matches_the_host():
    swift = _norm(ios_source("ThinkingView.swift"))
    for label, (heading, body) in trace.STAGE_INFO[trace.BRAIN_VERSION].items():
        assert _norm(label) in swift, (
            f"iOS scaffold (EngineChain.scaffold) is missing chain slot {label!r}")
        assert _norm(heading) in swift, (
            f"iOS scaffold is missing the heading {heading!r} for slot {label!r}")
        assert _norm(body) in swift, (
            f"iOS scaffold's in-depth copy for {label!r} has drifted from "
            "trace.STAGE_INFO — update EngineChain.scaffold in ThinkingView.swift")


# ---------------------------------------------------------------------------
# What the phone's timeline decodes
# ---------------------------------------------------------------------------

def test_the_response_carries_the_boundaries_the_phone_draws():
    """iOS renders the X0→X4 flow strip from `boundaries` in the voice
    response, and `ThinkingView` had no idea they existed until 2026-09-10 —
    the Mac drew them and the phone did not, which is backwards, since most
    commands are spoken to the phone.

    The server already sent them (the voice routes return the engine's whole
    result). This pins the shape `TraceBoundary` decodes, so dropping a field
    here fails the build rather than silently emptying the strip.
    """
    import assistant.engine as engine
    from assistant.trace import Trace

    tr = Trace()
    res = engine.run_transcript("book dentist tomorrow at 3", trace=tr,
                                source="test")
    bounds = res.get("boundaries")
    assert bounds, "the response carries no boundaries for the phone to draw"
    for b in bounds:
        assert set(("label", "value")) <= set(b), b
        assert isinstance(b["label"], str)
        assert isinstance(b.get("at_ms", 0), int), "at_ms decodes as Int? in Swift"

    # The strip draws X0..X4 and IGNORES anything else — there is already a
    # "verdict" boundary, and both clients look their labels up rather than
    # assuming every boundary is a pill. An X has to be present, though, or the
    # strip is empty for a reason no one would notice.
    assert any(b["label"].startswith("X") for b in bounds), bounds


def test_a_flagged_step_carries_its_kind_where_swift_reads_it():
    """`TraceStep.fastruleResult` is decoded out of the step's `data` bag, from
    the key `fastrule_result`. The two non-object outcomes are only tellable
    apart by it — one means an earlier stage handed the words over damaged, the
    other means they were read correctly and are simply not calendar work, and
    only the first is a defect.
    """
    from assistant.engine import load_config
    from assistant.engine.fastrule import stage as _stage
    from assistant.engine.state import EngineState, Item
    from assistant.trace import Trace

    for text, kind, expected in (("", "event", "bad_item"),
                                 ("thanks", "other", "not_an_ask")):
        st = EngineState(raw_text=text or "x", text=text or "x")
        st.trace = Trace()
        st.items = [Item(id="item_1", kind=kind, text=text)]
        _stage.run(st, load_config())

        flagged = [s for s in st.trace.to_list()
                   if (s.get("data") or {}).get("fastrule_result")]
        assert flagged, f"{expected}: no step carried a fastrule_result"
        assert flagged[0]["data"]["fastrule_result"] == expected
        assert st.items[0].slots.get("fastrule_result") == expected

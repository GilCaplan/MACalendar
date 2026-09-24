"""Save what is ready before the model reads the rest (Gil, 2026-09-24).

His six-ask command spent 48.9 s showing nothing, though 4 of its 6 objects
were built by the rules in 1.9 s; the loop wrote everything at the end. He
chose "save what's ready right away". The ready objects are written before the
model is called, exactly once, and the final commit skips them.
"""
from __future__ import annotations

import os
import sqlite3


def test_rule_built_objects_are_saved_before_the_model_and_only_once(registry_with_real_actions, monkeypatch):
    import assistant.engine as engine
    import assistant.engine.llm as L
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")          # the model door refuses...
    monkeypatch.setattr(L, "is_reachable", lambda cfg=None: True)  # ...but the deep track starts
    engine.run_transcript("walk the dog", source="test")       # warm
    said = ("Tomorrow I need to walk Val at 7.30am, then walk Jada at 9am, "
            "followed at, I need to go for a bike ride at 10am")
    out = engine.run_transcript(said, source="ios")
    steps = out.get("trace") or []
    at = {s.get("stage"): s.get("at_ms") for s in reversed(steps)}   # first of each stage
    executes = [s for s in steps if s.get("stage") == "execute" and s.get("ok", True)]
    assert executes, out.get("message")
    cross = [s for s in steps if s.get("stage") == "verify"]
    if cross:                                   # saved BEFORE the judge/model step
        assert executes[0]["at_ms"] <= cross[0]["at_ms"], steps
    db = sqlite3.connect(os.environ["MACALENDAR_DB"])
    titles = [r[0] for r in db.execute("select title from events")]
    assert titles.count("walk val") == 1, titles              # never written twice

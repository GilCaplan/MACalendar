"""A board's model calls are SEEDED; the live assistant's are not.

Board D v2 measured what an unseeded board costs (2026-09-22): two runs of the
1,200-row board at the same commit differed on 22 rows, none touched by the
thing being measured — the rescue's parse answering "book club" one time and
"club" the next. That is more rows than the board's two arms disagree on
(19), so a fixed/broke pair read through it is dice. `MACALENDAR_LLM_SEED`
pins `seed` and a temperature of 0 on every ollama door, read at call time
like the priority, and a board declares it in the same env block.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from assistant import llm_bus, model_protocol
from assistant.config import OllamaConfig
from assistant.intent.parser import IntentParser

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_no_seed_means_no_extra_options(monkeypatch):
    monkeypatch.delenv("MACALENDAR_LLM_SEED", raising=False)
    assert model_protocol.seed_options() == {}


def test_a_seed_pins_the_sampling(monkeypatch):
    monkeypatch.setenv("MACALENDAR_LLM_SEED", "17")
    assert model_protocol.seed_options() == {"seed": 17, "temperature": 0.0}


def test_a_seed_that_is_not_a_number_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setenv("MACALENDAR_LLM_SEED", "seventeen")
    assert model_protocol.seed_options() == {}


class _Resp:
    def __init__(self, content: str) -> None:
        self._c = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"content": self._c}}


def _parser(sent: list) -> IntentParser:
    """The transport alone: a parser with a config and a fake session, no
    registry, no model."""
    p = object.__new__(IntentParser)
    p.config = SimpleNamespace(ollama=OllamaConfig())

    class _Session:
        def post(self, url, json=None, timeout=None):
            sent.append(json)
            return _Resp("{}")
    p._session = _Session()
    return p


@pytest.fixture(autouse=True)
def _bus_in_scratch(tmp_path, monkeypatch):
    """The transport logs every call to the LLM console's bus, which lives in
    `~/.assistant_tools/` — a personal store, never test output."""
    monkeypatch.setattr(llm_bus, "BUS_PATH", str(tmp_path / "llm_calls.jsonl"))


def test_both_ollama_doors_carry_the_seed_when_the_process_is_seeded(monkeypatch):
    monkeypatch.delenv("MACALENDAR_LLM_DISABLED", raising=False)   # the suite disables it; this drives a FAKE session
    monkeypatch.setenv("MACALENDAR_LLM_SEED", "17")
    sent: list = []
    p = _parser(sent)
    p._call_ollama("sys", "book gym tomorrow at 7", {"type": "object"})
    p._call_ollama_verify("sys", "user")
    assert len(sent) == 2
    for payload in sent:
        assert payload["options"]["seed"] == 17, payload
        assert payload["options"]["temperature"] == 0.0, payload
        assert payload["options"]["num_ctx"] == OllamaConfig().num_ctx


def test_the_live_assistant_is_untouched_without_a_seed(monkeypatch):
    monkeypatch.delenv("MACALENDAR_LLM_DISABLED", raising=False)   # the suite disables it; this drives a FAKE session
    monkeypatch.delenv("MACALENDAR_LLM_SEED", raising=False)
    sent: list = []
    p = _parser(sent)
    p._call_ollama("sys", "book gym tomorrow at 7", {"type": "object"})
    p._call_ollama_verify("sys", "user")
    main, verify = sent
    assert "seed" not in main["options"] and "seed" not in verify["options"]
    assert main["options"]["temperature"] == OllamaConfig().temperature
    assert verify["options"]["temperature"] == 0.0        # by design, unchanged


def test_board_d_declares_its_seed_in_its_env_block():
    """Read from the tree, like the background-priority rule: a board that
    forgets is invisible to every other check and its net is dice."""
    text = (ROOT / "assistant/engine/llmjudge/experiments/board_d.py").read_text()
    head = text.split("def main", 1)[0]
    assert 'os.environ.setdefault("MACALENDAR_LLM_SEED"' in head


def test_the_disabled_flag_stops_both_ollama_doors(monkeypatch):
    """`MACALENDAR_LLM_DISABLED=1` used to stop only `engine.llm.call_json`;
    the rescue reached the model through this transport regardless
    (2026-09-24: 14 s of ollama calls on a "model-free" run)."""
    from assistant.exceptions import OllamaUnavailableError
    monkeypatch.setenv("MACALENDAR_LLM_DISABLED", "1")
    sent: list = []
    p = _parser(sent)
    with pytest.raises(OllamaUnavailableError):
        p._call_ollama("sys", "book gym tomorrow at 7", {"type": "object"})
    with pytest.raises(OllamaUnavailableError):
        p._call_ollama_verify("sys", "user")
    assert sent == []

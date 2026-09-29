"""Integration tests exercise the REAL model, so they switch LLM calls back on.

`tests/conftest.py` sets MACALENDAR_LLM_DISABLED=1 for the whole suite, which
is right for unit tests (fast, deterministic, never a live model). But the
integration tests that call Ollama already skip themselves when it isn't
running — with it running, the global switch made them FAIL instead
(`OllamaUnavailableError: LLM calls are disabled`), which is how four of
them went red on a Mac with Ollama up (2026-09-28). The background priority
and the scratch stores from the root conftest still apply.
"""
import pytest


@pytest.fixture(autouse=True)
def _real_model_calls(monkeypatch):
    monkeypatch.delenv("MACALENDAR_LLM_DISABLED", raising=False)

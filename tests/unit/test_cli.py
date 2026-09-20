"""The health CLI — logic that needs no running server, and the guard that
keeps the engine layer in step with the engine (like test_panel_agreement)."""
from __future__ import annotations

import pytest

from assistant import cli


def test_info_lines_never_drag_a_layer_to_warning():
    c = cli.Check("x")
    c.add(True, "ok"); c.info("just so you know")
    assert c.status is True                      # info is weightless
    c.add(None, "a real warning")
    assert c.status is None
    c.add(False, "broken")
    assert c.status is False


def test_endpoints_lists_the_api_surface(capsys):
    assert cli.main(["endpoints"]) == 0
    out = capsys.readouterr().out
    assert "/voice/text" in out and "/heartbeat" in out and "routes" in out


def test_storage_and_engine_layers_run_without_a_server():
    # these read local files / import modules; no API needed
    assert cli.check_storage().status in (True, False, None)
    eng = cli.check_engine()
    assert any("brain version" in t for _s, t in eng.rows)


def test_base_url_honours_the_env_port(monkeypatch):
    monkeypatch.setenv("MACALENDAR_API_PORT", "9191")
    assert cli._base_url().endswith(":9191")


# --- the version-coupling guard ---------------------------------------------

def test_the_engine_layer_covers_every_real_engine_stage():
    """Every folder under engine/ is verified by the doctor, so a new
    component can never be silently missed."""
    import pkgutil
    import assistant.engine as E
    from assistant.cli import ENGINE_STAGES
    modules = " ".join(m for _c, m in ENGINE_STAGES)
    # Modules that are INFRASTRUCTURE, not stages. `boundary` joined them on
    # 2026-09-10: it renders the value crossing between two stages for the
    # review panel, so it has no `run(state, cfg)` and nothing for the doctor
    # to check that checking the stages does not already cover. `fastrule` is
    # NOT here — it is a real stage folder, and ENGINE_STAGES covers it with
    # several `assistant.engine.fastrule.*` entries (build.py, fast_track.py,
    # stage.py, fastrule.py); excluding it here would hide that check ever
    # missing one of them.
    _NOT_A_STAGE = ("state", "llm", "component", "boundary", "__init__")
    real = {m.name for m in pkgutil.iter_modules(E.__path__)
            if m.name not in _NOT_A_STAGE}
    for stage in real:
        assert f"assistant.engine.{stage}" in modules, (
            f"engine folder '{stage}' exists but cli.ENGINE_STAGES imports nothing "
            "from it — add it (see DOCUMENTATION/CLI.md, version-tied)")


def test_the_engine_layer_names_every_stage_the_chain_declares():
    """The OTHER direction, which was missing and cost a year of drift.

    The old guard only asked "does every folder appear?". It could not see a
    NAME the doctor verifies that the engine no longer uses, so `("generate",
    ...)` survived long after that stage was renamed `fastrule` at the
    2026-09-08 rewire, and `doctor` reported a chain the engine had stopped
    running. state.STAGES is what the chain actually runs."""
    from assistant.cli import ENGINE_STAGES
    from assistant.engine.state import STAGES
    named = {comp for comp, _m in ENGINE_STAGES}
    missing = [s for s in STAGES if s not in named]
    assert not missing, (
        f"state.STAGES declares {missing} but cli.ENGINE_STAGES never names them — "
        "the doctor would report a chain it does not check")


def test_the_engine_layer_names_no_stage_that_does_not_exist():
    """And the reverse of that: a name the doctor verifies must be a real
    stage, or a retired component keeps being reported as healthy."""
    from assistant.cli import ENGINE_STAGES
    from assistant.engine.state import STAGES
    extra = {c for c, _m in ENGINE_STAGES} - set(STAGES) - {"LLM_one_shot"}
    assert not extra, (
        f"cli.ENGINE_STAGES names {sorted(extra)}, which state.STAGES does not "
        "declare — a renamed or retired stage is still being reported")


def test_every_module_the_engine_layer_claims_actually_imports():
    """A path in the list that has rotted should fail here, not in production.
    `segmentation.old_seg.segment` (retired 2026-09-20) was the ONLY segmenter the doctor imported
    long after FastSeg became the default — it verified the one that does not
    run."""
    import importlib
    from assistant.cli import ENGINE_STAGES
    for _component, module in ENGINE_STAGES:
        importlib.import_module(module)

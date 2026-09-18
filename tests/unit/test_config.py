"""Unit tests for config loading and validation."""

import os
import textwrap

import pytest
import yaml

from assistant.config import AppConfig, load_config
from assistant.exceptions import ConfigError


def _write_config(tmp_path, content: str) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return str(p)


VALID_YAML = """
hotkey:
  modifiers: ["cmd", "shift"]
  key: "space"
microsoft:
  client_id: "abc-123"
"""


def test_valid_config_loads(tmp_path):
    path = _write_config(tmp_path, VALID_YAML)
    config = load_config(path)
    assert config.hotkey.key == "space"
    assert config.microsoft.client_id == "abc-123"
    assert config.confirmation_level == 1  # default


def test_defaults_applied(tmp_path):
    path = _write_config(tmp_path, VALID_YAML)
    config = load_config(path)
    assert config.stt_engine == "whisper"
    assert config.whisper.model_size == "base"
    assert config.audio.sample_rate == 16000
    assert config.tts.voice == "Samantha"


def test_missing_required_field_raises(tmp_path):
    # hotkey is required
    path = _write_config(tmp_path, "confirmation_level: 1\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_yaml_raises(tmp_path):
    path = _write_config(tmp_path, "hotkey: {bad yaml: [unclosed")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_file_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/path/config.yaml")


def test_invalid_modifier_raises(tmp_path):
    content = VALID_YAML + "  # extra\n"
    # Override modifier
    data = yaml.safe_load(textwrap.dedent(VALID_YAML))
    data["hotkey"]["modifiers"] = ["superkey"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(data))
    with pytest.raises(ConfigError):
        load_config(str(path))


def test_confirmation_level_out_of_range_raises(tmp_path):
    data = yaml.safe_load(textwrap.dedent(VALID_YAML))
    data["confirmation_level"] = 5
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(data))
    with pytest.raises(ConfigError):
        load_config(str(path))


def test_env_var_overrides_ollama_model(tmp_path, monkeypatch):
    path = _write_config(tmp_path, VALID_YAML)
    monkeypatch.setenv("ASSISTANT_OLLAMA_MODEL", "mistral:7b")
    config = load_config(path)
    assert config.ollama.model == "mistral:7b"


def test_env_var_overrides_stt_engine(tmp_path, monkeypatch):
    path = _write_config(tmp_path, VALID_YAML)
    monkeypatch.setenv("ASSISTANT_STT_ENGINE", "google")
    config = load_config(path)
    assert config.stt_engine == "google"


# ---------------------------------------------------------------------------
# The lock-screen agenda card's switch is SHARED (Gil, 2026-09-17: "make sure
# toggle value is synced with calendar app accordingly").
#
# It is iPhone-only behaviour, so the temptation is to leave it in the phone's
# UserDefaults. Then the Mac's settings screen and the phone's disagree about a
# value both claim to own, and a reinstall silently turns it back on. It lives
# in `notifications:` instead, alongside `daily_digest`, which is shared for the
# same reason.
# ---------------------------------------------------------------------------

def test_the_agenda_card_switch_is_part_of_the_shared_config():
    from assistant.config import NotificationsConfig
    assert NotificationsConfig().agenda_card is True, "must default ON"
    assert NotificationsConfig(agenda_card=False).agenda_card is False


def test_the_agenda_card_switch_survives_a_yaml_round_trip():
    """The Mac writes it and the API reads it back — through YAML, not memory."""
    import yaml
    from assistant.config import NotificationsConfig

    for value in (True, False):
        text = yaml.safe_dump({"notifications": {"agenda_card": value}})
        loaded = yaml.safe_load(text)["notifications"]
        assert NotificationsConfig(**loaded).agenda_card is value


def test_an_older_config_with_no_agenda_card_key_still_loads():
    """`config.yaml` is gitignored and hand-edited, so most real files predate
    this key. A missing key must mean "on", not a validation error."""
    from assistant.config import NotificationsConfig
    cfg = NotificationsConfig(**{"daily_digest": True, "digest_time": "07:00"})
    assert cfg.agenda_card is True


def test_the_example_config_documents_it():
    """config.yaml is gitignored, so config.example.yaml is the only place a new
    checkout can learn the setting exists."""
    import pathlib
    import yaml
    root = pathlib.Path(__file__).resolve().parents[2]
    example = yaml.safe_load((root / "config.example.yaml").read_text())
    assert "agenda_card" in example["notifications"], \
        "a new setting must be mirrored into config.example.yaml"
    assert example["notifications"]["agenda_card"] is True

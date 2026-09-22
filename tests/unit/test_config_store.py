"""The section-scoped, comment-preserving config writer."""
from __future__ import annotations

from assistant.config_store import set_values

SAMPLE = """# my config
tts:
  mute: false   # keep quiet?
  rate: 200
  voice: "Samantha"

ui:
  theme: "light"
  rate: 999     # a DIFFERENT rate — must never be touched by tts.rate

observance:
  latitude: 31.7683
"""


def _write(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(SAMPLE)
    return p


def test_rewrites_are_section_scoped(tmp_path):
    p = _write(tmp_path)
    assert set_values({"tts": {"rate": 180}}, str(p))
    out = p.read_text()
    assert "  rate: 180" in out
    assert "rate: 999     # a DIFFERENT rate" in out   # ui.rate untouched


def test_comments_survive_everywhere(tmp_path):
    p = _write(tmp_path)
    set_values({"tts": {"mute": True}}, str(p))
    out = p.read_text()
    assert "# my config" in out
    assert "mute: true   # keep quiet?" in out         # inline comment kept


def test_missing_key_is_inserted_into_its_section(tmp_path):
    p = _write(tmp_path)
    set_values({"observance": {"enabled": False}}, str(p))
    out = p.read_text()
    sec = out.split("observance:")[1]
    assert "enabled: false" in sec
    assert "latitude: 31.7683" in sec


def test_missing_section_is_appended(tmp_path):
    p = _write(tmp_path)
    set_values({"brandnew": {"key": "wren", "n": 3}}, str(p))
    out = p.read_text()
    assert "brandnew:\n  key: \"wren\"\n  n: 3" in out


def test_types_render_as_yaml_literals(tmp_path):
    p = _write(tmp_path)
    set_values({"tts": {"voice": "Daniel", "rate": 150, "mute": False}}, str(p))
    out = p.read_text()
    assert 'voice: "Daniel"' in out and "rate: 150" in out and "mute: false" in out


def test_missing_file_writes_nothing(tmp_path):
    assert set_values({"a": {"b": 1}}, str(tmp_path / "nope.yaml")) is False


def test_a_hash_inside_a_quoted_value_is_not_read_as_a_comment(tmp_path):
    """Real corruption, 2026-09-15: `ui.accent_color: "#f5a524"` compounded
    into `"#f5a524"#f5a524'` after repeated saves, because the old
    value-vs-comment split had no idea a `#` can sit inside a quoted
    string."""
    p = tmp_path / "config.yaml"
    p.write_text('ui:\n  accent_color: "#f5a524"\n  theme: "dark"\n')
    set_values({"ui": {"accent_color": "#2288ff"}}, str(p))
    out = p.read_text()
    assert 'accent_color: "#2288ff"' in out
    assert "#f5a524" not in out
    assert 'theme: "dark"' in out           # neighbour untouched


def test_a_hash_in_a_value_with_a_real_trailing_comment_keeps_both(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('ui:\n  accent_color: "#f5a524"  # brand orange\n')
    set_values({"ui": {"accent_color": "#2288ff"}}, str(p))
    out = p.read_text()
    assert 'accent_color: "#2288ff"  # brand orange' in out


def test_rewriting_a_key_removes_its_old_block_list_lines(tmp_path):
    """Real corruption, 2026-09-15: `nlu.event_keywords` had been written as
    a YAML block list at some point; rewriting it to a flow list replaced
    only the header line and left the `-` lines as orphaned siblings —
    invalid YAML that made `AppConfig` refuse to load at all."""
    p = tmp_path / "config.yaml"
    p.write_text(
        "nlu:\n"
        "  event_keywords:\n"
        "  - meeting\n"
        "  - appointment\n"
        "  - activity\n"
        "notifications:\n"
        "  enabled: true\n"
    )
    set_values({"nlu": {"event_keywords": ["meeting", "lecture"]}}, str(p))
    out = p.read_text()
    assert '  event_keywords: ["meeting", "lecture"]' in out
    assert "- appointment" not in out
    assert "- activity" not in out
    assert "enabled: true" in out           # the next section untouched
    import yaml
    yaml.safe_load(out)                     # must still be valid YAML


def test_top_level_keys_and_lists(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("theme: \"light\"  # startup theme\nconfirmation_level: 1\n\naudio:\n  sample_rate: 16000\n")
    set_values({"": {"theme": "dark", "confirmation_level": 0},
                "audio": {"stop_phrases": ["execute", "done"]}}, str(p))
    out = p.read_text()
    assert 'theme: "dark"  # startup theme' in out          # comment kept
    assert "confirmation_level: 0" in out
    assert '  stop_phrases: ["execute", "done"]' in out     # inserted as flow list


def test_a_mapping_is_written_as_a_flow_mapping_and_reads_back_as_a_dict(tmp_path):
    """The dict case (2026-09-22). Until then a dict fell through to the string
    branch and came back from YAML as a STRING — the settings dialog carried its
    own writer for `notifications.category_leads` because of it."""
    import yaml
    from assistant import config_store
    p = tmp_path / "config.yaml"
    p.write_text("notifications:\n  enabled: true   # keep\n  category_leads:\n    Work: 15\n    Meal: 0\n\nother:\n  x: 1\n")
    assert config_store.set_values({"notifications": {"category_leads": {"Work": 30, "Family": 5}}}, path=str(p))
    text = p.read_text()
    assert "category_leads: {Family: 5, Work: 30}" in text, text
    assert "    Work: 15" not in text and "    Meal: 0" not in text     # the old block children are gone
    assert "# keep" in text
    data = yaml.safe_load(text)
    assert data["notifications"]["category_leads"] == {"Family": 5, "Work": 30}
    assert data["other"]["x"] == 1


def test_a_mapping_key_that_needs_quoting_is_quoted(tmp_path):
    import yaml
    from assistant import config_store
    p = tmp_path / "config.yaml"
    p.write_text("notifications:\n  enabled: true\n")
    assert config_store.set_values({"notifications": {"category_leads": {"Kids: school": 10}}}, path=str(p))
    assert yaml.safe_load(p.read_text())["notifications"]["category_leads"] == {"Kids: school": 10}

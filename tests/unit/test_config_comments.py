"""Writing a setting must not destroy the file's comments.

`config.yaml` is where the assistant is explained to its owner: what each block
is for, why a value is what it is, which ones are safe to change. It is also
GITIGNORED, so there is no copy to restore from.

`PATCH /features/<name>` and `PATCH /config` both did load → mutate →
`yaml.dump`. Every VALUE survived, so nothing looked wrong — and every comment
in the user's config was destroyed by toggling a tab from the phone. This pins
the fix.
"""

from __future__ import annotations

import yaml

from assistant.features import yaml_text

SAMPLE = '''# MACalendar configuration
#
# Copy config.example.yaml and edit.

ui:
  # Which tabs are shown on the Mac.
  show_timer: true      # the Timer tab
  font_month: 11

# Jude — the Judaic study assistant.
jude:
  enabled: true
  priority: background  # yields the model to voice commands

theme: dark
'''


def _comments(text: str) -> int:
    return sum(1 for line in text.split("\n") if "#" in line)


def test_setting_a_nested_flag_keeps_every_comment():
    out = yaml_text.set_nested(SAMPLE, "jude", "enabled", False)
    assert _comments(out) == _comments(SAMPLE)
    assert yaml.safe_load(out)["jude"]["enabled"] is False
    assert "yields the model to voice commands" in out


def test_adding_a_key_to_an_existing_block_keeps_comments():
    out = yaml_text.set_nested(SAMPLE, "ui", "show_week_numbers", True)
    assert _comments(out) == _comments(SAMPLE)
    d = yaml.safe_load(out)
    assert d["ui"]["show_week_numbers"] is True and d["ui"]["show_timer"] is True


def test_creating_a_missing_block_keeps_comments():
    out = yaml_text.set_nested(SAMPLE, "features", "coursework", False)
    assert _comments(out) == _comments(SAMPLE)
    assert yaml.safe_load(out)["features"]["coursework"] is False


def test_a_trailing_comment_on_the_edited_line_survives():
    out = yaml_text.set_nested(SAMPLE, "ui", "show_timer", False)
    assert "# the Timer tab" in out, "the note beside the value was dropped"
    assert yaml.safe_load(out)["ui"]["show_timer"] is False


def test_a_top_level_scalar_keeps_comments():
    out = yaml_text.set_top(SAMPLE, "theme", "light")
    assert _comments(out) == _comments(SAMPLE)
    assert yaml.safe_load(out)["theme"] == "light"


def test_nothing_else_in_the_file_moves():
    """Byte-for-byte apart from the one line — key ORDER included. The old
    `PATCH /config` dump also reordered the document."""
    out = yaml_text.set_nested(SAMPLE, "jude", "enabled", False)
    a, b = SAMPLE.split("\n"), out.split("\n")
    assert len(a) == len(b)
    differing = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    assert differing == [len(a) - len(a) + differing[0]] and len(differing) == 1


def test_values_that_could_be_reread_as_another_type_are_quoted():
    out = yaml_text.set_nested(SAMPLE, "jude", "priority", "true")
    assert yaml.safe_load(out)["jude"]["priority"] == "true", (
        "an unquoted 'true' would come back as a boolean")


def test_set_visible_through_the_real_writer(tmp_path, monkeypatch):
    """The end-to-end path a phone toggle takes."""
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE)
    monkeypatch.setenv("MACALENDAR_CONFIG", str(path))
    from assistant.features import settings
    settings.set_visible("coursework", False)
    after = path.read_text()
    assert _comments(after) == _comments(SAMPLE), "a tab toggle ate the comments"
    assert settings.is_visible("coursework", True) is False


def test_patch_config_writes_the_OVERRIDE_not_the_real_file(tmp_path, monkeypatch):
    """`PATCH /config` must honour `MACALENDAR_CONFIG`.

    It did not until 2026-09-18: `_CONFIG_PATH` was hard-coded to the repo root,
    so this endpoint wrote the user's live config.yaml whatever the environment
    said. That is the one file `conftest.py` redirects on purpose AND the one
    that is gitignored, so a bad write has nothing to restore from. It was found
    the only way it could be — by a sandboxed script setting the override
    correctly and still changing Gil's theme to light.
    """
    import os
    import yaml as _yaml

    target = tmp_path / "config.yaml"
    target.write_text('theme: dark\nui:\n  accent_color: "#f5a524"\n')
    monkeypatch.setenv("MACALENDAR_CONFIG", str(target))

    # Re-imported so the module constant is rebuilt against the override.
    import importlib
    import assistant.api.server as server
    importlib.reload(server)

    app = server.create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    repo_config = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(server.__file__)))), "config.yaml")
    before = (open(repo_config).read() if os.path.exists(repo_config) else None)

    assert client.patch("/config", json={"theme": "light"}).status_code == 200

    assert _yaml.safe_load(target.read_text())["theme"] == "light", \
        "the override was not written"
    if before is not None:
        assert open(repo_config).read() == before, \
            "the REAL config.yaml was modified by a test"

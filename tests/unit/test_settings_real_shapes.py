"""The settings dialog against the shapes Gil's Mac actually has.

The dialog crashed the live app on open — not with a traceback in a log, but
with SIGABRT: PyQt6 turns an unhandled exception inside a slot into qFatal(),
so an AttributeError raised while building the dialog takes the whole calendar
process (and, via the launcher, the API and the HUD) down with it.

    AttributeError: 'Pipeline' object has no attribute '_confirmer'

`Pipeline._confirmer` was deleted in e3ea4f6 ("Delete the Mac's dead half"),
when parsing and execution moved into the API process — but the dialog kept
reading it, and BOTH settings suites' `_Pipeline` doubles had invented one, so
the suites stayed green while the real app aborted. That is the whole lesson of
this file: **the doubles here are deliberately no more capable than the real
objects.** `_StrictPipeline` raises AttributeError for anything the real
Pipeline does not have, so the next attribute the dialog invents fails here
rather than on Gil's screen.

The rest is the same class of failure, from the other real store:

* his config.yaml predates the notifications and observance work, so it has
  NO `notifications:`, `observance:` or `engine:` section — the dialog must
  open against the pydantic defaults and the save must CREATE those sections;
* ~/.assistant_tools/categories.json is hand-editable and merged over the
  defaults, so a row can carry a null colour, a colour Qt cannot parse, a
  non-ascii name, or a duplicate of another row's name. A bad row must degrade
  to the default dot / Default lead, never abort the dialog.
"""
from __future__ import annotations

import json
import queue

import pytest

pytest.importorskip("PyQt6")

import yaml                                                          # noqa: E402
from PyQt6.QtCore import QPoint, Qt, QTimer                          # noqa: E402
from PyQt6.QtTest import QTest                                       # noqa: E402
from PyQt6.QtWidgets import (                                        # noqa: E402
    QApplication, QCheckBox, QComboBox, QPushButton, QWidget,
)

from assistant import config_store                                   # noqa: E402
from assistant.actions.calendar import categories as categories_mod  # noqa: E402
from assistant.calendar_ui.settings_dialog import open_settings      # noqa: E402
from assistant.config import load_config                             # noqa: E402
from assistant.tts.speaker import Speaker                            # noqa: E402

# A faithful trim of the live config.yaml: the sections it HAS, and none of the
# three it does not. Anything the dialog reads out of notifications/observance/
# engine therefore comes from the pydantic defaults, and saving has to create
# those sections rather than assume them.
REAL_SHAPED_CONFIG = """\
hotkey:
  modifiers: [ctrl]
  key: "j"

stt_engine: "mlx"

ollama:
  model: "llama3.1:8b"

confirmation_level: 0
verify_fast_path: true
self_check_apply: false

audio:
  review_before_send: true
  review_seconds: 3

tts:
  mute: false
  voice: "Samantha"
  rate: 200

nlu:
  event_keywords: [meeting, appointment, activity]

theme: "dark"  # "light" | "dark" - default theme on startup

ui:
  font_month: 19
  accent_color: "#f5a524"
  show_timer: true
  show_workout: false
  show_coursework: false
  thinking_auto_open: true  # a key pydantic does not declare — must be ignored

hebrew_calendar:
  display_mode: "both"
  show_holidays: true
  israel_holidays: true
"""

# Hand-edited categories.json, merged over the built-in defaults by
# categories._load(). Every entry here is a shape the dot-drawing or the
# per-category combo used to be assumed away.
ODD_CATEGORIES = {
    "categories": [
        # Overrides a BUILT-IN category's colour with null. QColor(None) raises
        # TypeError — this is the entry that would abort the dialog.
        {"name": "Work", "color": None},
        # A colour Qt cannot parse: QColor() is constructed but invalid, so the
        # brush would be drawn with an undefined colour.
        {"name": "Bad Colour", "color": "not-a-colour"},
        # Non-ascii, spaces and an emoji in a name used verbatim as a widget
        # objectName and as a YAML mapping key on save.
        {"name": "Café Meetings ☕", "color": "#ff8800"},
        # No colour key at all.
        {"name": "No Colour Key"},
        # Blank name — categories._load() drops it; asserted so a change there
        # does not quietly start producing a nameless row.
        {"name": "   ", "color": "#123456"},
        # The same new name twice: categories._load() snapshots its index
        # before the merge loop, so BOTH are appended and all_categories()
        # really does return two rows called "Duplicated".
        {"name": "Duplicated", "color": "#111111"},
        {"name": "Duplicated", "color": "#222222"},
    ]
    # …plus MANY more, appended below.
    + [{"name": f"Custom {i}", "color": "#3366aa"} for i in range(30)],
    "removed": [],
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def real_config(tmp_path):
    """A real AppConfig parsed from a real-shaped config.yaml (scratch copy)."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(REAL_SHAPED_CONFIG)
    cfg = load_config(str(cfg_file))
    # The premise of every test below.
    raw = yaml.safe_load(REAL_SHAPED_CONFIG)
    assert "notifications" not in raw
    assert "observance" not in raw
    assert "engine" not in raw
    return cfg, cfg_file


@pytest.fixture
def odd_categories(tmp_path, monkeypatch):
    """Point the category store at the hand-edited file and clear its cache.

    CATEGORIES_PATH is a module constant read at import time (see
    tests/conftest.py), so the env var is too late here — the attribute is
    patched instead, and the mtime cache reset either side.
    """
    path = tmp_path / "categories.json"
    path.write_text(json.dumps(ODD_CATEGORIES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(categories_mod, "CATEGORIES_PATH", str(path))
    monkeypatch.setattr(categories_mod, "_cache", None)
    monkeypatch.setattr(categories_mod, "_mtime", -1.0)
    yield path
    categories_mod._cache, categories_mod._mtime = None, -1.0


# ── doubles that are no more capable than the real objects ───────────


class _StrictPipeline:
    """assistant.pipeline.Pipeline's surface, and nothing the real one lacks.

    `_tts` is the REAL Speaker. Everything the window merely wires up is a
    no-op callable — but any *attribute* the dialog reaches for that the real
    Pipeline does not define raises, exactly as it does on Gil's Mac.
    """

    #: what the real Pipeline has and the dialog is allowed to touch
    _REAL_ATTRS = {"_tts", "status_queue", "config", "registry", "trigger",
                   "health_check", "speak"}

    def __init__(self, cfg):
        self._tts = Speaker(cfg.tts)
        self.status_queue: queue.Queue = queue.Queue()

    def __getattr__(self, name):
        if name in self._REAL_ATTRS:
            return lambda *a, **k: None
        raise AttributeError(f"'Pipeline' object has no attribute {name!r}")


class _Btn:
    def __init__(self):
        self.visible = True

    def setVisible(self, visible):
        self.visible = visible


class _Window(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self._pipeline = _StrictPipeline(cfg)
        self._config = cfg
        self._dark = cfg.theme == "dark"
        self._view_mode = "month"
        self._view_btn_coursework = _Btn()
        self._view_btn_workout = _Btn()
        self._view_btn_timer = _Btn()

    def show_toast(self, *_):
        pass

    def refresh_calendar(self):
        pass

    def _apply_ui_config(self):
        pass

    def _apply_theme(self, _dark):
        pass

    def _set_view(self, _mode):
        pass


def _drive(interact, failures):
    """Run interaction against the modal once it is up (see the sibling suites)."""
    def _go():
        from PyQt6 import sip as _sip   # a stale wrapper segfaulted Linux CI (TASKS 53)
        dlg = QApplication.activeModalWidget()
        if dlg is None or _sip.isdeleted(dlg) or not dlg.isVisible() or dlg.objectName() != "settings_dialog":
            QTimer.singleShot(10, _go)
            return
        try:
            interact(dlg)
        except Exception as e:                # noqa: BLE001 — re-raised below
            failures.append(e)
            dlg.reject()
    QTimer.singleShot(0, _go)


def _click(widget):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier,
                     QPoint(8, widget.height() // 2))


# ── the tests ────────────────────────────────────────────────────────


def test_the_odd_category_file_really_is_odd(odd_categories):
    """The fixture only means something if the loader passes the mess through."""
    cats = categories_mod.all_categories()
    by_name: dict[str, list] = {}
    for c in cats:
        by_name.setdefault(c["name"], []).append(c)
    assert by_name["Work"][0]["color"] is None          # the aborting entry
    assert by_name["Bad Colour"][0]["color"] == "not-a-colour"
    assert "Café Meetings ☕" in by_name
    assert len(by_name["Duplicated"]) == 2              # a genuine duplicate
    assert "   " not in by_name and "" not in by_name   # blank name dropped
    assert len(cats) > 40                               # MANY categories


def test_dialog_opens_with_the_real_pipeline_and_a_sectionless_config(
        app, real_config, odd_categories):
    """The crash, as a test: no `_confirmer`, no notifications/observance
    sections, and a category file full of bad rows — the dialog still opens."""
    cfg, _ = real_config
    window = _Window(cfg)
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        auto = next(cb for cb in dlg.findChildren(QCheckBox)
                    if cb.text().startswith("Auto-approve"))
        # Sourced from config.confirmation_level (0), NOT from the pipeline.
        seen["auto"] = auto.isChecked()
        # Defaults stood in for the three absent sections.
        seen["observance"] = dlg.findChild(QCheckBox, "observance_enabled_cb").isChecked()
        seen["notif"] = dlg.findChild(QCheckBox, "notif_enabled_cb").isChecked()
        lead = dlg.findChild(QComboBox, "notif_default_lead_combo")
        seen["lead"] = (lead.currentText(), lead.currentData())
        # Every odd row still rendered, at Default.
        for name in ("Work", "Bad Colour", "Café Meetings ☕", "No Colour Key",
                     "Duplicated", "Custom 29"):
            combo = dlg.findChild(QComboBox, f"notif_cat_lead_{name}")
            assert combo is not None, f"category row {name!r} missing"
            seen[f"row:{name}"] = combo.currentText()
        # The duplicate collapsed to a single row rather than two combos
        # fighting over one objectName.
        seen["dup_rows"] = len(dlg.findChildren(QComboBox, "notif_cat_lead_Duplicated"))
        dlg.reject()

    _drive(interact, failures)
    open_settings(window)                    # must not raise → must not qFatal
    if failures:
        raise failures[0]

    assert seen["auto"] is True              # confirmation_level: 0
    assert seen["observance"] is True        # ObservanceConfig default
    assert seen["notif"] is True             # NotificationsConfig default
    assert seen["lead"] == ("Off", 0)        # default_lead_minutes: 0
    assert seen["dup_rows"] == 1
    for name in ("Work", "Bad Colour", "Café Meetings ☕", "No Colour Key",
                 "Duplicated", "Custom 29"):
        assert seen[f"row:{name}"] == "Default"


def test_saving_creates_the_sections_the_live_config_never_had(
        app, real_config, odd_categories, monkeypatch):
    """Save against a config with no notifications/observance section: both are
    created, category_leads lands as a mapping, and a non-ascii category name
    survives the round-trip as a YAML key."""
    cfg, cfg_file = real_config
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg_file): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg_file))

    window = _Window(cfg)
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        # The per-category rows sit in a fold that starts closed (2026-10-01):
        # open it as a person would, then use the row.
        _click(dlg.findChild(QWidget, "section_header_notifications"))
        fold = dlg.findChild(QWidget, "subfold_reminders_by_category")
        if not fold.isChecked():
            _click(fold)
        cafe = dlg.findChild(QComboBox, "notif_cat_lead_Café Meetings ☕")
        assert cafe.isVisibleTo(dlg), "the row is still folded away"
        assert cafe is not None, "the non-ascii category has no row"
        QTest.keyClicks(cafe, "M")                  # → "Muted" (0)
        seen["cafe"] = (cafe.currentText(), cafe.currentData())
        auto = next(cb for cb in dlg.findChildren(QCheckBox)
                    if cb.text().startswith("Auto-approve"))
        _click(auto)                                # on → off
        seen["auto_after_click"] = auto.isChecked()
        save = dlg.save_button
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen["cafe"] == ("Muted", 0)
    assert seen["auto_after_click"] is False

    data = yaml.safe_load(cfg_file.read_text())
    # Sections that did not exist before the save.
    assert data["notifications"]["enabled"] is True
    assert data["notifications"]["default_lead_minutes"] == 0
    assert data["notifications"]["category_leads"] == {"Café Meetings ☕": 0}
    assert data["observance"]["enabled"] is True
    assert data["engine"]["confirm_transcript"] is False
    # The one setting the auto-approve checkbox really drives.
    assert data["confirmation_level"] == 1
    assert cfg.confirmation_level == 1            # and in memory
    # Untouched neighbours and comments survive.
    assert data["hebrew_calendar"]["display_mode"] == "both"
    assert '# "light" | "dark" - default theme on startup' in cfg_file.read_text()


def test_a_pathological_category_list_does_not_abort_the_dialog(
        app, real_config, monkeypatch):
    """Entries categories._load() would never emit, in case something else
    does: a non-dict row, a None name, a name that is only whitespace."""
    cfg, _ = real_config
    monkeypatch.setattr(categories_mod, "all_categories", lambda: [
        "not a dict",
        None,
        {"name": None, "color": "#ffffff"},
        {"name": "  ", "color": "#ffffff"},
        {"color": "#ffffff"},                       # no name key at all
        {"name": "Survivor", "color": "#00ff00"},
    ])

    window = _Window(cfg)
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        seen["survivor"] = dlg.findChild(QComboBox, "notif_cat_lead_Survivor") is not None
        seen["rows"] = len([c for c in dlg.findChildren(QComboBox)
                            if (c.objectName() or "").startswith("notif_cat_lead_")])
        dlg.reject()

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert seen["survivor"] is True
    assert seen["rows"] == 1        # only the one usable entry got a row


def test_a_config_missing_a_brand_new_field_still_saves(app, real_config, monkeypatch):
    """The calendar GUI does not reload itself.

    So it can be running a config module from BEFORE a setting existed while
    lazily importing `settings_dialog` fresh from disk the moment Settings is
    opened. Gil hit exactly that on 2026-09-18: a new `agenda_card` checkbox
    raised `"NotificationsConfig" object has no field "agenda_card"` on a machine
    whose config.yaml had just been written perfectly well, and the dialog
    reported it as "Could not save config.yaml".

    A config object that refuses an unknown field must not turn a successful save
    into a failed one — the value is already on disk by then, and a restart picks
    it up.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QMessageBox, QPushButton
    cfg, cfg_path = real_config

    # The dialog catches its own exceptions and shows them, so the failure is a
    # MESSAGE BOX rather than a traceback. Record instead of display.
    shown: list = []
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.append(a[2] if len(a) > 2 else a)))

    class _Strict:
        """Refuses anything it was not born with, the way pydantic does."""
        __slots__ = ("enabled", "default_lead_minutes", "respect_observance",
                     "speak", "sound", "category_leads")

        def __init__(self):
            self.enabled = True
            self.default_lead_minutes = 0
            self.respect_observance = True
            self.speak = False
            self.sound = True
            self.category_leads = {}

    cfg.notifications = _Strict()                 # no `agenda_card`, on purpose
    window = _Window(cfg)
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        save = dlg.save_button
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert not shown, (
        "saving with a config that lacks a newly-added field must not report an "
        f"error — it showed: {shown}")


def test_settings_tabs_has_an_account_switch_that_hides_the_tab(
        app, real_config, odd_categories, monkeypatch):
    """Settings › Tabs is drawn from the feature registry (Gil, 2026-09-28:
    "add account to tabs as an additional toggle on settings"), so Account is
    there beside Timer, and unticking it + Save hides it through `features:`."""
    cfg, cfg_file = real_config
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg_file): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg_file))
    monkeypatch.setenv("MACALENDAR_CONFIG", str(cfg_file))
    from assistant.features import registry as feats

    window = _Window(cfg)
    window._view_btn_account = _Btn()
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        names = {cb.objectName() for cb in dlg.findChildren(QCheckBox)
                 if cb.objectName().startswith("tab_cb_")}
        seen["names"] = names
        box = dlg.findChild(QCheckBox, "tab_cb_account")
        seen["before"] = box.isChecked()
        _click(box)
        save = dlg.save_button
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]

    assert {"tab_cb_account", "tab_cb_timer", "tab_cb_coursework"} <= seen["names"]
    assert "tab_cb_calendar" not in seen["names"]          # pinned: no switch
    assert seen["before"] is True
    assert yaml.safe_load(cfg_file.read_text())["features"]["account"] is False
    assert not feats.get("account").visible()
    assert window._view_btn_account.visible is False


def test_emoji_in_titles_is_one_setting_in_two_places(app, real_config, odd_categories, monkeypatch):
    """TASKS 51: Gil asked for the switch under Easter egg AND under
    Assistant. Two combos, one value: changing either moves the other, and
    the save writes `title_emoji.count` (a section the live config lacks)."""
    cfg, cfg_file = real_config
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg_file): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg_file))
    window = _Window(cfg)
    failures: list = []
    seen: dict = {}

    def interact(dlg):
        here = dlg.findChild(QComboBox, "title_emoji")
        there = dlg.findChild(QComboBox, "title_emoji_egg")
        assert here is not None and there is not None
        seen["start"] = (here.currentText(), there.currentText())
        QTest.keyClicks(here, "T")                  # → "Two"
        seen["moved"] = (here.currentData(), there.currentData())
        save = dlg.save_button
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]
    assert seen["start"] == ("None", "None")
    assert seen["moved"] == (2, 2)
    assert yaml.safe_load(cfg_file.read_text())["title_emoji"]["count"] == 2
    assert cfg.title_emoji.count == 2


def test_which_kinds_of_emoji_is_chosen_in_a_dialog_and_saved(app, real_config, odd_categories, monkeypatch):
    """The kinds (Gil, 2026-10-01): a "Which kinds…" button opens one switch
    per kind; unticking Food and pressing OK, then Save, writes food: false."""
    cfg, cfg_file = real_config
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg_file): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg_file))
    window = _Window(cfg)
    failures: list = []
    seen: dict = {}

    def in_kinds():
        try:
            from PyQt6.QtWidgets import QDialog, QDialogButtonBox
            d = next(w for w in QApplication.topLevelWidgets()
                     if w.objectName() == "title_emoji_kinds_dialog" and w.isVisible())
            food = d.findChild(QCheckBox, "title_emoji_kind_food")
            seen["food_before"] = food.isChecked()
            _click(food)
            ok = d.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
            QTest.mouseClick(ok, Qt.MouseButton.LeftButton)
        except Exception as e:                      # surfaced after the dialog closes
            failures.append(e)

    def interact(dlg):
        btn = dlg.findChild(QPushButton, "title_emoji_kinds")
        assert btn is not None
        QTimer.singleShot(150, in_kinds)
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        save = dlg.save_button
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    open_settings(window)
    if failures:
        raise failures[0]
    assert seen["food_before"] is True
    data = yaml.safe_load(cfg_file.read_text())["title_emoji"]
    assert data["food"] is False and data["animals"] is True
    assert cfg.title_emoji.food is False


# -- the Jewish calendar: off for a new install, one switch to turn it on ------

def test_a_new_install_ships_with_the_jewish_calendar_off():
    """Gil, 2026-10-02: "the whole Jewish thing off by default and then user
    can put it on". config.example.yaml is what a new Mac copies."""
    import pathlib
    import yaml
    ex = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "config.example.yaml").read_text())
    assert ex["hebrew_calendar"]["display_mode"] == "english"
    assert ex["hebrew_calendar"]["show_holidays"] is False
    assert ex["hebrew_calendar"]["show_shabbat_times"] is False
    assert ex["observance"]["enabled"] is False
    assert not any(ex["occasions"][k] for k in ("parasha", "omer", "rosh_chodesh"))
    assert ex["title_emoji"]["jewish"] is False


def test_the_jewish_calendar_switch_sets_every_part(app, real_config, odd_categories, monkeypatch):
    from PyQt6.QtWidgets import QCheckBox
    cfg, cfg_file = real_config
    real = config_store.set_values
    monkeypatch.setattr(config_store, "set_values",
                        lambda updates, path=str(cfg_file): real(updates, path))
    monkeypatch.setattr(config_store, "CONFIG_PATH", str(cfg_file))
    cfg.hebrew_calendar.show_holidays = True                 # whatever the fixture's file says
    window = _Window(cfg)
    failures: list = []

    def interact(dlg):
        master = dlg.findChild(QCheckBox, "jewish_calendar_cb")
        assert master.isChecked()                       # the suite's config has it on
        master.setChecked(False)
        assert not dlg.findChild(QCheckBox, "observance_enabled_cb").isChecked()
        assert not dlg.findChild(QCheckBox, "occasions_parasha").isChecked()
        master.setChecked(True)
        assert dlg.findChild(QCheckBox, "shabbat_lines_cb").isChecked()
        master.setChecked(False)
        QTest.mouseClick(dlg.save_button, Qt.MouseButton.LeftButton)

    _drive(interact, failures)
    from assistant.calendar_ui.settings_dialog import open_settings
    open_settings(window)
    if failures:
        raise failures[0]
    import yaml
    data = yaml.safe_load(cfg_file.read_text())
    assert data["hebrew_calendar"]["show_holidays"] is False and data["hebrew_calendar"]["display_mode"] == "english"
    assert data["observance"]["enabled"] is False

"""Which phone settings travel to the Mac, and which stay on the phone.

DEVQA Q87 (Gil, 2026-10-10): "the only configurations relevant for that device
is on that device". How each SCREEN looks — the theme, the accent colour, how
the Hebrew calendar is drawn — is per device. What the ASSISTANT does is
shared, and so, by his answer, are spoken replies and completed tasks.

Read from the Swift source: the phone has no test target CI can run, and the
two ways a setting crosses are both visible there — `api.patchShared([...])`
pushes it, `adoptSharedSettings()` takes the Mac's copy.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2] / "MACalendar-iOS" / "MACalendar-iOS"
SETTINGS = (ROOT / "Views" / "SettingsView.swift").read_text()
CLIENT = (ROOT / "API" / "APIClient.swift").read_text()

#: How a screen looks: never pushed, never adopted.
PER_DEVICE_KEYS = ("\"theme\"", "\"display_mode\"", "\"show_holidays\"",
                   "\"show_shabbat_times\"", "\"accent_color\"")
PER_DEVICE_FIELDS = ("theme", "accentColor", "hebrewDisplayMode",
                     "showHolidays", "showShabbatTimes")
#: What the assistant does, plus Gil's two: still shared both ways.
SHARED_FIELDS = ("israelHolidays", "observanceEnabled", "speakReplies",
                 "hideCompletedTasks", "eventLengthMinutes", "chainGapMinutes",
                 "titleEmojiCount")


def _pushes() -> str:
    """Every patchShared(...) argument in the phone's Settings and Tasks."""
    tasks = (ROOT / "Features" / "Tasks" / "TasksView.swift").read_text()
    return "\n".join(re.findall(r"patchShared\((.*?)\)\s*\}", SETTINGS + tasks, re.S))


def _adopt_body() -> str:
    start = SETTINGS.index("private func adoptSharedSettings()")
    end = SETTINGS.index("\n    }\n", start)
    return SETTINGS[start:end]


def test_the_phone_never_pushes_how_its_screen_looks():
    pushed = _pushes()
    assert pushed, "found no patchShared calls — the pattern needs updating"
    for key in PER_DEVICE_KEYS:
        assert key not in pushed, f"the phone pushes {key} to the Mac — it is per device (Q87)"


def test_the_phone_never_adopts_the_macs_look():
    body = _adopt_body()
    for field in PER_DEVICE_FIELDS:
        assert f"shared.{field}" not in body, \
            f"the phone takes the Mac's {field} — it is per device (Q87)"
    struct = CLIENT[CLIENT.index("struct SharedSettings"):]
    struct = struct[:struct.index("\n}\n")]
    for field in PER_DEVICE_FIELDS:
        assert not re.search(rf"\bvar {field}\b", struct), \
            f"SharedSettings still carries {field}"


def test_what_the_assistant_does_is_still_shared_both_ways():
    body = _adopt_body()
    for field in SHARED_FIELDS:
        assert f"shared.{field}" in body, f"the phone stopped adopting {field}"
    pushed = _pushes()
    for key in ("\"observance\"", "\"israel_holidays\"", "\"mute\"",
                "\"show_completed\"", "\"title_emoji\"", "\"events\""):
        assert key in pushed, f"the phone stopped sharing {key}"


def test_the_mic_style_stays_on_each_device():
    assert "micVisual" not in _pushes() and "micVisual" not in _adopt_body()

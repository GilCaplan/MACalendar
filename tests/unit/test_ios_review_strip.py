"""The phone's "N voice commands to review" strip is opt-in.

It sat across the top of every tab once five commands had no thumbs up or
down, and its number only grew (Gil, 2026-10-29: "the thing where thumbs up
or down whether answer was good and it adds up" — "clutters and gets in the
way"). Reviewing stays one tap away in Settings, with its count. CI has no
Swift toolchain, so this reads the source.
"""
from pathlib import Path
import re

IOS = Path(__file__).resolve().parents[2] / "MACalendar-iOS" / "MACalendar-iOS"
CONTENT = (IOS / "Views" / "ContentView.swift").read_text()
SETTINGS = (IOS / "Settings" / "AppSettings.swift").read_text()
SETTINGS_VIEW = (IOS / "Views" / "SettingsView.swift").read_text()


def test_the_strip_needs_the_switch():
    strip = CONTENT.index("voice commands to review")
    guard = CONTENT.rfind("if ", 0, strip)
    assert "settings.reviewReminder && unreviewed >= 5" in CONTENT[guard:strip]


def test_the_switch_defaults_off():
    assert re.search(r'self\.reviewReminder = UserDefaults\.standard\.bool\(forKey: "reviewReminder"\)',
                     SETTINGS), "reviewReminder must default to off (bool(forKey:) of a missing key)"


def test_settings_keeps_the_count_and_the_switch():
    assert "NavigationLink { AssistantReviewView() }" in SETTINGS_VIEW
    assert 'Text("\\(unreviewed)")' in SETTINGS_VIEW
    assert "$settings.reviewReminder" in SETTINGS_VIEW

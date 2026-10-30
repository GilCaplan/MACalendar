"""The phone's thinking panel opens on a TAP, not on every command.

It used to rise as a sheet over the screen each time a command ran, which
got in the way (Gil, 2026-10-27: "the review panel is kind of annoying …
it just keeps showing"). The timeline is still recorded; the "Thinking…"
capsule above the mic opens it, and a Settings switch brings the old
behaviour back. CI has no Swift toolchain, so this reads the source.
"""
import re
from pathlib import Path

IOS = Path(__file__).resolve().parents[2] / "MACalendar-iOS" / "MACalendar-iOS"
VOICE = (IOS / "Views" / "VoiceButton.swift").read_text()
SETTINGS = (IOS / "Settings" / "AppSettings.swift").read_text()
SETTINGS_VIEW = (IOS / "Views" / "SettingsView.swift").read_text()


def test_only_a_tap_or_the_switch_opens_the_panel():
    # Every assignment that opens the sheet is either a Button's action or
    # the one gated helper.
    opens = [m.start() for m in re.finditer(r"showThinking = true", VOICE)]
    assert opens, "the panel can no longer be opened at all"
    for at in opens:
        line = VOICE[VOICE.rfind("\n", 0, at) + 1: VOICE.find("\n", at)]
        assert "Button {" in line or "autoOpenThinking" in line, line.strip()


def test_switch_defaults_off_and_is_in_settings():
    assert re.search(r'self\.autoOpenThinking = UserDefaults\.standard\.bool\(forKey: "autoOpenThinking"\)',
                     SETTINGS), "autoOpenThinking must default to off (bool(forKey:) of a missing key)"
    assert "$settings.autoOpenThinking" in SETTINGS_VIEW


def test_stuck_screen_stays_down_while_the_capsule_shows():
    # With the sheet closed, the capsule is the progress: the mid-screen
    # loader taking over after 4 s would swap one interruption for another.
    loader = (IOS / "EasterEgg" / "EggLoaderViews.swift").read_text()
    assert "!waits.panelOpen && !waits.commandCapsule" in loader
    assert "EggWaits.shared.commandCapsule = now == .thinking" in VOICE

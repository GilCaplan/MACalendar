"""The phone's connection strips are off by default; Settings ▸ Your Mac shows
the same facts, live (Gil, 2026-10-10: "hide the UI that shows mac connection
offline and waiting commands … shown … in the server part of the settings in
a dynamic way"). Read from the Swift source, as the other iOS pins are."""

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "MACalendar-iOS" / "MACalendar-iOS"


def _src(rel: str) -> str:
    return (APP / rel).read_text()


def test_the_strips_default_to_off():
    settings = _src("Settings/AppSettings.swift")
    init = re.search(r"self\.showConnectionBanner = (.+)", settings).group(1)
    assert "?? true" not in init and "? true" not in init, init
    assert "UserDefaults.standard.bool(forKey: \"showConnectionBanner\")" in init


def test_both_strips_answer_to_the_one_switch():
    content = _src("Views/ContentView.swift")
    offline = content.index('accessibilityIdentifier("offline-banner")')
    voice = content.index("Button { showVoiceQueue = true }")
    for at in (offline, voice):
        guard = content.rfind("if ", 0, at)
        assert "settings.showConnectionBanner" in content[guard:at], content[guard:guard + 120]


def test_settings_your_mac_carries_the_live_card():
    settings = _src("Views/SettingsView.swift")
    page = settings[settings.index("private var serverPage"):]
    assert "ConnectionStatusCard(" in page[:page.index("NearbyServers()")]
    card = settings[settings.index("struct ConnectionStatusCard"):]
    for what in ("api.isOnline", "store.pendingCount", "store.pendingVoice",
                 "VoiceQueueView", "showConnectionBanner"):
        assert what in card, f"the card no longer shows {what}"

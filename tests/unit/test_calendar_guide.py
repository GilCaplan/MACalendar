"""The in-app "how to connect" walkthroughs (Gil, 2026-09-24: "add in
connected calendars simple tutorial of how to do, step by step").

One list of steps (`calendar_sync/guide.py`) is drawn by both apps. What can
rot: a step naming a button the app no longer has, a link that isn't https,
and the long guide (DOCUMENTATION/CALENDAR_SYNC.md) drifting from the short one.
"""
from __future__ import annotations

import pathlib

import pytest

from assistant.calendar_sync.guide import guides

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAC_UI = (ROOT / "assistant/calendar_ui/connected_calendars.py").read_text()
IOS_UI = (ROOT / "MACalendar-iOS/MACalendar-iOS/Views/ConnectedCalendarsView.swift").read_text()
LONG = " ".join((ROOT / "DOCUMENTATION/CALENDAR_SYNC.md").read_text().split())


def test_three_ways_in_each_with_steps():
    gs = guides()
    assert [g["key"] for g in gs] == ["ics", "google", "outlook"]
    for g in gs:
        assert g["title"] and g["time"] and g["summary"] and g["done"]
        assert len(g["steps"]) >= 3
        for s in g["steps"]:
            assert s["text"].strip()
            assert not s["link"] or (s["link"].startswith("https://") and s["link_label"])


@pytest.mark.parametrize("button,where", [
    ("Set up…", MAC_UI), ("Choose client JSON…", MAC_UI), ("Connect…", MAC_UI),
    ("Add link", IOS_UI), ("Read-only calendar links", IOS_UI),
])
def test_every_button_a_step_names_exists(button, where):
    text = " ".join(s["text"] for g in guides() for s in g["steps"])
    assert button in text, f"no step names {button!r} any more — drop it from this list"
    assert button in where, f"a step tells you to press {button!r}, which the app no longer has"


@pytest.mark.parametrize("fact", [
    "Desktop app", "Publish app", "calendar.events", "com.macalendar.app",
    "Allow public client flows", "Calendars.ReadWrite",
    "Accounts in any organizational directory and personal Microsoft accounts",
    "Secret address in iCal format",
])
def test_the_short_guide_and_the_long_one_agree(fact):
    short = " ".join(s["text"] for g in guides() for s in g["steps"])
    assert fact in short and fact in LONG


def test_the_route_serves_them():
    from assistant.api.server import create_app
    client = create_app().test_client()
    body = client.get("/calendar_sync/guide").get_json()
    assert [g["key"] for g in body["guides"]] == ["ics", "google", "outlook"]


def test_the_mac_guide_opens_on_the_first_unconnected_and_ticks(monkeypatch):
    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QCheckBox, QPushButton
    import assistant.calendar_ui.connected_calendars as cc

    app = QApplication.instance() or QApplication([])
    seen = {}

    class _Brain:
        def call(self, method, path, body=None, timeout=15):
            return 200, {"enabled": True, "interval_minutes": 15, "running": False,
                         "last_run": None, "subscriptions": [],
                         "providers": {"google": {"connected": True, "configured": True},
                                       "outlook": {"connected": False, "configured": False}}}

    w = cc.ConnectedCalendarsSection(None, None, client=_Brain(), open_url=lambda u: None)
    w.show()
    for _ in range(100):
        if "Syncs every" in w.summary.text():
            break
        QTest.qWait(20)

    def drive():
        dlg = app.activeModalWidget()
        if dlg is None:
            QTimer.singleShot(10, drive)
            return
        seen["tab"] = dlg.tabs.tabText(dlg.tabs.currentIndex())
        box = dlg.findChild(QCheckBox, "outlook_step_1")
        QTest.mouseClick(box, Qt.MouseButton.LeftButton)
        seen["ticked"] = box.isChecked()
        dlg.accept()

    QTimer.singleShot(0, drive)
    QTest.mouseClick(w.findChild(QPushButton, "calsync_guide"), Qt.MouseButton.LeftButton)
    assert seen == {"tab": "Outlook Calendar, two-way", "ticked": True}

"""The Mac's Connected Calendars section, driven by real clicks.

The widget is a client of the brain, so the brain is a fake here: no socket,
no Google, no Microsoft. What is under test is that a click on Connect starts
the right sign-in, opens the right page, and follows the flow to the end.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from assistant.calendar_ui.connected_calendars import ConnectedCalendarsSection  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _provider(**kw):
    base = {"configured": True, "setup_needed": False, "connected": False, "account": "",
            "source_id": None, "two_way": False, "last_synced": "", "last_error": "",
            "pending_flow": None, "setup": {"mac": True, "ios": False}, "setup_hint": ""}
    return {**base, **kw}


class FakeBrain:
    def __init__(self, google=None, outlook=None):
        self.calls = []
        self.flow_state = "pending"
        self.providers = {"google": google or _provider(), "outlook": outlook or _provider()}

    def call(self, method, path, body=None, timeout=15):
        self.calls.append((method, path, body))
        if path == "/calendar_sync/status":
            return 200, {"enabled": True, "interval_minutes": 15, "running": False,
                         "last_run": None, "providers": self.providers, "subscriptions": []}
        if path == "/calendar_sync/google/start":
            return 200, {"id": "f1", "provider": "google", "state": "pending",
                         "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?x=1"}
        if path == "/calendar_sync/outlook/start":
            return 200, {"id": "f2", "provider": "outlook", "state": "pending",
                         "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin"}
        if path.startswith("/calendar_sync/flows/"):
            return 200, {"id": path.rsplit("/", 1)[1], "state": self.flow_state, "account": "gil@example.com"}
        if path == "/calendar_sync/sync":
            return 200, {"finished": True, "results": {"google_pulled": 3, "errors": []}}
        if path.endswith("/disconnect"):
            return 200, {"disconnected": True}
        raise AssertionError(path)


def _wait(cond, ms=3000):
    for _ in range(ms // 20):
        if cond():
            return True
        QTest.qWait(20)
    return cond()


def _make(qapp, brain, **kw):
    opened, toasts = [], []
    w = ConnectedCalendarsSection(None, None, client=brain, open_url=opened.append,
                                  toast=toasts.append, **kw)
    w.show()
    _wait(lambda: "Syncs every" in w.summary.text())
    return w, opened, toasts


def test_setup_needed_is_said_and_connect_is_disabled(qapp):
    brain = FakeBrain(google=_provider(configured=False, setup_needed=True))
    w, _, _ = _make(qapp, brain)
    status = w.findChild(QLabel, "google_status")
    assert "Set-up needed" in status.text()
    assert not w.findChild(QPushButton, "google_connect").isEnabled()


def test_clicking_connect_google_opens_the_sign_in_and_follows_it(qapp, monkeypatch):
    monkeypatch.setattr("assistant.calendar_ui.connected_calendars._POLL_MS", 30)
    brain = FakeBrain()
    w, opened, toasts = _make(qapp, brain)
    QTest.mouseClick(w.findChild(QPushButton, "google_connect"), Qt.MouseButton.LeftButton)
    assert _wait(lambda: opened)
    assert opened[0].startswith("https://accounts.google.com/")
    assert ("POST", "/calendar_sync/google/start", {"platform": "mac"}) in brain.calls
    brain.flow_state = "done"
    assert _wait(lambda: toasts)
    assert "Google Calendar connected as gil@example.com" in toasts[0]


def test_clicking_connect_outlook_shows_the_device_code(qapp):
    brain = FakeBrain()
    w, opened, _ = _make(qapp, brain)
    QTest.mouseClick(w.findChild(QPushButton, "outlook_connect"), Qt.MouseButton.LeftButton)
    assert _wait(lambda: w._code_dialog is not None)
    code = w._code_dialog.findChild(QLabel, "outlook_user_code")
    assert "ABCD-1234" in code.text()
    w._code_dialog.close()


def test_sync_now_asks_the_brain_and_reports(qapp):
    brain = FakeBrain(google=_provider(connected=True, account="gil@example.com", source_id=1))
    w, _, toasts = _make(qapp, brain)
    assert w.findChild(QPushButton, "google_disconnect").isVisible()
    QTest.mouseClick(w.findChild(QPushButton, "calsync_sync_now"), Qt.MouseButton.LeftButton)
    assert _wait(lambda: toasts)
    assert toasts[0] == "Calendars synced (3 pulled, 0 pushed)"
    assert ("POST", "/calendar_sync/sync", {"wait": True}) in brain.calls

"""The server as a clickable app (``assistant.host``, DEVQA Q69).

The QR window is clicked, not called (CLAUDE.md: a UI test that never sends
a mouse event tests nothing), and nothing here reaches the live API: the
window's ``fetch`` is handed a dict, the tray a fake stack.
"""
from __future__ import annotations

import plistlib

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from assistant.host import autostart, supervisor


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _info(n=[0]):
    n[0] += 1
    return {"code": f"ABCDEFG{n[0] % 10}", "pretty": "ABCD-EFGH", "expires_in": 600,
            "urls": ["http://100.64.0.9:8080", "http://192.168.1.5:8080"],
            "name": "Test Mac", "link": f"macalendar://pair?c=X{n[0]}&n=Test"}


def test_the_window_shows_a_qr_the_code_and_where(qapp):
    from assistant.host.pair_dialog import PairDialog
    d = PairDialog(fetch=_info)
    assert d.qr.modules() > 20
    assert "ABCD-EFGH" in d.code.text() and "100.64.0.9:8080" in d.code.text()
    assert d.error.isHidden()


def test_new_code_fetches_a_fresh_one(qapp):
    from assistant.host.pair_dialog import PairDialog
    calls = []
    d = PairDialog(fetch=lambda: calls.append(1) or _info())
    QTest.mouseClick(d.new_btn, Qt.MouseButton.LeftButton)
    assert len(calls) == 2


def test_an_expired_code_is_replaced_by_itself(qapp):
    from assistant.host.pair_dialog import PairDialog
    calls = []
    d = PairDialog(fetch=lambda: calls.append(1) or dict(_info(), expires_in=1))
    d._count_down()
    assert len(calls) == 2


def test_a_server_that_is_not_answering_says_so(qapp):
    from assistant.host.pair_dialog import PairDialog

    def down():
        raise ConnectionRefusedError("refused")
    d = PairDialog(fetch=down)
    assert not d.error.isHidden() and "isn't answering" in d.error.text()
    assert d.qr.modules() == 0


# -- the tray ----------------------------------------------------------------

class _FakeStack:
    port = 8080

    def __init__(self):
        self.pulled = 0

    def start(self, api=True):
        self.api = api
        return []

    def stop(self):
        pass

    def status(self):
        return {}

    def pull_model(self):
        self.pulled += 1
        return True


@pytest.fixture
def tray(qapp, tmp_path, monkeypatch):
    from assistant.host import tray as tray_mod
    monkeypatch.setattr(tray_mod.HostTray, "show_pairing", lambda self: setattr(self, "shown", 1 + getattr(self, "shown", 0)))
    t = tray_mod.HostTray(qapp, stack=_FakeStack(), start=False)
    t.timer.stop()
    t._settings = QSettings(str(tmp_path / "host.ini"), QSettings.Format.IniFormat)
    return t


def test_the_menu_says_running_where_and_how_many(tray):
    tray.apply_status({"api": True, "urls": ["http://100.64.0.9:8080", "http://192.168.1.5:8080"],
                       "devices": 2, "ollama_installed": True, "model_ready": True})
    assert "Running" in tray.status_act.text()
    assert tray.where_act.text() == "Reachable at 100.64.0.9 · 192.168.1.5"
    assert tray.devices_act.text() == "2 devices joined"
    assert tray.pair_act.isEnabled() and not tray.setup_act.isVisible()


def test_nothing_to_pair_with_while_the_server_is_down(tray):
    tray.apply_status({"api": False})
    assert "Not running" in tray.status_act.text() and not tray.pair_act.isEnabled()


def test_the_qr_is_offered_once_when_nothing_has_joined(tray):
    st = {"api": True, "devices": 0, "urls": []}
    tray.apply_status(st)
    tray.apply_status(st)
    assert getattr(tray, "shown", 0) == 1


def test_a_missing_model_is_one_click_away(tray):
    tray.apply_status({"api": True, "devices": 1, "ollama_installed": True, "model_ready": False})
    assert tray.setup_act.isVisible() and "Download" in tray.setup_act.text()
    tray.setup_act.trigger()
    assert tray.stack.pulled == 1


def test_no_ollama_points_at_getting_it(tray):
    tray.apply_status({"api": False, "ollama_installed": False})
    assert "Get Ollama" in tray.setup_act.text()


# -- the stack ---------------------------------------------------------------

def test_nothing_is_started_that_already_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "port_open", lambda port, host="127.0.0.1": True)
    popen = []
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **k: popen.append(a))
    assert supervisor.Stack(log_dir=tmp_path).start() == [] and popen == []


def test_what_it_did_not_start_it_never_stops(tmp_path):
    s = supervisor.Stack(log_dir=tmp_path)
    s.stop()                                   # nothing started: nothing to stop
    assert s.started == {}


def test_the_model_is_recognised_with_or_without_its_tag(monkeypatch):
    monkeypatch.setattr(supervisor, "_get",
                        lambda url, **k: {"models": [{"name": "llama3.1:8b"}, {"name": "qwen:latest"}]})
    assert supervisor.model_ready("llama3.1:8b") is True
    assert supervisor.model_ready("qwen") is True
    assert supervisor.model_ready("mistral:7b") is False


# -- open at login -------------------------------------------------------------

@pytest.mark.parametrize("system", ["Darwin", "Linux", "Windows"])
def test_open_at_login_round_trips_on_each_platform(tmp_path, monkeypatch, system):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    assert not autostart.is_enabled(tmp_path, system)
    path = autostart.enable(tmp_path, system, app=tmp_path / "missing.app")
    assert autostart.is_enabled(tmp_path, system) and str(path).startswith(str(tmp_path))
    text = path.read_bytes()
    if system == "Darwin":
        plist = plistlib.loads(text)
        assert plist["RunAtLoad"] and plist["ProgramArguments"][-2:] == ["-m", "assistant.host"]
    else:
        assert b"-m assistant.host" in text
    autostart.disable(tmp_path, system)
    assert not autostart.is_enabled(tmp_path, system)


def test_on_a_mac_it_opens_the_installed_app(tmp_path):
    app = tmp_path / "MACalendar Server.app"
    app.mkdir()
    plist = plistlib.loads(autostart.enable(tmp_path, "Darwin", app=app).read_bytes())
    assert plist["ProgramArguments"] == ["/usr/bin/open", "-a", str(app)]


class _FakeHelper:
    code = "ABCDEFGH"

    def primaries(self):
        return [{"id": "x", "primary": "MacBook Air"}]

    def stop(self):
        pass


def test_a_helper_says_it_is_lending_and_shows_its_code(tray):
    from assistant.host import role
    tray.role, tray.helper = role.HELPER, _FakeHelper()
    tray.apply_status({"api": False, "ollama": True})
    assert "Lending" in tray.status_act.text()
    assert tray.where_act.text() == "Code for your primary: ABCD-EFGH"
    assert tray.devices_act.text() == "Used by 1 primary"
    assert not tray.pair_act.isVisible() and tray.servers_act.text() == "Helper code & log…"


def test_switching_role_is_remembered_and_stops_the_brain(tray, monkeypatch):
    from assistant.host import role
    stopped = []
    tray.stack.stop_api = lambda: stopped.append(1)
    monkeypatch.setattr(tray, "_start_helper", lambda: setattr(tray, "helper", _FakeHelper()))
    tray.poller.poll = lambda: None
    tray.set_role(role.HELPER, confirm=False)
    assert role.get() == role.HELPER and stopped == [1] and tray.helper is not None
    tray.set_role(role.PRIMARY, confirm=False)
    assert role.get() == role.PRIMARY and tray.helper is None


def test_the_installer_can_set_the_role_without_a_window(monkeypatch, capsys):
    from assistant.host import role, tray as tray_mod
    monkeypatch.setattr("sys.argv", ["host", "--role", "helper"])
    tray_mod.main()
    assert role.get() == role.HELPER
    role.set(role.PRIMARY)

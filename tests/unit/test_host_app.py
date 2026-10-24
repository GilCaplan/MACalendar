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
    yield t
    _retire(t)


def _retire(t) -> None:
    """A tray outlives its test unless told to stop: its first status check
    runs on a thread and lands later, possibly in another test, on widgets the
    garbage collector is tearing down (TASKS 53: CI's random segfaults)."""
    t.timer.stop()
    try:
        t.poller.got.disconnect()
    except TypeError:
        pass
    t.tray.hide()


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


# -- ONE menu-bar icon (Gil, 2026-09-29: "two icons should be consolidated") --

def test_the_server_menu_has_every_app(tray):
    texts = [a.text() for a in tray.menu.actions()]
    for want in ("Open calendar", "Show thinking card", "Pair a phone or tablet…",
                 "Servers & logs…"):
        assert want in texts, want


def test_the_hud_star_steps_aside_while_the_server_menu_is_up(tray):
    from assistant import thinking_hud
    from assistant.heartbeat import beat
    import json, os, time
    from assistant import heartbeat
    path = os.path.join(heartbeat._DIR, "host.json")
    if os.path.exists(path):
        os.remove(path)
    assert thinking_hud.needs_own_icon(), "no server menu: the ✦ stays"
    tray.apply_status({"api": True, "devices": 1, "urls": []})      # the server beats
    assert not thinking_hud.needs_own_icon(), "one icon, not two"
    with open(path, "w") as f:
        json.dump({"ts": time.time() - 60}, f)                          # it went away
    assert thinking_hud.needs_own_icon(), "the card must stay reopenable"


def test_show_card_starts_the_hud_when_it_is_not_running(tray, monkeypatch):
    started = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: started.append(cmd))
    from assistant.host import tray as tray_mod
    monkeypatch.setattr(tray_mod, "HUD_INSTANCE", "macalendar-hud-test-nobody")
    tray.show_card()
    assert started and started[0][-2:] == ["assistant.thinking_hud", "--show"]


# -- a click on the icon restarts the brain (Gil, 2026-10-24) ----------------

def _wait_for(cond, ms=3000):
    waited = 0
    while not cond() and waited < ms:
        QTest.qWait(20)
        waited += 20
    return cond()


def test_restart_restarts_on_the_port_shown(qapp):
    from assistant.host.restart_dialog import RestartDialog
    asked, saved = [], []
    d = RestartDialog(port=8080, restart=lambda p: asked.append(p) or "restarted",
                      save_port=lambda p: saved.append(p) or True)
    QTest.mouseClick(d.restart_btn, Qt.MouseButton.LeftButton)
    assert _wait_for(lambda: "Restarted" in d.status.text())
    assert asked == [8080] and saved == [], "same port: config.yaml is left alone"


def test_a_new_port_is_saved_before_the_restart_and_warns_about_phones(qapp):
    from assistant.host.restart_dialog import RestartDialog
    order = []
    d = RestartDialog(port=8080, restart=lambda p: order.append(("restart", p)) or "",
                      save_port=lambda p: order.append(("save", p)) or True)
    d.port.clear()
    QTest.keyClicks(d.port, "8181")
    assert not d.port_note.isHidden() and "pair again" in d.port_note.text()
    QTest.mouseClick(d.restart_btn, Qt.MouseButton.LeftButton)
    assert _wait_for(lambda: "8181" in d.status.text())
    assert order == [("save", 8181), ("restart", 8181)]


def test_default_puts_8080_back(qapp):
    from assistant.host.restart_dialog import RestartDialog
    d = RestartDialog(port=9000, restart=lambda p: "", save_port=lambda p: True)
    QTest.mouseClick(d.default_btn, Qt.MouseButton.LeftButton)
    assert d.port.value() == 8080


def test_a_failed_restart_says_why_and_puts_the_old_port_back(qapp):
    from assistant.host.restart_dialog import RestartDialog
    saved = []

    def boom(_p):
        raise RuntimeError("The brain runs as the service x.service, which fixes --port 8080.")
    d = RestartDialog(port=8080, restart=boom, save_port=lambda p: saved.append(p) or True)
    d.port.setValue(8181)
    QTest.mouseClick(d.restart_btn, Qt.MouseButton.LeftButton)
    assert _wait_for(lambda: "fixes --port" in d.status.text())
    assert saved == [8181, 8080], "no client may be left pointed at a dead port"
    assert d.port.value() == 8080 and d.restart_btn.isEnabled()


def test_the_qr_is_one_button_away(qapp):
    from assistant.host.restart_dialog import RestartDialog
    paired = []
    d = RestartDialog(port=8080, restart=lambda p: "", save_port=lambda p: True,
                      pair=lambda: paired.append(1))
    d.show()
    QTest.mouseClick(d.pair_btn, Qt.MouseButton.LeftButton)
    assert paired == [1]


def test_a_second_click_on_the_app_offers_the_restart(tray, monkeypatch):
    from assistant.host import tray as tray_mod
    shown = []
    monkeypatch.setattr(tray_mod.HostTray, "show_restart", lambda self: shown.append(1))
    tray_mod._on_message(tray, b"pair")
    assert shown == [1]
    assert "Restart the brain…" in [a.text() for a in tray.menu.actions()]


def test_a_helper_has_no_brain_to_restart(tray, monkeypatch):
    from assistant.host import role as role_mod
    tray.role = role_mod.HELPER
    tray.show_restart()
    assert getattr(tray, "shown", 0) == 1 and tray._restart_win is None


def test_the_systemd_service_is_found_from_the_cgroup(tmp_path):
    d = tmp_path / "42"
    d.mkdir()
    (d / "cgroup").write_text(
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/macalendar-brain.service\n")
    assert supervisor.systemd_unit(42, proc=tmp_path) == "macalendar-brain.service"
    (d / "cgroup").write_text(
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-gnome-x-5.scope\n")
    assert supervisor.systemd_unit(42, proc=tmp_path) is None, "a terminal's, not a service's"
    assert supervisor.systemd_unit(43, proc=tmp_path) is None


def test_a_service_is_restarted_through_systemctl_not_killed(monkeypatch, tmp_path):
    """Restart=always brings a killed API back at once, on the old code."""
    ran, killed = [], []
    monkeypatch.setattr(supervisor, "listener_pids", lambda port: [7])
    monkeypatch.setattr(supervisor, "systemd_unit", lambda pid: "brain.service")
    monkeypatch.setattr(supervisor, "pinned_port", lambda unit: None)
    monkeypatch.setattr(supervisor.os, "kill", lambda *a: killed.append(a))
    monkeypatch.setattr(supervisor.subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or type("R", (), {"returncode": 0})())
    s = supervisor.Stack(port=8080, log_dir=tmp_path)
    assert s.restart_api(8181) == "restarted brain.service"
    assert ran == [["systemctl", "--user", "restart", "brain.service"]] and killed == []
    assert s.port == 8181


def test_a_service_that_pins_its_port_is_not_moved_silently(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(supervisor, "listener_pids", lambda port: [7])
    monkeypatch.setattr(supervisor, "systemd_unit", lambda pid: "brain.service")
    monkeypatch.setattr(supervisor, "pinned_port", lambda unit: 8080)
    monkeypatch.setattr(supervisor.subprocess, "run", lambda cmd, **k: ran.append(cmd))
    s = supervisor.Stack(port=8080, log_dir=tmp_path)
    with pytest.raises(RuntimeError, match="fixes --port 8080"):
        s.restart_api(8181)
    assert ran == [] and s.port == 8080


def test_an_api_from_elsewhere_is_stopped_and_started_again(monkeypatch, tmp_path):
    up = {8080: True}
    killed, popen = [], []
    monkeypatch.setattr(supervisor, "listener_pids", lambda port: [7] if up.get(port) else [])
    monkeypatch.setattr(supervisor, "systemd_unit", lambda pid: None)
    monkeypatch.setattr(supervisor, "ollama_path", lambda: None)
    monkeypatch.setattr(supervisor, "port_open", lambda port, host="127.0.0.1": up.get(port, False))

    def kill(pid, sig):
        killed.append(pid)
        up[8080] = False
    monkeypatch.setattr(supervisor.os, "kill", kill)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda cmd, **k: popen.append(cmd))
    s = supervisor.Stack(port=8080, log_dir=tmp_path)
    assert s.restart_api() == "restarted"
    assert killed == [7] and popen and popen[0][popen[0].index("--port") + 1] == "8080"


def test_the_server_reads_its_port_from_config(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "configured_port", lambda: 9123)
    assert supervisor.Stack(log_dir=tmp_path).port == 9123

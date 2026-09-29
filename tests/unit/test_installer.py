"""The installer (DEVQA Q70): one small file per OS, one stage two for all.

Planned, not run: every test drives ``install/install.py`` in dry-run (or
calls its pure pieces), so nothing is cloned, installed or written outside
tmp_path. The real run is a manual step, recorded in the commit that ships it.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install"


@pytest.fixture(scope="module")
def inst():
    spec = importlib.util.spec_from_file_location("mc_install", INSTALL / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plan(inst, tmp_path, system, *extra):
    args = inst.parse(["--dry-run", "--root", str(tmp_path / "root"), "--no-launch", *extra])
    i = inst.Installer(args, system=system)
    i.main()
    return i.plan


@pytest.mark.parametrize("system", ["Darwin", "Linux", "Windows"])
def test_every_os_gets_the_code_its_packages_and_a_role(inst, tmp_path, system):
    plan = "\n".join(_plan(inst, tmp_path, system, "--no-apps"))
    assert "git clone --depth 1 https://github.com/GilCaplan/MACalendar.git" in plan
    assert "-m venv" in plan and "pip install -e .[nlp" in plan
    assert "spacy download en_core_web_sm" in plan
    assert "-m assistant.host --role primary" in plan
    py = "Scripts/python.exe" if system == "Windows" else "bin/python"
    assert f".venv/{py} -m pip" in plan


def test_everything_goes_in_one_folder(inst, tmp_path):
    plan = _plan(inst, tmp_path, "Linux", "--no-apps", "--no-model")
    root = str((tmp_path / "root").resolve())
    for step in plan:
        paths = re.findall(r"(/\S+)", step)
        for p in paths:
            if p.startswith(("/opt/", "/usr/", "/bin/")) or "github.com" in p or p == "/c":
                continue
            assert p.startswith(root) or p.startswith(sys.executable), (step, p)


def test_a_helper_gets_only_the_server(inst, tmp_path):
    entries = inst.desktop_entries(Path("/r"), Path("/r/.venv/bin/python"), "helper", False)
    assert list(entries) == ["macalendar-server.desktop"]
    shortcuts = inst.windows_shortcuts(Path("C:/r"), Path("C:/r/.venv/Scripts/python.exe"), "helper")
    assert list(shortcuts) == ["MACalendar Server"]


def test_linux_menu_entries_start_the_server_quietly_with_the_calendar(inst, tmp_path):
    repo = tmp_path / "MACalendar"
    e = inst.desktop_entries(repo, repo / ".venv" / "bin" / "python", "primary", False)
    assert set(e) == {"macalendar-server.desktop", "macalendar.desktop", "macalendar-hud.desktop"}
    assert "-m assistant.host --background" in e["macalendar.desktop"]
    assert "-m assistant.main" in e["macalendar.desktop"]
    assert all(t.startswith("[Desktop Entry]\nType=Application\n") for t in e.values())


def test_windows_shortcuts_use_pythonw_so_no_console_opens(inst):
    s = inst.windows_shortcuts(Path("C:/r"), Path("C:/r/.venv/Scripts/python.exe"), "primary")
    assert s["MACalendar Server"][0].endswith("pythonw.exe")
    ps = inst.shortcut_ps("MACalendar", *s["MACalendar"], Path("C:/r"))
    assert "WScript.Shell" in ps and "MACalendar.lnk" in ps


def test_the_mac_apps_are_not_repointed_without_asking(inst, tmp_path, monkeypatch):
    """No-touch (CLAUDE.md): apps installed from another folder stay put."""
    apps = tmp_path / "MACalendar APPs"
    (apps / "MACalendar Server.app").mkdir(parents=True)
    monkeypatch.setattr(inst, "APPS_DIR", apps)
    plan = "\n".join(_plan(inst, tmp_path, "Darwin", "--no-model"))
    assert "build_apps.sh" not in plan
    (tmp_path / "root").mkdir(exist_ok=True)
    (tmp_path / "root" / "install.json").write_text(
        '{"root": "%s"}' % (tmp_path / "root").resolve())
    plan = "\n".join(_plan(inst, tmp_path, "Darwin", "--no-model"))
    assert "build_apps.sh --install MACalendar Server" in plan, "our own install: updated"


def test_jude_is_asked_about_and_left_out_by_default(inst, tmp_path):
    assert "JudeTheJudaicChatBot" not in "\n".join(_plan(inst, tmp_path, "Linux", "--no-apps", "--no-model"))
    plan = "\n".join(_plan(inst, tmp_path, "Linux", "--no-apps", "--no-model", "--jude", "yes"))
    assert "JudeTheJudaicChatBot.git" in plan and "requirements.txt" in plan


def test_stage_two_needs_nothing_but_the_standard_library():
    """It runs before any package is installed."""
    tree = ast.parse((INSTALL / "install.py").read_text())
    mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods - set(sys.stdlib_module_names)


def test_one_script_for_mac_and_linux_detects_which():
    path = INSTALL / "install-macalendar.sh"
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    text = path.read_text()
    assert 'uname -s' in text and "Darwin)" in text and "Linux)" in text
    assert "MINGW*" in text and "install-macalendar-windows.ps1" in text, "Windows is pointed at its own"
    assert "https://github.com/GilCaplan/MACalendar.git" in text
    assert "install/install.py" in text and '${@+"$@"}' in text, "bash 3.2-safe hand-over"
    assert "--installer-file" in text, "the downloaded file is offered for deletion"
    assert "pull" not in text, "an existing copy is install.py's question, not stage one's"
    assert "FETCH_HEAD:install/install.py" in text, "the NEWEST installer asks"
    assert path.stat().st_mode & 0o111, "executable"


def test_the_mac_double_click_file_runs_the_same_script():
    path = INSTALL / "install-macalendar-mac.command"
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    text = path.read_text()
    assert "install-macalendar.sh" in text and "MACALENDAR_INSTALLER_FILE" in text
    assert path.stat().st_mode & 0o111


def test_the_windows_stage_one_hands_over(tmp_path):
    text = (INSTALL / "install-macalendar-windows.ps1").read_text()
    assert "winget install" in text and "install\\install.py" in text
    assert "--installer-file" in text and "pull" not in text
    assert "FETCH_HEAD:install/install.py" in text, "the NEWEST installer asks"
    if shutil.which("pwsh"):
        r = subprocess.run(["pwsh", "-NoProfile", "-Command",
                            f"$null = [ScriptBlock]::Create((Get-Content -Raw '{INSTALL / 'install-macalendar-windows.ps1'}'))"])
        assert r.returncode == 0


def test_the_readme_points_at_files_that_exist():
    readme = (ROOT / "README.md").read_text()
    for url in re.findall(r"https://raw\.githubusercontent\.com/GilCaplan/MACalendar/main/(\S+?)[)`\s|]", readme):
        assert (ROOT / url).exists(), url
    for f in ("install-macalendar.sh", "install-macalendar-mac.command",
              "install-macalendar-windows.ps1"):
        assert f in readme


# -- the guides agree with the installer ---------------------------------------

def test_every_option_the_agent_guide_names_exists(inst):
    """An agent runs exactly what FOR_AI_AGENTS.md says; an option that was
    renamed would fail its install with a usage error."""
    guide = (INSTALL / "FOR_AI_AGENTS.md").read_text()
    named = set(re.findall(r"`(--[a-z-]+)", guide)) | set(re.findall(r" (--[a-z-]+)", guide))
    named -= {"--depth", "--ff-only"}                        # git's, not ours
    real = {a for act in inst.parse([])._get_kwargs() for a in [f"--{act[0].replace('_', '-')}"]}
    assert named and named <= real, named - real


def test_the_install_guides_link_to_files_that_exist():
    for doc in (ROOT / "INSTALL.md", INSTALL / "FOR_AI_AGENTS.md"):
        for target in re.findall(r"\]\(((?!https?:|#)[^)#]+)", doc.read_text()):
            assert (doc.parent / target).resolve().exists(), (doc.name, target)


def test_the_check_is_valid_python_and_a_dry_run_passes_it(inst, tmp_path):
    compile(inst._VERIFY, "<verify>", "exec")
    args = inst.parse(["--dry-run", "--root", str(tmp_path), "--verify"])
    with pytest.raises(SystemExit) as done:
        inst.Installer(args, system="Linux").main()
    assert done.value.code == 0


def test_verify_on_nothing_installed_says_so(inst, tmp_path):
    args = inst.parse(["--root", str(tmp_path), "--verify"])
    with pytest.raises(SystemExit) as done:
        inst.Installer(args).main()
    assert done.value.code == 1


# -- an existing install, the icons, tidying up (DEVQA Q71) ---------------------

def _installer(inst, tmp_path, system, *extra):
    args = inst.parse(["--root", str(tmp_path / "root"), "--no-launch", *extra])
    return inst.Installer(args, system=system)


def _mark(tmp_path, **kw):
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    (root / "install.json").write_text(__import__("json").dumps(dict({"root": str(root.resolve())}, **kw)))


def test_a_fresh_folder_is_a_fresh_install_even_with_the_code_fetched(inst, tmp_path):
    (tmp_path / "root" / "MACalendar" / ".git").mkdir(parents=True)     # stage one cloned it
    assert _installer(inst, tmp_path, "Linux", "--yes").existing() == "fresh"


def test_an_existing_install_is_updated_by_default(inst, tmp_path):
    _mark(tmp_path)
    assert _installer(inst, tmp_path, "Linux", "--yes").existing() == "update"


def test_leave_it_as_it_is_changes_nothing(inst, tmp_path, capsys):
    _mark(tmp_path)
    i = _installer(inst, tmp_path, "Linux", "--existing", "keep", "--dry-run")
    i.main()
    assert i.plan == [] and "nothing was changed" in capsys.readouterr().out


def test_reinstall_deletes_only_a_real_checkout(inst, tmp_path):
    _mark(tmp_path)
    (tmp_path / "root" / "MACalendar").mkdir()
    i = _installer(inst, tmp_path, "Linux", "--existing", "reinstall")
    i.state = "reinstall"
    with pytest.raises(SystemExit, match="does not look like a MACalendar checkout"):
        i.reinstall_code()
    assert (tmp_path / "root" / "MACalendar").exists()


def test_reinstall_keeps_the_settings(inst, tmp_path, monkeypatch):
    # reinstall_code steps out of the folder it deletes (os.chdir); undo that
    # for the tests after this one, which open files by relative path
    monkeypatch.chdir(tmp_path)
    _mark(tmp_path)
    repo = tmp_path / "root" / "MACalendar"
    (repo / "install").mkdir(parents=True)
    (repo / "install" / "install.py").write_text("")
    (repo / "assistant").mkdir()
    (repo / "config.yaml").write_text("mine: true\n")
    i = _installer(inst, tmp_path, "Linux", "--existing", "reinstall")

    def fake_clone(cmd, **kw):
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "fresh").write_text("")
        return 0
    monkeypatch.setattr(i, "run", fake_clone)
    i.reinstall_code()
    assert (repo / "fresh").exists() and (repo / "config.yaml").read_text() == "mine: true\n"
    assert not (repo / "assistant").exists(), "the old program is gone"


def test_an_update_finishes_with_the_newest_installer(inst, tmp_path, monkeypatch):
    repo = tmp_path / "root" / "MACalendar" / "install"
    repo.mkdir(parents=True)
    (repo / "install.py").write_text("# a newer installer\n")
    monkeypatch.delenv("MACALENDAR_INSTALL_REEXEC", raising=False)
    seen = []
    monkeypatch.setattr(inst.os, "execv", lambda exe, argv: seen.append(argv))
    monkeypatch.setattr(inst.sys, "argv", ["install.py", "--existing", "reinstall", "--yes"])
    _installer(inst, tmp_path, "Linux").hand_over_if_newer()
    assert seen and seen[0][1].endswith("install.py")
    assert seen[0][-2:] == ["--existing", "update"] and "reinstall" not in seen[0]
    monkeypatch.setenv("MACALENDAR_INSTALL_REEXEC", "1")
    seen.clear()
    _installer(inst, tmp_path, "Linux").hand_over_if_newer()
    assert not seen, "never twice"


def test_the_mac_icons_go_where_the_person_says(inst, tmp_path):
    i = _installer(inst, tmp_path, "Darwin", "--apps-dir", str(tmp_path / "Mine"), "--yes")
    i.choose_icons()
    assert i.apps_dir == tmp_path / "Mine"


def test_an_update_keeps_the_last_icon_choice(inst, tmp_path):
    _mark(tmp_path, apps_dir=str(tmp_path / "Desk"), desktop_icons=True)
    i = _installer(inst, tmp_path, "Darwin", "--yes")
    i.state = "update"
    i.choose_icons()
    assert i.apps_dir == tmp_path / "Desk"
    j = _installer(inst, tmp_path, "Linux", "--yes")
    j.state = "update"
    j.choose_icons()
    assert j.desktop_icons is True


def test_linux_desktop_icons_are_a_second_copy_of_the_menu_entries(inst, tmp_path, monkeypatch):
    monkeypatch.setattr(inst, "linux_desktop", lambda: tmp_path / "Desktop")
    plan = "\n".join(_plan(inst, tmp_path, "Linux", "--no-model", "--desktop-icons", "yes"))
    assert f"write {tmp_path / 'Desktop' / 'macalendar.desktop'}" in plan
    assert "/.local/share/applications/macalendar.desktop" in plan


def test_windows_desktop_shortcuts_when_asked(inst, tmp_path):
    plan = _plan(inst, tmp_path, "Windows", "--no-model", "--desktop-icons", "yes")
    assert sum("GetFolderPath('Desktop')" in step for step in plan) == 3
    assert sum("Start Menu" in step for step in plan) == 3


def test_the_downloaded_installer_is_offered_for_deletion(inst, tmp_path):
    f = tmp_path / "Downloads" / "install-macalendar-mac.command"
    f.parent.mkdir()
    f.write_text("#!/bin/bash\n")
    _installer(inst, tmp_path, "Darwin", "--yes", "--installer-file", str(f)).tidy_up()
    assert not f.exists(), "--yes takes the default: delete it"


def test_only_the_downloaded_installer_is_ever_deleted(inst, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("x")
    _installer(inst, tmp_path, "Darwin", "--yes", "--installer-file", str(other)).tidy_up()
    inside = tmp_path / "root" / "MACalendar" / "install" / "install-macalendar.sh"
    inside.parent.mkdir(parents=True)
    inside.write_text("x")
    _installer(inst, tmp_path, "Darwin", "--yes", "--installer-file", str(inside)).tidy_up()
    assert other.exists() and inside.exists()


def test_a_running_server_is_asked_to_quit(inst, qapp_or_skip):
    """Through Qt's own local socket, as the tray listens (the name is unique
    here so the real MACalendar Server is never told to quit by a test)."""
    from PyQt6.QtNetwork import QLocalServer
    name = f"macalendar-test-{__import__('os').getpid()}"
    server = QLocalServer()
    QLocalServer.removeServer(name)
    assert server.listen(name)
    got = []
    import threading
    t = threading.Thread(target=lambda: got.append(inst.stop_running_server("/some/root", name)))
    t.start()
    assert server.waitForNewConnection(3000)
    conn = server.nextPendingConnection()
    conn.waitForReadyRead(3000)
    assert bytes(conn.readAll()) == b"quit /some/root"
    t.join(5)
    assert got == [True]
    assert inst.stop_running_server("/some/root", name + "-nobody") is False


def test_a_tray_quits_only_for_its_own_install():
    """Updating ~/MACalendar must not stop a server run from another checkout."""
    from pathlib import Path
    from assistant.host import tray
    calls = []

    class H:
        def quit(self):
            calls.append("quit")

        def show_pairing(self):
            calls.append("pair")
    mine = Path(tray.__file__).resolve().parents[3]
    tray._on_message(H(), f"quit {mine}".encode())
    tray._on_message(H(), b"quit /somewhere/else")
    tray._on_message(H(), b"pair")
    assert calls == ["quit", "pair"]


@pytest.fixture
def qapp_or_skip():
    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])



def test_an_update_moves_a_shallow_clone_to_the_newest_commit(tmp_path):
    """`git pull` cannot fast-forward a depth-1 clone across a gap — the
    first real update run failed exactly so. Fetch + reset does, and keeps
    config.yaml."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mc_install2", INSTALL / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    git = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd, check=True,
                                              capture_output=True, text=True).stdout
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    git("config", "user.email", "t@t", cwd=origin)
    git("config", "user.name", "t", cwd=origin)
    for i in range(3):
        (origin / "f.txt").write_text(f"v{i}\n")
        git("add", "f.txt", cwd=origin)
        git("commit", "-q", "-m", f"v{i}", cwd=origin)
        if i == 0:
            root = tmp_path / "root"
            git("clone", "-q", "--depth", "1", f"file://{origin}", str(root / "MACalendar"))
            (root / "MACalendar" / "config.yaml").write_text("mine\n")
    args = mod.parse(["--root", str(root), "--yes"])
    i = mod.Installer(args, system="Linux")
    i.update_code()
    assert (root / "MACalendar" / "f.txt").read_text() == "v2\n"
    assert (root / "MACalendar" / "config.yaml").read_text() == "mine\n"


def test_an_update_that_did_not_happen_does_not_hand_over(inst, tmp_path, monkeypatch):
    """The old copy's installer must never take over."""
    repo = tmp_path / "root" / "MACalendar"
    (repo / "install").mkdir(parents=True)
    (repo / "install" / "install.py").write_text("# an OLD installer\n")
    (repo / ".git").mkdir()
    i = _installer(inst, tmp_path, "Linux", "--yes")
    i.state = "update"
    monkeypatch.setattr(i, "update_code", lambda: None)      # the fetch failed
    handed = []
    monkeypatch.setattr(i, "hand_over_if_newer", lambda: handed.append(1))
    i.code()
    assert handed == []



def test_a_file_inside_any_git_checkout_is_never_deleted(inst, tmp_path):
    """Running the repository's own install-macalendar.sh passes ITS path as
    the installer file; --yes must not delete source (found in a real run)."""
    src = tmp_path / "somerepo" / "install" / "install-macalendar.sh"
    src.parent.mkdir(parents=True)
    (tmp_path / "somerepo" / ".git").mkdir()
    src.write_text("x")
    _installer(inst, tmp_path, "Darwin", "--yes", "--installer-file", str(src)).tidy_up()
    assert src.exists()


def test_a_hand_over_passes_only_options_the_other_version_knows(inst):
    old = 'p.add_argument("--root")\np.add_argument("--yes")\np.add_argument("--no-apps")'
    argv = ["--root", "/r", "--installer-file", "/d/x.sh", "--existing", "reinstall",
            "--yes", "--no-apps", "--desktop-icons", "yes"]
    assert inst._args_it_knows(argv, old) == ["--root", "/r", "--yes", "--no-apps"]


def test_the_end_of_input_is_the_default_not_a_crash(inst, monkeypatch):
    """A closed terminal, or answers piped in that run out (found driving the
    installer through `script`): every question falls back to its default."""
    def eof(_prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert inst._input("? ") == ""
    src = (INSTALL / "install.py").read_text()
    # a prompt is a call with a string: none may use input() directly
    assert not re.findall(r"(?<![\w.])input\(\s*f?[\"']", src), "every prompt goes through _input"

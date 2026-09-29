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
    apps.mkdir()
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


@pytest.mark.parametrize("script", ["install-macalendar-mac.command", "install-macalendar-linux.sh"])
def test_the_shell_stage_ones_parse_and_hand_over(script):
    path = INSTALL / script
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    text = path.read_text()
    assert "https://github.com/GilCaplan/MACalendar.git" in text
    assert "install/install.py" in text and '${@+"$@"}' in text, "bash 3.2-safe hand-over"
    assert path.stat().st_mode & 0o111, "executable"


def test_the_windows_stage_one_hands_over(tmp_path):
    text = (INSTALL / "install-macalendar-windows.ps1").read_text()
    assert "winget install" in text and "install\\install.py" in text
    if shutil.which("pwsh"):
        r = subprocess.run(["pwsh", "-NoProfile", "-Command",
                            f"$null = [ScriptBlock]::Create((Get-Content -Raw '{INSTALL / 'install-macalendar-windows.ps1'}'))"])
        assert r.returncode == 0


def test_the_readme_points_at_files_that_exist():
    readme = (ROOT / "README.md").read_text()
    for url in re.findall(r"https://raw\.githubusercontent\.com/GilCaplan/MACalendar/main/(\S+?)[)`\s|]", readme):
        assert (ROOT / url).exists(), url
    for f in ("install-macalendar-mac.command", "install-macalendar-linux.sh",
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

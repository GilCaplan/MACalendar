#!/usr/bin/env python3
"""MACalendar installer, stage two — the same on macOS, Linux and Windows.

Stage one (``install-macalendar.sh`` — macOS and Linux, it detects which —
its double-clickable Mac wrapper ``install-macalendar-mac.command``, or
``install-macalendar-windows.ps1``) installs what this needs to run — git,
Python 3.11+ and Ollama — fetches the code if it is not there, and runs this.
Everything else happens here, with the standard library only (nothing is
installed yet when it starts):

    0. an existing install?  update it, delete and reinstall it, or leave it
    1. the code         ROOT/MACalendar (a git checkout)
    2. its packages     ROOT/MACalendar/.venv
    3. the settings     config.yaml from config.example.yaml, once
    4. the role         primary (the brain) or a model helper (DEVQA Q70)
    5. Jude (optional)  ROOT/JudeTheJudaicChatBot, its packages, its index
    6. the model        ollama pull, for what config.yaml names
    7. the apps         where YOU choose: macOS /Applications/MACalendar APPs,
                        the Desktop or any folder; Linux the applications menu
                        and Windows the Start menu, each optionally also on the
                        Desktop
    8. open at login    optional
    9. check it         five checks, ✓ or ✗ (``--verify`` runs only this)
   10. start it         MACalendar Server, which offers the pairing QR
   11. tidy up          offer to delete the installer file you downloaded

Everything lives in ONE folder, ROOT (``~/MACalendar`` unless you say
otherwise). Run it again to update: every step is safe to repeat.

    python3 install.py --help      (every option; FOR_AI_AGENTS.md explains them)

DEVQA Q70/Q71. Personal data is never here: it lives in ~/.assistant_tools,
and nothing here — not even "delete and reinstall" — touches it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/GilCaplan/MACalendar.git"
JUDE_URL = "https://github.com/GilCaplan/JudeTheJudaicChatBot.git"
JUDE_INDEX = "RockyCo/jude-judaic-data"          # 2.2 GB, on Hugging Face
MIN_PY = (3, 11)
APPS_DIR = Path("/Applications/MACalendar APPs")
INSTANCE = "macalendar-server-host"               # assistant/host/tray.py
#: This file as it was when it started — a pull that changes it hands over to
#: the new one, so an update always finishes with the newest installer.
_MY_SOURCE = Path(__file__).read_bytes()


# -- small helpers -------------------------------------------------------------

class Installer:
    def __init__(self, args, system: str | None = None):
        self.a = args
        self.system = system or platform.system()
        self.root = Path(args.root).expanduser().resolve()
        self.repo = self.root / "MACalendar"
        self.jude = self.root / "JudeTheJudaicChatBot"
        self.plan: list[str] = []            # what ran (or would run), in order
        self.state = "fresh"                 # fresh | update | reinstall | keep
        self.apps_dir = APPS_DIR             # macOS: where the apps go
        self.desktop_icons = False           # Linux / Windows: also on the Desktop

    # paths inside the venv differ on Windows
    def venv_python(self, checkout: Path | None = None) -> Path:
        base = (checkout or self.repo) / ".venv"
        return base / ("Scripts/python.exe" if self.system == "Windows" else "bin/python")

    def say(self, text: str) -> None:
        print(f"\n▸ {text}", flush=True)

    def run(self, cmd: list, cwd: Path | None = None, check: bool = True,
            env: dict | None = None) -> int:
        shown = " ".join(str(c) for c in cmd)
        self.plan.append(shown)
        if self.a.dry_run:
            print(f"   (dry run) {shown}")
            return 0
        print(f"   $ {shown}", flush=True)
        r = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                           env=dict(os.environ, **(env or {})))
        if check and r.returncode != 0:
            raise SystemExit(f"\n✗ That step failed (exit {r.returncode}): {shown}\n"
                             "  Fix what it says above and run the installer again — "
                             "every step is safe to repeat.")
        return r.returncode

    def ask(self, question: str, default: bool) -> bool:
        if self.a.yes or self.a.dry_run or not sys.stdin.isatty():
            return default
        hint = "[Y/n]" if default else "[y/N]"
        got = input(f"\n? {question} {hint} ").strip().lower()
        return default if not got else got.startswith("y")

    def choose_role(self) -> str:
        if self.a.role:
            return self.a.role
        if self.a.yes or self.a.dry_run or not sys.stdin.isatty():
            return "primary"
        print("\n? What is this computer for?\n"
              "   1. The primary — the brain. Your calendar lives here and your phone\n"
              "      connects to it. (Choose this for your first computer.)\n"
              "   2. A model helper — it only lends its model to a primary elsewhere.")
        return "helper" if input("  1 or 2 [1]: ").strip() == "2" else "primary"

    # -- the steps ---------------------------------------------------------------

    def check_python(self) -> None:
        if sys.version_info < MIN_PY:
            raise SystemExit(f"✗ Python {MIN_PY[0]}.{MIN_PY[1]}+ is needed; this is "
                             f"{platform.python_version()}. The stage-one installer "
                             "for your system installs it.")

    # -- 0. an existing install ---------------------------------------------------

    def marker(self) -> dict:
        try:
            data = json.loads((self.root / "install.json").read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def existing(self) -> str:
        """Is MACalendar already installed here? Ask what to do with it.

        Installed = a finished install's marker, or a checkout with its
        packages (an interrupted install). A bare checkout is what stage one
        just fetched: that is a fresh install, not an existing one."""
        found = self.marker() or (self.venv_python().exists() and {"root": str(self.root)})
        if not found:
            return "fresh"
        if self.a.existing:
            return self.a.existing
        when = found.get("installed_at", "")
        where = found.get("apps_dir", "")
        running = _port_open(8080)
        print(f"\n  MACalendar is already installed in {self.root}"
              + (f" (installed {when})" if when else "")
              + (f";\n  its apps are in {where}" if where else "")
              + (".\n  It is running now — it will be stopped and started again." if running else "."))
        if self.a.yes or self.a.dry_run or not sys.stdin.isatty():
            return "update"
        print("\n? What would you like to do?\n"
              "   1. Update it — keep your settings, get the newest version (recommended)\n"
              "   2. Delete and reinstall it — a fresh copy of the program; your settings\n"
              "      and your own data (~/.assistant_tools) are kept\n"
              "   3. Leave it as it is — change nothing")
        got = input("  1, 2 or 3 [1]: ").strip()
        return {"2": "reinstall", "3": "keep"}.get(got, "update")

    # -- 1. the code ---------------------------------------------------------------

    def code(self) -> None:
        self.say(f"The code → {self.repo}")
        self.root.mkdir(parents=True, exist_ok=True) if not self.a.dry_run else None
        if self.state in ("update", "reinstall"):
            if not self.a.dry_run and stop_running_server():
                print("   Stopped the running MACalendar Server (it starts again at the end).")
        if self.state == "reinstall":
            self.reinstall_code()
        elif (self.repo / ".git").is_dir():
            self.run(["git", "-C", self.repo, "pull", "--ff-only"], check=False)
        else:
            self.run(["git", "clone", "--depth", "1", self.a.repo_url or REPO_URL, self.repo])
        self.hand_over_if_newer()

    def reinstall_code(self) -> None:
        """Delete the program and fetch it fresh. Only this install's own
        checkout goes — never ~/.assistant_tools, never Jude's library — and
        config.yaml is carried across."""
        if not ((self.repo / "install" / "install.py").is_file() and (self.repo / "assistant").is_dir()):
            raise SystemExit(f"✗ {self.repo} does not look like a MACalendar checkout; "
                             "not deleting it. Remove it yourself or pick another --root.")
        keep = self.root / "config.yaml.keep"
        cfg = self.repo / "config.yaml"
        self.plan.append(f"keep {cfg} → {keep}; delete {self.repo}; clone fresh")
        if self.a.dry_run:
            print(f"   (dry run) keep config.yaml, delete {self.repo}, clone it fresh")
            return
        if cfg.exists():
            shutil.copyfile(cfg, keep)
        os.chdir(self.root)
        shutil.rmtree(self.repo, onerror=_force_remove)
        print(f"   Deleted {self.repo}")
        self.run(["git", "clone", "--depth", "1", self.a.repo_url or REPO_URL, self.repo])
        if keep.exists():
            shutil.copyfile(keep, cfg)
            keep.unlink()
            print("   Your settings (config.yaml) are back in place.")

    def hand_over_if_newer(self) -> None:
        """The pull may have brought a newer installer: finish with IT."""
        new = self.repo / "install" / "install.py"
        if self.a.dry_run or os.environ.get("MACALENDAR_INSTALL_REEXEC") or not new.is_file():
            return
        if new.read_bytes() == _MY_SOURCE:
            return
        print("   The installer itself was updated — continuing with the new one.")
        argv = [a for a in sys.argv[1:]]
        if "--existing" in argv:
            i = argv.index("--existing")
            del argv[i:i + 2]
        os.environ["MACALENDAR_INSTALL_REEXEC"] = "1"
        os.execv(sys.executable, [sys.executable, str(new), *argv, "--existing", "update"])

    def packages(self) -> None:
        self.say("Its packages (a few minutes the first time)")
        py = self.venv_python()
        if not py.exists():
            self.run([sys.executable, "-m", "venv", self.repo / ".venv"])
        self.run([py, "-m", "pip", "install", "--upgrade", "pip"])
        extras = "nlp"
        if self.system == "Darwin" and platform.machine() == "arm64":
            extras += ",mlx"                  # Whisper on the Apple GPU
        self.run([py, "-m", "pip", "install", "-e", f".[{extras}]"], cwd=self.repo)
        self.run([py, "-m", "spacy", "download", "en_core_web_sm"], cwd=self.repo)

    def settings(self) -> None:
        cfg, example = self.repo / "config.yaml", self.repo / "config.example.yaml"
        self.say("Settings")
        if cfg.exists():
            print("   config.yaml already exists — kept as it is.")
            return
        self.plan.append(f"copy {example.name} → {cfg.name}")
        if not self.a.dry_run:
            shutil.copyfile(example, cfg)

    def role(self, role: str) -> None:
        self.say(f"This computer is: {'the primary (the brain)' if role == 'primary' else 'a model helper'}")
        self.run([self.venv_python(), "-m", "assistant.host", "--role", role], cwd=self.repo)

    def jude_step(self) -> None:
        self.say("Jude — the Judaic study assistant")
        if (self.jude / ".git").is_dir():
            self.run(["git", "-C", self.jude, "pull", "--ff-only"], check=False)
        else:
            self.run(["git", "clone", "--depth", "1", JUDE_URL, self.jude])
        jpy = self.venv_python(self.jude)
        if not jpy.exists():
            self.run([sys.executable, "-m", "venv", self.jude / ".venv"])
        self.run([jpy, "-m", "pip", "install", "-r", "requirements.txt"], cwd=self.jude)
        if not (self.jude / "chroma_db").is_dir() and self.ask(
                "Download Jude's library index now? It is 2.2 GB (Jude can't answer "
                "without it; you can do it later).", True):
            self.run([jpy, "-m", "pip", "install", "huggingface_hub"], cwd=self.jude)
            self.run([jpy, "-c", "from huggingface_hub import snapshot_download; "
                      f"snapshot_download(repo_id='{JUDE_INDEX}', repo_type='dataset', "
                      "local_dir='.')"], cwd=self.jude)
        # Switch it on, pointed at the checkout beside this one.
        self.run([self.venv_python(), "-c",
                  "import yaml,pathlib; p=pathlib.Path('config.yaml'); "
                  "d=yaml.safe_load(p.read_text()) or {}; "
                  "j=d.setdefault('jude',{}); j['enabled']=True; "
                  "j['path']='../JudeTheJudaicChatBot'; "
                  "p.write_text(yaml.safe_dump(d, sort_keys=False))"], cwd=self.repo)

    def models(self) -> None:
        self.say("The assistant's model (several GB the first time)")
        ollama = shutil.which("ollama") or next(
            (p for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama",
                         os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"))
             if os.path.isfile(p)), None)
        if not ollama and not self.a.dry_run:
            print("   Ollama isn't installed, so the model can't be downloaded yet. "
                  "MACalendar Server will offer it once Ollama is there.")
            return
        ollama = ollama or "ollama"
        # A server must be up for `pull`; start one if nothing answers.
        if not self.a.dry_run and not _port_open(11434):
            subprocess.Popen([ollama, "serve"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            _wait_port(11434, 20)
        for name in self.model_names():
            self.run([ollama, "pull", name])

    def model_names(self) -> list[str]:
        """What config.yaml names (the engine's model, its verifier, and the
        label embedder) — read through the venv, which has the YAML parser."""
        if self.a.dry_run and not self.venv_python().exists():
            return ["<ollama.model from config.yaml>"]
        out = subprocess.run(
            [str(self.venv_python()), "-c",
             "from assistant.config import load_config; c=load_config().ollama; "
             "from assistant.engine.label import embed; "
             "print('\\n'.join(dict.fromkeys(m for m in (c.model, getattr(c,'verify_model',''), "
             "embed.MODEL) if m)))"],
            cwd=str(self.repo), capture_output=True, text=True)
        return [l for l in out.stdout.split() if l] or ["llama3.1:8b"]

    def choose_icons(self) -> None:
        """Where the app icons go — the person's choice (DEVQA Q71). An update
        keeps the last answer unless told otherwise."""
        before = self.marker()
        quiet = self.a.yes or self.a.dry_run or not sys.stdin.isatty()
        if self.system == "Darwin":
            if self.a.apps_dir:
                self.apps_dir = Path(self.a.apps_dir).expanduser()
                return
            if before.get("apps_dir") and self.state != "fresh":
                self.apps_dir = Path(before["apps_dir"])
                return
            if quiet:
                return
            print("\n? Where should the app icons go?\n"
                  f"   1. Applications ▸ MACalendar APPs (recommended)\n"
                  "   2. Your Desktop\n"
                  "   3. Another folder")
            got = input("  1, 2 or 3 [1]: ").strip()
            if got == "2":
                self.apps_dir = Path.home() / "Desktop"
            elif got == "3":
                typed = input("  Folder (it is created if missing): ").strip()
                if typed:
                    self.apps_dir = Path(typed).expanduser()
            return
        if self.a.desktop_icons:
            self.desktop_icons = self.a.desktop_icons == "yes"
        elif "desktop_icons" in before and self.state != "fresh":
            self.desktop_icons = bool(before["desktop_icons"])
        else:
            where = "the Start menu" if self.system == "Windows" else "the applications menu"
            self.desktop_icons = self.ask(f"The apps go in {where}. Also put icons on your Desktop?", False)

    def apps(self, role: str, with_jude: bool) -> None:
        self.say("The apps")
        names = ["MACalendar Server"] if role == "helper" else \
            ["MACalendar Server", "MACalendar", "MACalendar HUD"] + (["Jude"] if with_jude else [])
        if self.system == "Darwin":
            if not self.ours_or_ok():
                print("   Left the existing apps alone.")
                return
            print(f"   into {self.apps_dir}")
            for name in names:
                self.run(["bash", self.repo / "scripts" / "build_apps.sh", "--install", name],
                         env={"MACALENDAR_APPS_DIR": str(self.apps_dir)})
            # so the Server's "Open calendar" and "Open at login" find them
            self.run([self.venv_python(), "-c",
                      f"from assistant.host import role; role.remember('apps_dir', {str(self.apps_dir)!r})"],
                     cwd=self.repo)
            return
        py = self.venv_python()
        entries = desktop_entries(self.repo, py, role, with_jude)
        if self.system == "Windows":
            folders = [START_MENU] + ([DESKTOP] if self.desktop_icons else [])
            for folder in folders:
                for name, (target, args) in windows_shortcuts(self.repo, py, role).items():
                    self.run(["powershell", "-NoProfile", "-Command",
                              shortcut_ps(name, target, args, self.repo, folder)])
            return
        folders = [Path.home() / ".local" / "share" / "applications"]
        if self.desktop_icons:
            folders.append(linux_desktop())
        for folder in folders:
            for fname, text in entries.items():
                self.plan.append(f"write {folder / fname}")
                if self.a.dry_run:
                    print(f"   (dry run) write {folder / fname}")
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                (folder / fname).write_text(text)
                if folder != folders[0]:
                    # a Desktop launcher must be executable, and GNOME asks
                    # it to be marked trusted before it will run it
                    os.chmod(folder / fname, 0o755)
                    subprocess.run(["gio", "set", str(folder / fname),
                                    "metadata::trusted", "true"], capture_output=True)

    def ours_or_ok(self) -> bool:
        """The Mac apps are NO TOUCH (CLAUDE.md): if they are already installed
        from a DIFFERENT folder, replacing them repoints them — ask first."""
        if not (self.apps_dir / "MACalendar Server.app").exists():
            return True
        if self.marker().get("root") == str(self.root):
            return True
        return self.ask(f"MACalendar's apps are already in {self.apps_dir}, installed from "
                        "another folder. Replace them so they run from this one?", False)

    def autostart(self) -> None:
        if self.a.no_autostart or not self.ask(
                "Start MACalendar Server when you log in?", True):
            return
        self.run([self.venv_python(), "-c",
                  "from assistant.host import autostart; print(autostart.enable())"],
                 cwd=self.repo)

    def launch(self) -> None:
        if self.a.no_launch:
            return
        self.say("Starting MACalendar Server (it sits in the menu bar / system tray)")
        app = APPS_DIR / "MACalendar Server.app"
        if self.system == "Darwin" and app.exists() and not self.a.no_apps:
            self.run(["open", "-a", app], check=False)
        elif not self.a.dry_run:
            flags = {"creationflags": 0x00000008} if self.system == "Windows" else \
                {"start_new_session": True}
            subprocess.Popen([str(self.venv_python()), "-m", "assistant.host"],
                             cwd=str(self.repo), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **flags)

    def verify(self) -> bool:
        """Does it work? One line per check, ✓ or ✗ with what to do. The
        installer ends with this, and ``--verify`` runs only this — so a
        person, or an AI agent driving the install, can tell done from broken."""
        self.say("Checking that it works")
        if self.a.dry_run:
            print("   (dry run) the checks below would run against the installed copy")
            return True
        py = self.venv_python()
        if not py.exists():
            print(f"   ✗ no installed copy at {self.repo} — run the installer first")
            return False
        r = subprocess.run([str(py), "-c", _VERIFY], cwd=str(self.repo),
                           capture_output=True, text=True,
                           env=dict(os.environ, MACALENDAR_NO_WARMUP="1",
                                    MACALENDAR_NO_DISCOVERY="1"))
        try:
            checks = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print("   ✗ the checks could not run:\n" + (r.stderr or r.stdout)[-2000:])
            return False
        for name, good, detail in checks:
            print(f"   {'✓' if good else '✗'} {name}" + (f" — {detail}" if detail else ""))
        good = all(c[1] for c in checks)
        print("   All good." if good else
              "   Something above needs fixing; run the installer again after, or "
              "`install.py --verify` to re-check.")
        return good

    def remember(self) -> None:
        if self.a.dry_run:
            return
        import datetime
        (self.root / "install.json").write_text(json.dumps({
            "root": str(self.root), "system": self.system,
            "installed_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "apps_dir": str(self.apps_dir) if self.system == "Darwin" else "",
            "desktop_icons": self.desktop_icons}, indent=2))

    def tidy_up(self) -> None:
        """Offer to delete the installer file the person downloaded — it is
        not needed again (updating runs the copy inside the install)."""
        f = self.a.installer_file
        if not f:
            return
        p = Path(f)
        if not p.is_file() or not p.name.startswith("install-macalendar"):
            return
        if self.root in p.resolve().parents:
            return                        # the checkout's own copy stays
        updater = self.repo / "install" / "install.py"
        self.say("Tidying up")
        if self.ask(f"Delete the installer you downloaded ({p})? You won't need it — "
                    f"to update later, run: python3 \"{updater}\"", True):
            self.plan.append(f"delete {p}")
            if not self.a.dry_run:
                p.unlink()
            print(f"   Deleted {p}.")
        else:
            print(f"   Kept {p}. You can delete it any time — it isn't needed again.")

    # -- the whole thing --------------------------------------------------------

    def main(self) -> None:
        self.check_python()
        if self.a.verify:
            raise SystemExit(0 if self.verify() else 1)
        print(f"MACalendar installer — {self.system}, into {self.root}")
        self.state = self.existing()
        if self.state == "keep":
            print("\n  Left as it is — nothing was changed.")
            self.tidy_up()
            return
        self.code()
        self.packages()
        self.settings()
        role = self.choose_role()
        self.role(role)
        with_jude = False
        if role == "primary":
            if self.a.jude:
                with_jude = self.a.jude == "yes"
            else:
                with_jude = self.ask("Install Jude, the Judaic study assistant? "
                                     "(optional; about 2.5 GB with its library)", False)
            if with_jude:
                self.jude_step()
        if not self.a.no_model:
            self.models()
        if not self.a.no_apps:
            self.choose_icons()
            self.apps(role, with_jude)
        self.autostart()
        self.remember()
        ok = self.verify()
        self.launch()
        if ok:
            self.tidy_up()
        print(summary(self.root, role, self.system, launched=not self.a.no_launch))
        if not ok:
            raise SystemExit(1)


# -- per-platform pieces (pure, so they are tested) ------------------------------

def desktop_entries(repo: Path, py: Path, role: str, with_jude: bool) -> dict[str, str]:
    """Linux applications-menu entries."""
    def entry(name, comment, cmd):
        return ("[Desktop Entry]\nType=Application\n"
                f"Name={name}\nComment={comment}\n"
                f"Exec=sh -c 'cd \"{repo}\" && {cmd}'\nPath={repo}\n"
                "Terminal=false\nCategories=Office;Calendar;\n")
    out = {"macalendar-server.desktop": entry(
        "MACalendar Server", "The assistant's brain, in the system tray",
        f'"{py}" -m assistant.host')}
    if role == "primary":
        out["macalendar.desktop"] = entry(
            "MACalendar", "Your calendar",
            f'("{py}" -m assistant.host --background &) ; exec "{py}" -m assistant.main')
        out["macalendar-hud.desktop"] = entry(
            "MACalendar HUD", "The floating thinking card",
            f'exec "{py}" -m assistant.thinking_hud')
    return out


def windows_shortcuts(repo: Path, py: Path, role: str) -> dict[str, tuple[str, str]]:
    """Start-menu shortcuts: name -> (target, arguments). pythonw: no console."""
    pyw = str(py).replace("python.exe", "pythonw.exe")
    out = {"MACalendar Server": (pyw, "-m assistant.host")}
    if role == "primary":
        out["MACalendar"] = ("cmd.exe", f'/c start "" "{pyw}" -m assistant.host --background '
                                        f'& start "" "{pyw}" -m assistant.main')
        out["MACalendar HUD"] = (pyw, "-m assistant.thinking_hud")
    return out


START_MENU = r"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\MACalendar"
DESKTOP = "$([Environment]::GetFolderPath('Desktop'))"


def linux_desktop() -> Path:
    """The Desktop folder, in the person's own language (xdg-user-dir)."""
    try:
        got = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout.strip():
            return Path(got.stdout.strip())
    except OSError:
        pass
    return Path.home() / "Desktop"


def shortcut_ps(name: str, target: str, args: str, repo: Path, folder: str = START_MENU) -> str:
    esc = lambda s: str(s).replace("'", "''")
    return (f"New-Item -ItemType Directory -Force -Path \"{folder}\" | Out-Null; "
            f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"{folder}\\{esc(name)}.lnk\"); "
            f"$s.TargetPath='{esc(target)}'; $s.Arguments='{esc(args)}'; "
            f"$s.WorkingDirectory='{esc(repo)}'; $s.Save()")


def summary(root: Path, role: str, system: str, launched: bool = True) -> str:
    where = {"Darwin": "the menu bar", "Windows": "the system tray (by the clock)"}.get(
        system, "the system tray")
    lines = ["", "✓ Installed.", f"  Everything is in {root}.",
             f"  MACalendar Server now runs in {where}." if launched else
             f"  Start MACalendar Server; it will sit in {where}."]
    if role == "primary":
        lines += ["  Next: in its menu choose “Pair a phone or tablet…” and point your",
                  "  iPhone's Camera at the code. (The iPhone app itself is installed",
                  "  from Xcode — see “iPhone & iPad App” in the README.)",
                  "  Away from home, install Tailscale on both with the same account."]
    else:
        lines += ["  Next: in its menu choose “Helper code & log…”, then on your primary:",
                  "  MACalendar Server ▸ Servers & logs ▸ Add a helper, and type the code."]
    updater = root / "MACalendar" / "install" / "install.py"
    lines.append(f"  To update later: python3 \"{updater}\" (or run the installer again).")
    return "\n".join(lines)


#: Run by the INSTALLED copy's Python (it has the packages). Prints one JSON
#: line: [[check, ok, detail], …]. Never writes: the brain is built with its
#: warm-up and network announcement off, and only /health is asked.
_VERIFY = r"""
import json, os, socket
res = []
def check(name, fn):
    try:
        good, detail = fn()
    except Exception as e:
        good, detail = False, f"{type(e).__name__}: {e}"
    res.append([name, bool(good), detail])

def qt():
    import PyQt6.QtWidgets
    return True, ""
def nlp():
    import spacy
    spacy.load("en_core_web_sm")
    return True, ""
def brain():
    from assistant.api.server import create_app
    code = create_app().test_client().get("/health").status_code
    return code == 200, "" if code == 200 else f"/health answered {code}"
def role():
    from assistant.host import role as r
    return True, r.get()
def model():
    import urllib.request
    from assistant.config import load_config
    want = load_config().ollama.model
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as f:
            have = {m["name"] for m in json.loads(f.read()).get("models", [])}
    except OSError:
        return False, "Ollama isn't running — MACalendar Server starts it"
    ok = want in have or f"{want}:latest" in have
    return ok, want if ok else f"{want} not downloaded — run: ollama pull {want}"

check("windows (Qt)", qt)
check("language model (spaCy)", nlp)
check("the brain starts", brain)
check("this computer's role", role)
check("the assistant's model", model)
print(json.dumps(res))
"""


def stop_running_server(name: str = INSTANCE) -> bool:
    """Ask a running MACalendar Server to quit (its tray listens on a local
    socket, assistant/host/tray.py). True when one answered. Best effort."""
    try:
        if os.name == "nt":
            with open("\\\\.\\pipe\\" + name, "wb") as f:     # \\.\pipe\<name>
                f.write(b"quit")
        else:
            import socket
            import tempfile
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(2)
                s.connect(os.path.join(tempfile.gettempdir(), name))
                s.sendall(b"quit")
        import time
        time.sleep(1.5)                  # let it stop what it started
        return True
    except OSError:
        return False


def _force_remove(func, path, _exc) -> None:
    """rmtree on Windows: git leaves read-only files."""
    import stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _port_open(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_port(port: int, seconds: float) -> None:
    import time
    end = time.time() + seconds
    while time.time() < end and not _port_open(port):
        time.sleep(0.5)


def parse(argv=None):
    p = argparse.ArgumentParser(description="Install MACalendar.")
    p.add_argument("--root", default=os.environ.get("MACALENDAR_HOME")
                   or str(Path.home() / "MACalendar"),
                   help="the one folder everything goes in (default ~/MACalendar)")
    p.add_argument("--role", choices=("primary", "helper"))
    p.add_argument("--jude", choices=("yes", "no"))
    p.add_argument("--yes", action="store_true", help="take every default, ask nothing")
    p.add_argument("--dry-run", action="store_true", help="print the steps, change nothing")
    p.add_argument("--no-model", action="store_true")
    p.add_argument("--no-apps", action="store_true")
    p.add_argument("--no-autostart", action="store_true")
    p.add_argument("--no-launch", action="store_true")
    p.add_argument("--verify", action="store_true",
                   help="only check that an existing install works (exit 1 if not)")
    p.add_argument("--existing", choices=("update", "reinstall", "keep"),
                   help="when MACalendar is already installed: update it (default), delete "
                        "and reinstall it, or leave it as it is")
    p.add_argument("--apps-dir", help="macOS: the folder the app icons go in "
                                      "(default /Applications/MACalendar APPs)")
    p.add_argument("--desktop-icons", choices=("yes", "no"),
                   help="Linux / Windows: also put icons on the Desktop")
    p.add_argument("--installer-file", help="the downloaded installer, offered for deletion "
                                            "at the end (stage one passes it)")
    p.add_argument("--system", help=argparse.SUPPRESS)       # tests: plan another OS
    p.add_argument("--repo-url", help=argparse.SUPPRESS)     # tests: clone a local copy
    return p.parse_args(argv)


if __name__ == "__main__":
    a = parse()
    Installer(a, system=a.system).main()

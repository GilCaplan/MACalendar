# Installing MACalendar

Three ways, same result. Pick one:

| | Who does the work | Good when |
|---|---|---|
| **[A. One file](#a-one-file-automatic)** | the installer | you want it done — download, run, answer two questions |
| **[B. Ask an AI agent](#b-ask-an-ai-agent)** | Claude Code, Codex, Cursor… | you already use a coding agent and want it to install, check and fix for you |
| **[C. By hand](#c-by-hand)** | you | you want to see and choose every step, or you are developing on it |

Whichever you pick:

- **Everything goes in one folder**, `~/MACalendar` (Windows:
  `%USERPROFILE%\MACalendar`), holding `MACalendar/` (the code) and, if chosen,
  `JudeTheJudaicChatBot/`. Your own data is never there — it lives in
  `~/.assistant_tools`.
- **A few questions, each with a sensible default:**
  - **Already installed?** It checks first, and offers to **update** it (keeps
    your settings), **delete and reinstall** it (a fresh copy of the program;
    your settings and your own data are kept), or **leave it as it is**.
  - **Primary or model helper?** The primary is the brain — your calendar lives
    there and your phone connects to it. A helper only lends its model to a
    primary elsewhere.
  - **Jude**, the Judaic study assistant (about 2.5 GB with its library)?
  - **Where the app icons go** — Mac: Applications ▸ MACalendar APPs, your
    Desktop, or any folder you name. Linux / Windows: the applications menu /
    Start menu, and optionally also your Desktop.
  - **Delete the installer file** you downloaded, once everything works? You
    won't need it again — updating runs the copy inside the install.
- **The iPhone app is separate** — Apple only lets Xcode install it; see the
  README's *iPhone & iPad App*. Once the server runs, the phone joins by
  scanning a QR code: nothing to type.
- **Status:** macOS is tested end to end. Linux and Windows run the same code
  and installer, dry-run-tested; they have not yet been tried on real hardware,
  and spoken replies there still need a voice (TASKS row 78).

---

## A. One file (automatic)

**macOS or Linux — one command, it works out which:**

```bash
curl -fsSL https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar.sh | bash
```

**Windows (PowerShell):** see below. Prefer a file to double-click?

| Your computer | File | Run it |
|---|---|---|
| **macOS** | [`install/install-macalendar-mac.command`](install/install-macalendar-mac.command) | double-click (first time: right-click ▸ Open ▸ Open) |
| **macOS or Linux** | [`install/install-macalendar.sh`](install/install-macalendar.sh) | `bash install-macalendar.sh` |
| **Windows** | [`install/install-macalendar-windows.ps1`](install/install-macalendar-windows.ps1) | right-click ▸ Run with PowerShell |


```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar-windows.ps1 | iex
```

(Running `install-macalendar.sh` on Windows tells you to use the PowerShell
line instead — Windows cannot run it.)

It installs git, Python 3.11+ and Ollama (with Homebrew, apt/dnf/pacman or
winget — it may ask for your password), fetches the code, then
[`install/install.py`](install/install.py) does the rest the same way
everywhere: packages, settings, your role, Jude if wanted, the model, the apps,
open-at-login, and finally a **check that it works**. It ends by starting
**MACalendar Server** in the menu bar / system tray, which offers the QR code
for your phone, and by offering to delete the file you downloaded.

**To update:** `python3 ~/MACalendar/MACalendar/install/install.py` (or run the
installer again) and choose *Update*. `install.py --verify` re-runs only the
check.

## B. Ask an AI agent

Open your coding agent (Claude Code, Codex, Cursor, …) in any folder and paste:

> Install MACalendar on this computer. Follow the instructions in
> https://github.com/GilCaplan/MACalendar/blob/main/install/FOR_AI_AGENTS.md
> exactly — ask me the questions it lists before starting, run the installer
> non-interactively, and finish with its verify step.

[`install/FOR_AI_AGENTS.md`](install/FOR_AI_AGENTS.md) tells the agent what to
ask you, the exact non-interactive commands per OS, the steps only you can do
(passwords, macOS permission prompts), how to check the result, how to fix
what the check reports, and what it must never touch.

## C. By hand

Everything the installer does, as commands you run yourself. (Windows: use
`.venv\Scripts\python` where these say `.venv/bin/python`.)

**1. Prerequisites** — git, Python 3.11+ and [Ollama](https://ollama.com/download):

```bash
# macOS
xcode-select --install                      # git
brew install python@3.12 ollama
# Linux (Debian/Ubuntu)
sudo apt install git python3 python3-venv libportaudio2 libxcb-cursor0 espeak-ng
curl -fsSL https://ollama.com/install.sh | sh
# Windows
winget install Git.Git Python.Python.3.12 Ollama.Ollama
```

**2. The code and its packages:**

```bash
mkdir -p ~/MACalendar && cd ~/MACalendar
git clone https://github.com/GilCaplan/MACalendar.git && cd MACalendar
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[nlp]"      # on Apple Silicon: ".[nlp,mlx]"
.venv/bin/python -m spacy download en_core_web_sm
cp config.example.yaml config.yaml               # then edit to taste
```

**3. The role** — `primary` for your main computer, `helper` for one that only
lends its model:

```bash
.venv/bin/python -m assistant.host --role primary
```

**4. The model** (the name is `ollama.model` in `config.yaml`):

```bash
ollama pull llama3.1:8b
```

**5. The apps:**

- macOS: `bash scripts/build_apps.sh --install` (all four) or
  `--install "MACalendar Server"` for one; they land in
  `/Applications/MACalendar APPs`, or in the folder you set with
  `MACALENDAR_APPS_DIR=/some/folder` (then tell the server where:
  `.venv/bin/python -c "from assistant.host import role; role.remember('apps_dir', '/some/folder')"`). Launch each once and allow the Desktop
  prompt if it appears.
- Linux / Windows: run `.venv/bin/python -m assistant.host` (the server, in the
  system tray) and `.venv/bin/python -m assistant.main` (the calendar); or run
  the installer with `--no-model` to get menu entries / Start-menu shortcuts.

**6. Optional:** Jude — clone
`https://github.com/GilCaplan/JudeTheJudaicChatBot.git` next to `MACalendar/`,
make its own `.venv`, `pip install -r requirements.txt`, and set
`jude.enabled: true` in `config.yaml`. Open at login — the server's menu ▸
Open at login.

**7. Check it:**

```bash
python3 install/install.py --root ~/MACalendar --verify
```

For development (tests, boards): `pip install -e ".[nlp,dev]"` and read
`CLAUDE.md`.

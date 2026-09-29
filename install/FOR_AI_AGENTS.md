# Installing MACalendar — instructions for an AI agent

You are an AI coding agent (Claude Code, Codex, Cursor, …) asked to install
MACalendar on the computer you are running on. Follow these steps in order.
The installer does the work; your job is to choose its options with the
person, run it without prompts, handle what only they can do, and prove the
result with its check. Human-facing overview: [`../INSTALL.md`](../INSTALL.md).

## 0. Rules

- **Ask before you start** (step 1). Do not guess the role: it decides whether
  this computer holds someone's calendar.
- **Never touch `~/.assistant_tools/`.** It is the person's own data
  (calendar, vocabulary, corrections). The installer only records this
  machine's role there, and its final check starts the brain once — which on a
  new computer creates the empty stores, as any first start would. It never
  changes what is already there, and you must not either: no deleting, no
  "cleaning up", no test data.
- **Never replace existing MACalendar apps on a Mac without asking.** If
  `/Applications/MACalendar APPs/` already exists, the installer leaves it
  alone unless told otherwise; tell the person and let them decide.
- **Passwords and permission prompts are the person's.** You cannot type a
  sudo password or click a macOS dialog; when a step needs one, stop and ask
  them to do that step (step 3 lists them).
- **Do not push, commit, or edit the code** to make the install pass. If
  something fails, report it with the output.

## 1. Ask these questions first

1. **Role** — "Is this computer the *primary* (the brain: your calendar lives
   here and your phone connects to it), or a *model helper* (it only lends its
   model to a primary on another computer)?" Default: primary. Most people
   have exactly one primary.
2. **Jude** (primary only) — "Install Jude, the Judaic study assistant? About
   2.5 GB with its library." Default: no.
3. **Folder** — "Install into `~/MACalendar`?" Default: yes. (Anything else:
   pass `--root`.)
4. **Open at login** — "Start MACalendar Server when you log in?" Default: yes.

## 2. Run the installer non-interactively

Detect the OS (`uname` / `$env:OS`) and run ONE of these, filling in the
answers. `--yes` takes every remaining default and asks nothing.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar-mac.command -o /tmp/mc-install   # Linux: install-macalendar-linux.sh
bash /tmp/mc-install --yes --role primary --jude no
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar-windows.ps1 -OutFile $env:TEMP\mc-install.ps1
powershell -ExecutionPolicy Bypass -File $env:TEMP\mc-install.ps1 --yes --role primary --jude no
```

Options (all passed through to `install/install.py`):

| option | meaning |
|---|---|
| `--role primary\|helper` | this computer's role (step 1, question 1) |
| `--jude yes\|no` | install Jude (primary only) |
| `--root DIR` | the one folder everything goes in (default `~/MACalendar`) |
| `--yes` | never prompt; take defaults for anything not given |
| `--no-autostart` | do not start the server at login |
| `--no-model` | skip the model download (several GB) |
| `--no-apps` | skip the apps / menu entries / shortcuts |
| `--no-launch` | do not start MACalendar Server at the end |
| `--dry-run` | print every step, change nothing — use it first if unsure |
| `--verify` | only run the check on an existing install (exit 1 if broken) |

The run takes a few minutes, plus the model download (several GB) the first
time. Use a long timeout and let it finish; progress lines start with `▸`.
If the stage-one file is already downloaded, or the code is already cloned,
you can run stage two directly:
`python3 ~/MACalendar/MACalendar/install/install.py --yes --role primary --jude no`.

## 3. Steps only the person can do

| When | What to tell them |
|---|---|
| macOS, no command-line tools | "A window asks to install Apple's command-line tools — click Install, then tell me when it's done." Then run the installer again. |
| macOS, no Homebrew | "Homebrew needs your password. Please run this in Terminal: `/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"`", then run the installer again. |
| Linux | the package step runs `sudo`; if it cannot prompt, ask them to run the `sudo apt-get install …` line the installer printed. |
| Windows, no winget | "Install *App Installer* from the Microsoft Store." |
| macOS, first launch of each app | "If macOS asks whether MACalendar may access your Desktop or microphone, click Allow." |
| iPhone | the iPhone app is installed from Xcode (README ▸ *iPhone & iPad App*); then the phone joins by scanning the QR in MACalendar Server ▸ Pair a phone or tablet. |

## 4. Check the result

The installer ends with a check and exits non-zero if it fails. Re-run it any
time:

```bash
python3 ~/MACalendar/MACalendar/install/install.py --verify
```

Every line must be ✓:

```
   ✓ windows (Qt)
   ✓ language model (spaCy)
   ✓ the brain starts
   ✓ this computer's role — primary
   ✓ the assistant's model — llama3.1:8b
```

| ✗ line | Fix |
|---|---|
| windows (Qt) | Linux: install the Qt system libraries (`libxcb-cursor0 libxkbcommon-x11-0 libegl1`), re-run the installer |
| language model (spaCy) | `~/MACalendar/MACalendar/.venv/bin/python -m spacy download en_core_web_sm` |
| the brain starts | show the person the error text; re-run the installer (it repairs packages) |
| the assistant's model — Ollama isn't running | start MACalendar Server (it starts Ollama), or `ollama serve` |
| the assistant's model — not downloaded | `ollama pull <the name it printed>` |

Then report to the person: the folder, the role, what was installed, the
check's output, and the next step (pair the phone from the server's menu, or,
for a helper, add it on the primary: Servers & logs ▸ Add a helper).

## 5. Updating and removing

- **Update:** run the same command again; every step is safe to repeat.
- **Remove:** only when asked. Delete the install folder and, on a Mac,
  `/Applications/MACalendar APPs`; turn off Open at login first (server menu).
  Leave `~/.assistant_tools` unless the person explicitly says to delete their
  data too — it cannot be recovered.

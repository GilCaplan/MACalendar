#!/bin/zsh
# Start (or restart) the Jude window on its own.
#
# Called by "Jude.app" through `do shell script`, which is headless — so this is
# a .sh and not a .command (a .command is what Finder opens INTO A TERMINAL).
#
# It deliberately does NOT start the assistant API and does NOT check
# jude.enabled. `assistant.jude.app` talks to whatever API is on
# 127.0.0.1:$MACALENDAR_API_PORT and reports "not available" itself, with the
# sentence from GET /jude/status — exactly as the iOS tab does. Duplicating
# that check here would mean two places to get it wrong, and the window is the
# one that can actually tell the user.
set -u

# EXPLICIT, not inferred from $0: a copy of this script installed anywhere else
# — which is precisely how the launcher app comes to call it — would otherwise
# cd into a directory with no .venv and report a broken venv that is fine.
REPO_DIR="${MACALENDAR_REPO:-/Users/USER/Desktop/Personal_Projects/MACalendar}"
LOG=~/.assistant_tools/jude.log
mkdir -p ~/.assistant_tools

cd "$REPO_DIR" || { echo "$(date '+%F %T')  no repo at $REPO_DIR" >> "$LOG"; exit 1; }

PY=./.venv/bin/python
if [[ ! -x "$PY" ]]; then
  # A bare `python` may be a pyenv shim without PyQt6, and the window then dies
  # with an import error that reads like a broken app rather than a missing venv.
  echo "$(date '+%F %T')  no ./.venv" >> "$LOG"
  osascript -e 'display alert "Jude" message "The project venv is missing.\n\nRun in the repo:\n  python3.11 -m venv .venv\n  ./.venv/bin/pip install -e ." as critical'
  exit 1
fi

# Restart rather than duplicate. CLAUDE.md: "The API reloads itself; nothing
# else does" — so a Jude window left open across an edit is running old code,
# and the fix is to replace it rather than end up with two.
if pgrep -f "assistant.jude.app" > /dev/null; then
  echo "$(date '+%F %T')  restarting a running Jude (picks up code changes)" >> "$LOG"
  pkill -f "assistant.jude.app"
  sleep 1
fi

# NOT `nohup ... &`: this project lives under ~/Desktop and macOS TCC blocks a
# freshly-detached process from touching it unless it has its own Desktop
# grant. `do shell script` gives the applet a TCC identity the user approves
# once; a detached grandchild does not inherit it reliably.
echo "$(date '+%F %T')  starting Jude" >> "$LOG"
"$PY" -m assistant.jude.app >> "$LOG" 2>&1 &
disown 2>/dev/null || true

# Confirm it came up: a window that dies on import would otherwise be a silent
# no-op — you click the icon and nothing ever appears.
sleep 3
if pgrep -f "assistant.jude.app" > /dev/null; then
  echo "$(date '+%F %T')  Jude is up" >> "$LOG"
else
  echo "$(date '+%F %T')  Jude failed to start — see above" >> "$LOG"
  osascript -e 'display alert "Jude" message "Jude did not start. See ~/.assistant_tools/jude.log" as critical'
  exit 1
fi

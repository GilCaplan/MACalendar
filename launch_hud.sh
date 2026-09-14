#!/bin/zsh
# Start (or restart) the thinking HUD on its own.
#
# NOT a .command, deliberately. A .command is what Finder double-clicks INTO A
# TERMINAL WINDOW, and `Launch Calendar.command` carries a whole osascript block
# to minimise the window Finder opens for it. This script is only ever called by
# "MACalendar HUD.app" through `do shell script`, which is headless — so naming
# it .command only created a file that pops a Terminal if anyone clicks it.
#
# `Launch Calendar.command` starts the whole stack — ollama, the API, the HUD
# and the GUI. This starts ONLY the card, for the two cases that come up
# constantly:
#
#   * the HUD was closed (which it remembers) and you want it back without
#     restarting the API and the GUI underneath it;
#   * the HUD is running OLD CODE. CLAUDE.md: "The API reloads itself; nothing
#     else does. The calendar GUI and the thinking HUD do NOT — restart them by
#     hand, and remember that when a change has no effect." So this kills a
#     running one first rather than leaving two cards on screen, one of them
#     stale.
#
# It deliberately does NOT set MACALENDAR_TRACE_BUS or MACALENDAR_LLM_BUS: the
# card must read the REAL stores, or it shows an empty History and none of the
# commands you actually gave.
set -u
# The repo path is EXPLICIT, not inferred from $0. `cd "$(dirname "$0")"` is
# right only while this file sits in the repo; a copy installed anywhere else —
# which is exactly how the launcher app came to call it — lands in a directory
# with no .venv and reports "no ./.venv" for a venv that is perfectly fine.
# REPO_DIR can be overridden for a checkout somewhere else.
REPO_DIR="${MACALENDAR_REPO:-/Users/USER/Desktop/Personal_Projects/MACalendar}"
cd "$REPO_DIR" || { echo "$(date '+%F %T')  no repo at $REPO_DIR" >> ~/.assistant_tools/hud.log; exit 1; }

LOG=~/.assistant_tools/hud.log
mkdir -p ~/.assistant_tools

PY=./.venv/bin/python
if [[ ! -x "$PY" ]]; then
  # A bare `python` may be a pyenv shim without PyQt6, and the HUD then dies
  # with an import error that looks like a broken app rather than a missing venv.
  echo "$(date '+%F %T')  no ./.venv — run: python3.11 -m venv .venv && ./.venv/bin/pip install -e ." >> "$LOG"
  osascript -e 'display alert "MACalendar HUD" message "The project venv is missing.\n\nRun in the repo:\n  python3.11 -m venv .venv\n  ./.venv/bin/pip install -e ." as critical'
  exit 1
fi

# Restart, don't duplicate.
if pgrep -f "assistant.thinking_hud" > /dev/null; then
  echo "$(date '+%F %T')  restarting a running HUD (picks up code changes)" >> "$LOG"
  pkill -f "assistant.thinking_hud"
  sleep 1
fi

# NOT `nohup ... &`. Launch Calendar.command explains why, and it applies here
# with more force: this project lives under ~/Desktop, and macOS TCC blocks a
# freshly-spawned or re-parented process from touching it ("Operation not
# permitted") unless that process has its own Desktop access. `do shell script`
# already gives the applet a TCC identity the user approves once; a detached
# grandchild does not inherit it reliably.
#
# setsid-style detachment is also unnecessary: `do shell script` returns when
# the command returns, so the HUD needs only to outlive this script, which
# a plain background job inside the applet's own session does.
echo "$(date '+%F %T')  starting the HUD" >> "$LOG"
"$PY" -m assistant.thinking_hud >> "$LOG" 2>&1 &
disown 2>/dev/null || true

# Confirm it actually came up: a HUD that dies on import would otherwise be a
# silent no-op — you click the icon and nothing ever appears.
sleep 3
if pgrep -f "assistant.thinking_hud" > /dev/null; then
  echo "$(date '+%F %T')  HUD is up" >> "$LOG"
else
  echo "$(date '+%F %T')  HUD failed to start — see above" >> "$LOG"
  osascript -e 'display alert "MACalendar HUD" message "The HUD did not start. See ~/.assistant_tools/hud.log" as critical'
  exit 1
fi

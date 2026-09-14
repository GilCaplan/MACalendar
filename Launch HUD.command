#!/bin/zsh
# Start (or restart) the thinking HUD on its own.
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
cd "$(dirname "$0")"

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

echo "$(date '+%F %T')  starting the HUD" >> "$LOG"
nohup "$PY" -m assistant.thinking_hud >> "$LOG" 2>&1 &

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

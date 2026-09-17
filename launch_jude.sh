#!/bin/zsh
# Start (or restart) Jude — the Judaic study assistant — on its own.
#
# NOT a .command, for the same reason launch_hud.sh isn't: this is only ever
# called by "Jude.app" through `do shell script`, which is headless, so a
# .command extension would just pop a Terminal if anyone double-clicked it
# directly.
#
# `Launch Calendar.command` already starts Jude as part of the whole stack,
# gated on `jude.enabled`. This script exists for the two cases that come up
# once Jude is a window you actually use, matching the HUD's own reasons:
#
#   * the window was closed and you want it back without restarting the API
#     and the calendar GUI underneath it;
#   * it is running OLD CODE. CLAUDE.md: "The API reloads itself; nothing else
#     does. The calendar GUI and the thinking HUD do NOT — restart them by
#     hand." Jude's window is the same kind of process, so this kills a
#     running one first rather than leaving two windows open, one stale.
#
# It does NOT start `assistant.api`, Jude's own server, or check `jude.enabled`
# — `assistant.jude_app` talks to the ALREADY-RUNNING assistant API on
# 127.0.0.1:$MACALENDAR_API_PORT (default 8080), exactly like the iOS tab
# does, and reports "not available" itself if the Mac has no Jude checkout or
# the flag is off. See DOCUMENTATION/JUDE.md.
set -u
# The repo path is EXPLICIT, not inferred from $0 — same reasoning as
# launch_hud.sh: a copy of this script installed inside the .app bundle would
# otherwise `cd` into a directory with no .venv.
REPO_DIR="${MACALENDAR_REPO:-/Users/USER/Desktop/Personal_Projects/MACalendar}"
cd "$REPO_DIR" || { echo "$(date '+%F %T')  no repo at $REPO_DIR" >> ~/.assistant_tools/jude-launch.log; exit 1; }

LOG=~/.assistant_tools/jude-launch.log
mkdir -p ~/.assistant_tools

PY=./.venv/bin/python
if [[ ! -x "$PY" ]]; then
  echo "$(date '+%F %T')  no ./.venv — run: python3.11 -m venv .venv && ./.venv/bin/pip install -e ." >> "$LOG"
  osascript -e 'display alert "Jude" message "The project venv is missing.\n\nRun in the repo:\n  python3.11 -m venv .venv\n  ./.venv/bin/pip install -e ." as critical'
  exit 1
fi

# Restart, don't duplicate — same reasoning as the HUD: two windows, one of
# them stale, is worse than a one-second gap while this one comes back.
if pgrep -f "assistant.jude_app" > /dev/null; then
  echo "$(date '+%F %T')  restarting a running Jude window (picks up code changes)" >> "$LOG"
  pkill -f "assistant.jude_app"
  sleep 1
fi

# NOT `nohup ... &` — same TCC reasoning as Launch Calendar.command and
# launch_hud.sh: this project lives under ~/Desktop, and a re-parented process
# does not reliably inherit the Desktop-access grant `do shell script` gives
# the applet's own session.
echo "$(date '+%F %T')  starting Jude" >> "$LOG"
"$PY" -m assistant.jude_app >> "$LOG" 2>&1 &
disown 2>/dev/null || true

# Confirm it actually came up — a Jude that dies on import (missing PyQt6,
# say) would otherwise be a silent no-op: click the icon, nothing appears.
sleep 3
if pgrep -f "assistant.jude_app" > /dev/null; then
  echo "$(date '+%F %T')  Jude is up" >> "$LOG"
else
  echo "$(date '+%F %T')  Jude failed to start — see above" >> "$LOG"
  osascript -e 'display alert "Jude" message "Jude did not start. See ~/.assistant_tools/jude-launch.log" as critical'
  exit 1
fi

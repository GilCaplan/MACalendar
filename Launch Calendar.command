#!/bin/bash
# Double-click this file in Finder to launch the Calendar Assistant.
# The Terminal window Finder opens for this gets minimized to the Dock
# immediately rather than staying visible — everything below then keeps
# running normally in that same (now-hidden) window/process.
#
# Deliberately NOT detaching this into a separate background process
# (e.g. via `nohup ... &` or `launchctl submit`): this project lives under
# ~/Desktop, and macOS's TCC privacy controls block freshly-spawned/
# re-parented processes from touching anything there ("Operation not
# permitted") unless the user has separately granted that process Desktop
# access. Staying in the same process that Terminal already launched (and
# already has permission for) sidesteps that entirely.

cd "$(dirname "$0")"

# Launched from the MACalendar app (osacompile's `do shell script`), this runs
# with the bare system PATH — /usr/bin:/bin:/usr/sbin:/sbin — where python3 is
# Apple's 3.9 and ollama does not exist. The venv check below then called a
# healthy venv "broken", found no 3.11, and exited: the app "auto quit"
# (2026-09-28). Terminal's PATH already has Homebrew; the app's does not.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ -z "$MACALENDAR_DETACHED" ]; then
    export MACALENDAR_DETACHED=1
    MY_TTY="$(tty)"
    osascript -e "
        tell application \"Terminal\"
            repeat with w in windows
                if (tty of w) is \"$MY_TTY\" then set miniaturized of w to true
            end repeat
        end tell
    " 2>/dev/null
fi

# Activate virtual environment
VENV_PYTHON=""
if [ -f ".venv/bin/python" ]; then
    # Validate the VENV's interpreter (not whatever python3 is on PATH): it
    # resolves (not a broken symlink), is 3.11+, and has the GUI's Qt.
    if .venv/bin/python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null && \
       .venv/bin/python -c "import PyQt6" 2>/dev/null; then
        source .venv/bin/activate
        VENV_PYTHON=".venv/bin/python"
    fi
elif [ -f "venv/bin/python" ]; then
    source venv/bin/activate
    VENV_PYTHON="venv/bin/python"
fi

# If no valid venv found, offer to create one automatically
if [ -z "$VENV_PYTHON" ]; then
    echo ""
    echo "⚠️  Virtual environment is missing or broken."
    echo "   Setting up dependencies now (this only runs once)..."
    echo ""
    # Find a Python 3.11+ interpreter
    for PY in python3.11 python3.12 python3.13; do
        if command -v $PY &>/dev/null; then
            FOUND_PY=$PY
            break
        fi
    done
    if [ -z "$FOUND_PY" ]; then
        echo "❌ Python 3.11 or later is required but not found."
        echo "   Install it via: brew install python@3.11"
        read -p "Press Enter to exit..."
        exit 1
    fi
    echo "Using $FOUND_PY — creating .venv and installing packages..."
    $FOUND_PY -m venv .venv
    .venv/bin/pip install -e ".[dev]" --quiet
    source .venv/bin/activate
    echo "✅ Setup complete."
    echo ""
fi

# ONE OF EACH ON THIS MAC (Gil, 2026-09-28). The apps in "MACalendar APPs"
# can be clicked in any order and any number of times — the Server app, the
# HUD app and this one all start pieces of the same stack — so every piece
# below starts only when it is not already running, and a second click on
# MACalendar brings the open window forward instead of opening another.
# What this launch did NOT start, it does not stop when the window closes: a
# server started by the Server app outlives the calendar window.
GUI_RUNNING="$(pgrep -f -- '-m assistant\.main( |$)' | head -1)"
if [ -n "$GUI_RUNNING" ]; then
    echo "$(date '+%F %T')  the calendar is already open (PID $GUI_RUNNING) — bringing it forward"
    osascript -e "tell application \"System Events\" to set frontmost of (first process whose unix id is $GUI_RUNNING) to true" 2>/dev/null
    exit 0
fi

# Start Ollama server if it is not already running
if command -v ollama &>/dev/null; then
    if ! lsof -i :11434 -sTCP:LISTEN -t >/dev/null; then
        echo "🦙 Starting Ollama server..."
        ollama serve > /dev/null 2>&1 &
        OLLAMA_PID=$!
        # Give it a few seconds to initialize
        sleep 5
    fi
fi

# Start the API server — the brain — in the background (Tailscale mode).
# If you get a port collision on 8080, change the port here and on your iPhone Settings.
#
# --reload restarts it by itself when anything under assistant/ changes, so
# editing the assistant no longer means quitting and relaunching everything.
# It is the Werkzeug reloader WITHOUT the debugger: --debug would also expose
# a browser shell on 0.0.0.0, which on a tailnet is a shell for every device
# on it (assistant.api refuses that combination outright).
#
# The GUI and the HUD are not reloaded — they are thin now, and restarting a
# window you are looking at is worse than restarting a server you are not.
# Set MACALENDAR_NO_RELOAD=1 to pin the server too.
RELOAD="--reload"
[ "$MACALENDAR_NO_RELOAD" = "1" ] && RELOAD=""
PORT=8080
API_PID=""
if lsof -i :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "📱 API already running on :$PORT — using it"
else
    python -m assistant.api --tailscale --port $PORT $RELOAD &
    API_PID=$!
fi

# Start the thinking HUD — its own always-on-top window, deliberately not part
# of the calendar app: a command given from the phone usually arrives while you
# are working in something else, and the HUD has to be visible there. It reads
# the trace bus, so it keeps working whichever process ran the command.
HUD_PID=""
if pgrep -f "assistant\.thinking_hud" >/dev/null; then
    echo "🪟 Thinking HUD already running — using it"
else
    MACALENDAR_API_PORT=$PORT python -m assistant.thinking_hud &
    HUD_PID=$!
fi

# Jude is NOT started here (Gil, 2026-09-29: clicking MACalendar "also opens
# the jude application … when it should be only the calendar"). Jude has its
# own app (Jude.app, scripts/build_apps.sh); the API still reaches Jude's
# server through the integration when it is used.
JUDE_PID=""

echo "--------------------------------------------------------"
[ -n "$API_PID" ] && echo "📱 iPhone API started (PID $API_PID)"
[ -n "$HUD_PID" ] && echo "🪟 Thinking HUD started (PID $HUD_PID)"
echo "   1. Ensure Tailscale is UP on both Mac and iPhone."
echo "   2. In the iOS app, set Server URL to the Tailscale IP + :$PORT"
echo "   3. (Optional) Open Xcode to deploy: open MACalendar-iOS/MACalendar-iOS.xcodeproj"
if [ ! -z "$OLLAMA_PID" ]; then
echo "   4. Ollama server started in background (PID $OLLAMA_PID)"
fi
echo "--------------------------------------------------------"

# Start the Mac calendar app (foreground — closing this window stops everything)
python -m assistant.main

# When the Mac app exits, shut down what THIS launch started — never a piece
# that was already running when it began
[ -n "$API_PID" ] && kill $API_PID 2>/dev/null
[ -n "$HUD_PID" ] && kill $HUD_PID 2>/dev/null
if [ ! -z "$JUDE_PID" ]; then
    kill $JUDE_PID 2>/dev/null
fi
if [ ! -z "$OLLAMA_PID" ]; then
    kill $OLLAMA_PID 2>/dev/null
fi

#!/bin/bash
# MACalendar installer for macOS — stage one.
#
# Double-click it. (The first time, macOS may say it is from an unidentified
# developer: right-click it ▸ Open ▸ Open.) Or, in Terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar-mac.command | bash
#
# It installs what the installer needs — Apple's command-line tools (git),
# Homebrew, Python 3.12 and Ollama — then fetches MACalendar into ~/MACalendar
# and hands over to install/install.py, which does the rest the same way on
# every system. Safe to run again: it updates what is there.
#
# MACALENDAR_HOME=/some/folder puts everything there instead of ~/MACalendar.
# Any arguments are passed on to install.py (e.g. --role helper, --yes).
set -euo pipefail

ROOT="${MACALENDAR_HOME:-$HOME/MACalendar}"
REPO_URL="https://github.com/GilCaplan/MACalendar.git"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

say() { printf '\n▸ %s\n' "$*"; }

say "MACalendar installer — macOS, into $ROOT"

# 1. git comes with Apple's command-line tools.
if ! xcode-select -p >/dev/null 2>&1; then
  say "Installing Apple's command-line tools (a window opens — click Install)"
  xcode-select --install || true
  echo "When that finishes, run this installer again."
  exit 1
fi

# 2. Homebrew, the package manager the rest comes from.
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew (it asks for your Mac password)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi

# 3. Python 3.11+ and Ollama.
PY=""
for v in 3.13 3.12 3.11; do
  if command -v "python$v" >/dev/null 2>&1; then PY="python$v"; break; fi
done
if [ -z "$PY" ]; then
  say "Installing Python 3.12"
  brew install python@3.12
  PY="python3.12"
fi
if ! command -v ollama >/dev/null 2>&1; then
  say "Installing Ollama (runs the assistant's model on this Mac)"
  brew install ollama
fi

# 4. The code.
mkdir -p "$ROOT"
if [ -d "$ROOT/MACalendar/.git" ]; then
  say "Updating the code"
  git -C "$ROOT/MACalendar" pull --ff-only || echo "(kept your local version)"
else
  say "Fetching the code"
  git clone --depth 1 "$REPO_URL" "$ROOT/MACalendar"
fi

# 5. Everything else. Its questions read the KEYBOARD even when this script
#    came through a pipe (curl … | bash), and ${@+"$@"} keeps macOS's bash 3.2
#    from calling an empty argument list unbound.
if [ -r /dev/tty ] && [ -w /dev/tty ]; then
  exec "$PY" "$ROOT/MACalendar/install/install.py" --root "$ROOT" ${@+"$@"} </dev/tty
fi
exec "$PY" "$ROOT/MACalendar/install/install.py" --root "$ROOT" ${@+"$@"}

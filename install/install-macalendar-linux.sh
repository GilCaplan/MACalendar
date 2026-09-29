#!/usr/bin/env bash
# MACalendar installer for Linux — stage one.
#
#   curl -fsSL https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar-linux.sh | bash
#
# or download it and run:  bash install-macalendar-linux.sh
#
# It installs what the installer needs — git, Python 3.11+, the audio and Qt
# system libraries, and Ollama — using your distribution's package manager
# (apt, dnf or pacman; it asks for your password), fetches MACalendar into
# ~/MACalendar, and hands over to install/install.py. Safe to run again.
#
# MACALENDAR_HOME=/some/folder puts everything there instead of ~/MACalendar.
# Any arguments are passed on to install.py (e.g. --role helper, --yes).
set -euo pipefail

ROOT="${MACALENDAR_HOME:-$HOME/MACalendar}"
REPO_URL="https://github.com/GilCaplan/MACalendar.git"

say() { printf '\n▸ %s\n' "$*"; }
say "MACalendar installer — Linux, into $ROOT"

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

# 1. System packages. portaudio: the microphone. libxcb-cursor / xcb: Qt's
#    windows on X11. espeak-ng: a voice for spoken replies.
if command -v apt-get >/dev/null 2>&1; then
  say "Installing system packages (apt)"
  $SUDO apt-get update
  $SUDO apt-get install -y git curl python3 python3-venv python3-pip \
    libportaudio2 libxcb-cursor0 libxkbcommon-x11-0 libegl1 espeak-ng
elif command -v dnf >/dev/null 2>&1; then
  say "Installing system packages (dnf)"
  $SUDO dnf install -y git curl python3 python3-pip portaudio xcb-util-cursor \
    libxkbcommon-x11 espeak-ng
elif command -v pacman >/dev/null 2>&1; then
  say "Installing system packages (pacman)"
  $SUDO pacman -Sy --noconfirm --needed git curl python python-pip portaudio \
    xcb-util-cursor libxkbcommon-x11 espeak-ng
else
  echo "No apt, dnf or pacman here — install git, Python 3.11+ and portaudio yourself,"
  echo "then run: python3 install.py (from the MACalendar repository's install/ folder)."
  exit 1
fi

# 2. Python 3.11+.
PY=""
for v in python3.13 python3.12 python3.11 python3; do
  if command -v "$v" >/dev/null 2>&1 && \
     "$v" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$v"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is needed and your distribution's python3 is older."
  echo "Install python3.11 (Ubuntu 22.04: sudo add-apt-repository ppa:deadsnakes/ppa;"
  echo "sudo apt install python3.11 python3.11-venv), then run this again."
  exit 1
fi

# 3. Ollama, from its own installer.
if ! command -v ollama >/dev/null 2>&1; then
  say "Installing Ollama (runs the assistant's model on this computer)"
  curl -fsSL https://ollama.com/install.sh | sh
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

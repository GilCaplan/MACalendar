#!/usr/bin/env bash
# MACalendar installer for macOS AND Linux — stage one. It works out which it
# is on; you do not need to pick.
#
#   curl -fsSL https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar.sh | bash
#
# or download it and run:  bash install-macalendar.sh
# (On a Mac, install-macalendar-mac.command is the same thing, double-clickable.)
# On Windows, use install-macalendar-windows.ps1 instead.
#
# It installs what the installer needs — git, Python 3.11+ and Ollama (macOS:
# Apple's command-line tools and Homebrew; Linux: apt, dnf or pacman, plus the
# audio and Qt libraries) — fetches MACalendar into ~/MACalendar if it is not
# there yet, and hands over to install/install.py, which asks the rest: an
# existing install (update / reinstall / leave), the role, Jude, where the app
# icons go — and at the end offers to delete this file.
#
# MACALENDAR_HOME=/some/folder puts everything there instead of ~/MACalendar.
# Any arguments are passed on to install.py (e.g. --yes --role helper).
set -euo pipefail

ROOT="${MACALENDAR_HOME:-$HOME/MACalendar}"
REPO_URL="https://github.com/GilCaplan/MACalendar.git"
say() { printf '\n▸ %s\n' "$*"; }

# This file, when it IS a file (not piped from curl): install.py offers to
# delete it once everything is installed.
SELF=""
case "${BASH_SOURCE[0]:-}" in
  ""|bash|-bash|/dev/*|/proc/*) ;;
  *) [ -f "${BASH_SOURCE[0]}" ] && SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")" ;;
esac
# Launched by the double-click wrapper, which is the file the person downloaded.
[ -n "${MACALENDAR_INSTALLER_FILE:-}" ] && SELF="$MACALENDAR_INSTALLER_FILE"

OS="$(uname -s)"
case "$OS" in
  Darwin) KIND=mac ;;
  Linux)  KIND=linux ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "This is Windows. Open PowerShell and run:"
    echo "  irm https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar-windows.ps1 | iex"
    exit 1 ;;
  *) echo "Unsupported system: $OS (MACalendar installs on macOS, Linux and Windows)."; exit 1 ;;
esac
say "MACalendar installer — $([ $KIND = mac ] && echo macOS || echo Linux), into $ROOT"

if [ $KIND = mac ]; then
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
  # git comes with Apple's command-line tools.
  if ! xcode-select -p >/dev/null 2>&1; then
    say "Installing Apple's command-line tools (a window opens — click Install)"
    xcode-select --install || true
    echo "When that finishes, run this installer again."
    exit 1
  fi
  if ! command -v brew >/dev/null 2>&1; then
    say "Installing Homebrew (it asks for your Mac password)"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
  fi
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
else
  SUDO=""
  [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  # portaudio: the microphone. xcb-cursor etc: Qt's windows. espeak-ng: a voice.
  if command -v apt-get >/dev/null 2>&1; then
    say "Installing system packages (apt — it may ask for your password)"
    $SUDO apt-get update
    $SUDO apt-get install -y git curl python3 python3-venv python3-pip \
      libportaudio2 libxcb-cursor0 libxkbcommon-x11-0 libegl1 espeak-ng
  elif command -v dnf >/dev/null 2>&1; then
    say "Installing system packages (dnf — it may ask for your password)"
    $SUDO dnf install -y git curl python3 python3-pip portaudio xcb-util-cursor \
      libxkbcommon-x11 espeak-ng
  elif command -v pacman >/dev/null 2>&1; then
    say "Installing system packages (pacman — it may ask for your password)"
    $SUDO pacman -Sy --noconfirm --needed git curl python python-pip portaudio \
      xcb-util-cursor libxkbcommon-x11 espeak-ng
  else
    echo "No apt, dnf or pacman here — install git, Python 3.11+ and portaudio,"
    echo "then run: python3 install.py (in the MACalendar repository's install/ folder)."
    exit 1
  fi
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
  if ! command -v ollama >/dev/null 2>&1; then
    say "Installing Ollama (runs the assistant's model on this computer)"
    curl -fsSL https://ollama.com/install.sh | sh
  fi
fi

# The code — fetched once. An EXISTING copy is left for install.py to ask
# about (update, reinstall, or leave it as it is) — and it must be the NEWEST
# install.py asking, not the one inside an old copy, which would not know the
# question. So: fetch (the files you have stay as they are) and run the
# fetched installer; offline, the one you have.
mkdir -p "$ROOT"
INSTALLER="$ROOT/MACalendar/install/install.py"
if [ -d "$ROOT/MACalendar/.git" ]; then
  TMPD="$(mktemp -d)"
  if git -C "$ROOT/MACalendar" fetch --quiet --depth 1 origin 2>/dev/null && \
     git -C "$ROOT/MACalendar" show FETCH_HEAD:install/install.py > "$TMPD/install.py" 2>/dev/null; then
    INSTALLER="$TMPD/install.py"
  fi
else
  say "Fetching the code"
  git clone --depth 1 "$REPO_URL" "$ROOT/MACalendar"
fi

ARGS=(--root "$ROOT")
[ -n "$SELF" ] && ARGS+=(--installer-file "$SELF")
# Its questions read the KEYBOARD even when this came through a pipe
# (curl … | bash); ${@+"$@"} keeps macOS's bash 3.2 from calling an empty
# argument list unbound.
if [ -r /dev/tty ] && [ -w /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
  exec "$PY" "$INSTALLER" "${ARGS[@]}" ${@+"$@"} </dev/tty
fi
exec "$PY" "$INSTALLER" "${ARGS[@]}" ${@+"$@"}

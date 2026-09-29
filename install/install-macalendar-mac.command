#!/bin/bash
# MACalendar installer — double-click me on a Mac.
# (The first time, macOS may say I am from an unidentified developer:
# right-click me ▸ Open ▸ Open.)
#
# I run the universal installer, install-macalendar.sh — the one beside me if
# I am inside the repository, otherwise a fresh copy from GitHub — and pass
# my own path on, so the installer can offer to delete me when it is done.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export MACALENDAR_INSTALLER_FILE="$HERE/$(basename "$0")"
if [ -f "$HERE/install-macalendar.sh" ]; then
  exec bash "$HERE/install-macalendar.sh" ${@+"$@"}
fi
TMP="$(mktemp -t macalendar-install)"
curl -fsSL https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar.sh -o "$TMP"
exec bash "$TMP" ${@+"$@"}

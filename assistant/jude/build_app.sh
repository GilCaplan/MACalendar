#!/bin/zsh
# Rebuild "Jude.app" from launch.sh.
#
#   assistant/jude/build_app.sh             # into the repo
#   assistant/jude/build_app.sh --install   # + ~/Desktop and /Applications
#
# The bundle is a build artefact, not source — gitignored, and rebuilt from here
# so the AppleScript inside it stays reviewable like any other file.
#
# THE THING THIS SCRIPT EXISTS TO GET RIGHT (learned the hard way on the HUD):
# osacompile ad-hoc-signs the bundle, and every PlistBuddy edit afterwards
# INVALIDATES that signature. A bundle whose Info.plist no longer matches its
# seal has no stable identity, and macOS will not file it under its own name in
# Settings > Privacy & Security > Files and Folders — it shows up as the bare
# executable "applet", with no working toggle. It then cannot be granted Desktop
# access, and because this project lives under ~/Desktop the app dies with
#
#     python: realpath: .venv/bin/: Operation not permitted
#
# which reads like a broken venv and is actually a missing TCC grant. So: edit
# the plist FIRST, re-sign LAST, and VERIFY — the verify is what stops this
# regressing silently, because a broken seal costs nothing until the day you
# need the app in that list.
set -eu
cd "$(dirname "$0")/../.."          # assistant/jude -> assistant -> repo
REPO="$(pwd)"
BUNDLE_ID="com.macalendar.jude"
ICON="$REPO/assistant/jude/assets/jude_icon.icns"

if [[ ! -f "$ICON" ]]; then
  echo "no icon at $ICON — run: ./.venv/bin/python assistant/jude/assets/make_icon.py"
  exit 1
fi

build() {
  local out="$1"
  rm -rf "$out"
  # Call the repo copy of launch.sh directly, exactly as "MACalendar.app" calls
  # `Launch Calendar.command`. One copy of the script means the thing that runs
  # cannot drift from the thing that gets edited.
  osacompile -o "$out" -e "do shell script \"mkdir -p ~/.assistant_tools && MACALENDAR_DETACHED=1 '$REPO/assistant/jude/launch.sh' >> ~/.assistant_tools/jude-launch.log 2>&1\""

  /usr/libexec/PlistBuddy -c "Set :CFBundleName 'Jude'" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 'Jude'" "$out/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName 'Jude'" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$out/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :NSDesktopFolderUsageDescription string 'Starts the Jude window from the project folder.'" "$out/Contents/Info.plist" 2>/dev/null || true
  # NOT LSUIElement: unlike the HUD, this is a real window with a real Dock icon.
  cp "$ICON" "$out/Contents/Resources/applet.icns"

  # Re-seal. --identifier must match CFBundleIdentifier, or the bundle is
  # inconsistent in the same way it was before, just less obviously.
  codesign --force --sign - --identifier "$BUNDLE_ID" "$out"

  # The guard. If this fails the app is unusable for the purpose it was built
  # for, so fail the build rather than ship something that looks fine in Finder
  # and cannot be granted anything.
  codesign --verify --strict "$out" 2>&1 || { echo "FAILED to seal $out"; exit 1; }
  local sig_id
  sig_id="$(codesign -dv "$out" 2>&1 | sed -n 's/^Identifier=//p')"
  [[ "$sig_id" == "$BUNDLE_ID" ]] || { echo "signature id '$sig_id' != '$BUNDLE_ID'"; exit 1; }

  touch "$out"
  echo "built + sealed $out  ($BUNDLE_ID)"
}

build "$REPO/Jude.app"
if [[ "${1:-}" == "--install" ]]; then
  build "$HOME/Desktop/Jude.app"
  build "/Applications/Jude.app"
  # Clear any half-recorded decision against this identity, so macOS asks again
  # on the next launch instead of silently refusing forever.
  tccutil reset SystemPolicyDesktopFolder "$BUNDLE_ID" 2>/dev/null || true
  tccutil reset All "$BUNDLE_ID" 2>/dev/null || true
  echo
  echo "Now launch it once and APPROVE the Desktop prompt."
  echo "If no prompt appears: Settings > Privacy & Security > Files and Folders > Jude."
fi

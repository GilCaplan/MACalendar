#!/bin/zsh
# Rebuild "MACalendar HUD.app" from launch_hud.sh.
#
# The bundle is a build artefact, not source — it is gitignored and rebuilt from
# here so the AppleScript inside it can be diffed and reviewed like anything
# else.
#
# THE THING THIS SCRIPT EXISTS TO GET RIGHT: osacompile ad-hoc-signs the bundle,
# and every PlistBuddy edit afterwards INVALIDATES that signature. A bundle whose
# Info.plist no longer matches its seal has no stable identity, and macOS will
# not file it under its own name in Settings ▸ Privacy ▸ Files and Folders — it
# appears as the bare executable, "applet", with no working toggle. The app then
# cannot be granted Desktop access, and because this project lives under
# ~/Desktop the HUD dies with
#
#     python: realpath: .venv/bin/: Operation not permitted
#
# which reads like a broken venv and is actually a missing TCC grant. So: edit
# the plist FIRST, re-sign LAST, and verify — the verify is what stops this
# regressing silently, because a broken seal costs nothing until the day you
# need the app in that list.
set -eu
cd "$(dirname "$0")/.."
REPO="$(pwd)"
BUNDLE_ID="com.macalendar.hud"
# Its OWN icon. This used to copy assistant/app_icon.icns, so the HUD and the
# calendar were identical in the Dock — two apps you click for different
# reasons wearing the same face.
ICON="$REPO/assistant/calendar_ui/assets/hud_icon.icns"

if [[ ! -f "$ICON" ]]; then
  echo "no icon at $ICON — run: ./.venv/bin/python assistant/calendar_ui/assets/make_hud_icon.py"
  exit 1
fi

build() {
  local out="$1"
  rm -rf "$out"
  # Call the repo copy directly, exactly as "MACalendar.app" calls
  # `Launch Calendar.command`. One copy of the script means it cannot drift
  # from the one that gets edited.
  osacompile -o "$out" -e "do shell script \"mkdir -p ~/.assistant_tools && MACALENDAR_DETACHED=1 '$REPO/launch_hud.sh' >> ~/.assistant_tools/hud-launch.log 2>&1\""

  /usr/libexec/PlistBuddy -c "Set :CFBundleName 'MACalendar HUD'" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 'MACalendar HUD'" "$out/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName 'MACalendar HUD'" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$out/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$out/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :NSDesktopFolderUsageDescription string 'Starts the thinking card from the project folder.'" "$out/Contents/Info.plist" 2>/dev/null || true
  cp "$ICON" "$out/Contents/Resources/applet.icns"
  # osacompile also ships the STOCK applet asset catalog (Assets.car) and points
  # CFBundleIconName at it; on current macOS that wins over CFBundleIconFile, so
  # the icns above was never drawn and the app wore the grey script-scroll face
  # (found 2026-09-27 on Tahoe). Drop both so the icns is the only icon.
  /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$out/Contents/Info.plist" 2>/dev/null || true
  rm -f "$out/Contents/Resources/Assets.car"

  # Re-seal. --identifier must match CFBundleIdentifier or the bundle is
  # inconsistent in the same way it was before, just less obviously.
  codesign --force --sign - --identifier "$BUNDLE_ID" "$out"

  # The guard. If this fails the app is unusable for the purpose it was built
  # for, so fail the build rather than shipping something that looks fine in
  # Finder and cannot be granted anything.
  codesign --verify --strict "$out" 2>&1 || { echo "FAILED to seal $out"; exit 1; }
  local sig_id
  sig_id="$(codesign -dv "$out" 2>&1 | sed -n 's/^Identifier=//p')"
  [[ "$sig_id" == "$BUNDLE_ID" ]] || { echo "signature id '$sig_id' != '$BUNDLE_ID'"; exit 1; }
  if /usr/libexec/PlistBuddy -c "Print :CFBundleIconName" "$out/Contents/Info.plist" >/dev/null 2>&1; then
    echo "$out still names the stock icon catalog"; exit 1
  fi
  if [[ -e "$out/Contents/Resources/Assets.car" ]]; then
    echo "$out still carries the stock Assets.car"; exit 1
  fi

  touch "$out"
  echo "built + sealed $out  ($BUNDLE_ID)"
}

build "$REPO/MACalendar HUD.app"
if [[ "${1:-}" == "--install" ]]; then
  # Into the ONE folder the apps live in (scripts/build_apps.sh), never loose on
  # the Desktop or in /Applications — loose copies are what an older install
  # then "tidied" away (2026-09-26, no touch).
  mkdir -p "/Applications/MACalendar APPs"
  build "/Applications/MACalendar APPs/MACalendar HUD.app"
  # Clear any half-recorded decision against this identity, so macOS asks again
  # on the next launch instead of silently refusing forever.
  tccutil reset SystemPolicyDesktopFolder "$BUNDLE_ID" 2>/dev/null || true
  tccutil reset All "$BUNDLE_ID" 2>/dev/null || true
  echo
  echo "Now launch it once and APPROVE the Desktop prompt."
  echo "If no prompt appears: Settings > Privacy & Security > Files and Folders > MACalendar HUD."
fi

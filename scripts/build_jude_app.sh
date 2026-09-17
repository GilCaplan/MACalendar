#!/bin/zsh
# Rebuild "Jude.app" from launch_jude.sh.
#
# Mirrors build_hud_app.sh exactly — same bundle artifact, same reasoning, and
# the same thing to get right: osacompile ad-hoc-signs the bundle, and every
# PlistBuddy edit afterwards INVALIDATES that signature. Edit the plist FIRST,
# re-sign LAST, and verify, or the bundle loses its stable identity (macOS
# files it under "applet" in Settings ▸ Privacy ▸ Files and Folders instead of
# its own name, with no working toggle) and dies under ~/Desktop with
# "python: realpath: .venv/bin/: Operation not permitted" — a TCC grant it can
# no longer be given, not a broken venv.
set -eu
cd "$(dirname "$0")/.."
REPO="$(pwd)"
BUNDLE_ID="com.macalendar.jude"

build() {
  local out="$1"
  rm -rf "$out"
  # Call the repo copy directly, exactly as "MACalendar HUD.app" calls
  # launch_hud.sh — one copy of the script means it cannot drift from the one
  # that gets edited.
  osacompile -o "$out" -e "do shell script \"mkdir -p ~/.assistant_tools && MACALENDAR_DETACHED=1 '$REPO/launch_jude.sh' >> ~/.assistant_tools/jude-launch.log 2>&1\""

  /usr/libexec/PlistBuddy -c "Set :CFBundleName 'Jude'" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 'Jude'" "$out/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName 'Jude'" "$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$out/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$out/Contents/Info.plist"
  # Unlike the HUD (a floating card, LSUIElement=true, no Dock icon), Jude is a
  # real window someone reads and types in for a while — it gets a normal Dock
  # presence, matching MACalendar.app's own launcher rather than the HUD's.
  /usr/libexec/PlistBuddy -c "Add :NSDesktopFolderUsageDescription string 'Starts Jude from the project folder.'" "$out/Contents/Info.plist" 2>/dev/null || true
  # No dedicated Jude icon yet — reuses the app icon, same as the HUD does.
  cp assistant/app_icon.icns "$out/Contents/Resources/applet.icns"

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

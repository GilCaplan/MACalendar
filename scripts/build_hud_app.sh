#!/bin/zsh
# Rebuild "MACalendar HUD.app" from launch_hud.sh.
#
# The bundle is a build artefact, not source — it is gitignored and rebuilt from
# here so the AppleScript inside it can be diffed and reviewed like anything
# else. osacompile ad-hoc re-signs on every build, which is why rebuilding
# repeatedly can make macOS treat it as a different app.
set -eu
cd "$(dirname "$0")/.."
REPO="$(pwd)"
build() {
  local out="$1"
  rm -rf "$out"
  osacompile -o "$out" -e "do shell script \"mkdir -p ~/.assistant_tools && MACALENDAR_DETACHED=1 '$REPO/launch_hud.sh' >> ~/.assistant_tools/hud-launch.log 2>&1\""
  /usr/libexec/PlistBuddy -c "Set :CFBundleName 'MACalendar HUD'" "$out/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 'MACalendar HUD'" "$out/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.macalendar.hud" "$out/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$out/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :NSDesktopFolderUsageDescription string 'Starts the thinking card from the project folder.'" "$out/Contents/Info.plist" 2>/dev/null || true
  cp assistant/app_icon.icns "$out/Contents/Resources/applet.icns"
  touch "$out"
  echo "built $out"
}
build "$REPO/MACalendar HUD.app"
[[ "${1:-}" == "--desktop" ]] && build "$HOME/Desktop/MACalendar HUD.app"

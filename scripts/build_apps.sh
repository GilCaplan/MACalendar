#!/bin/zsh
# Build every launcher app into ONE folder, icons and all.
#
#     scripts/build_apps.sh              # build into "MACalendar APPs/"
#     scripts/build_apps.sh --install    # ...and into "/Applications/MACalendar APPs/"
#
# Gil, 2026-09-18: every runnable piece should be an app with its own icon, all
# of them in one folder in Applications, and the loose copies scattered over
# /Applications and the Desktop gone.
#
# Four apps, because four things run:
#
#     MACalendar Server   assistant.api      — the brain's front door
#     MACalendar          assistant.main     — the calendar window
#     MACalendar HUD      thinking_hud       — the floating review card
#     Jude                jude               — the Judaic study assistant
#
# The iPhone app is not here on purpose: it is installed on the phone, not on
# this Mac, and it carries its own AppIcon asset.
#
# THE THING THIS GETS RIGHT, inherited from build_hud_app.sh: osacompile
# ad-hoc-signs the bundle, and every PlistBuddy edit AFTERWARDS invalidates that
# signature. A bundle whose Info.plist no longer matches its seal has no stable
# identity, macOS will not file it under its own name in Settings ▸ Privacy ▸
# Files and Folders, and it can never be granted Desktop access — which this
# project needs, because it lives under ~/Desktop. So: plist first, icon, then
# re-sign, then VERIFY. The verify is what stops it regressing silently.
set -eu
cd "$(dirname "$0")/.."
REPO="$(pwd)"
FOLDER="MACalendar APPs"

ICONS="$REPO/assistant/calendar_ui/assets"
[[ -f "$ICONS/server_icon.icns" ]] || \
  ./.venv/bin/python "$ICONS/make_server_icon.py" >/dev/null
[[ -f "$ICONS/hud_icon.icns" ]] || \
  ./.venv/bin/python "$ICONS/make_hud_icon.py" >/dev/null

build() {
  local out="$1" name="$2" bundle="$3" icon="$4" cmd="$5" agent="$6"
  rm -rf "$out"
  osacompile -o "$out" -e \
    "do shell script \"mkdir -p ~/.assistant_tools && $cmd >> ~/.assistant_tools/$(echo "$name" | tr 'A-Z ' 'a-z-')-launch.log 2>&1 &\""

  local plist="$out/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Set :CFBundleName '$name'" "$plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string '$name'" "$plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName '$name'" "$plist"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $bundle" "$plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $bundle" "$plist"
  [[ "$agent" == "true" ]] && \
    /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :NSDesktopFolderUsageDescription string 'Runs MACalendar from the project folder.'" "$plist" 2>/dev/null || true

  if [[ -f "$icon" ]]; then
    cp "$icon" "$out/Contents/Resources/applet.icns"
  else
    echo "  ! no icon at $icon — $name will wear the generic applet face"
  fi

  # Re-seal LAST. --identifier must match CFBundleIdentifier, or the bundle is
  # inconsistent in the same way it was before, just less obviously.
  codesign --force --sign - --identifier "$bundle" "$out"
  codesign --verify --strict "$out" 2>&1 || { echo "FAILED to seal $out"; exit 1; }
  local sig
  sig="$(codesign -dv "$out" 2>&1 | sed -n 's/^Identifier=//p')"
  [[ "$sig" == "$bundle" ]] || { echo "signature '$sig' != '$bundle'"; exit 1; }
  touch "$out"
  echo "  built  $name  ($bundle)"
}

# Explicit calls rather than a delimited list: zsh's `IFS=... read <<<` split
# the fields differently from bash and leaked the variables into the output,
# building one app at "./.app". Four calls are longer and cannot do that.
build_all_into() {
  local dir="$1"
  mkdir -p "$dir"
  echo "$dir"
  build "$dir/MACalendar Server.app" "MACalendar Server" "com.macalendar.server" \
    "$ICONS/server_icon.icns" \
    "cd '$REPO' && ./.venv/bin/python -m assistant.api --tailscale" true
  build "$dir/MACalendar.app" "MACalendar" "com.macalendar.app.launcher" \
    "$REPO/assistant/app_icon.icns" \
    "'$REPO/Launch Calendar.command'" false
  build "$dir/MACalendar HUD.app" "MACalendar HUD" "com.macalendar.hud" \
    "$ICONS/hud_icon.icns" \
    "MACALENDAR_DETACHED=1 '$REPO/launch_hud.sh'" true
  build "$dir/Jude.app" "Jude" "com.macalendar.jude" \
    "$REPO/assistant/jude/assets/jude_icon.icns" \
    "cd '$REPO' && ./.venv/bin/python -m assistant.jude" false
}

build_all_into "$REPO/$FOLDER"

if [[ "${1:-}" == "--install" ]]; then
  build_all_into "/Applications/$FOLDER"
  # The loose copies this replaces. Leaving them means two icons with one name
  # and no way to tell which one you just clicked.
  for stale in "/Applications/MACalendar.app" "/Applications/MACalendar HUD.app" \
               "/Applications/Jude.app" "$HOME/Desktop/MACalendar.app" \
               "$HOME/Desktop/MACalendar HUD.app"; do
    [[ -e "$stale" ]] && rm -rf "$stale" && echo "  removed stale  $stale"
  done
  # Clear any half-recorded privacy decision against these identities, so macOS
  # asks again on the next launch instead of silently refusing forever.
  for bundle in com.macalendar.server com.macalendar.app.launcher \
                com.macalendar.hud com.macalendar.jude; do
    tccutil reset SystemPolicyDesktopFolder "$bundle" 2>/dev/null || true
  done
  echo
  echo "All four are in /Applications/$FOLDER."
  echo "Launch each once and APPROVE the Desktop prompt if it appears."
fi

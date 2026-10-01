#!/bin/bash
# Builds MACalendar Magic — the Mac's Easter egg — from the phone's shared
# drawing and decision code (MACalendar-iOS/.../EasterEgg) plus the Mac's own
# window, store and settings (this folder). Output: build/MACalendarMagic.
# The calendar app runs this on first start when the binary is missing.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
EGG="$HERE/../../MACalendar-iOS/MACalendar-iOS/EasterEgg"
mkdir -p "$HERE/build"
swiftc -O -parse-as-library -target "$(uname -m)-apple-macos14.0" \
  "$EGG/EggArt.swift" "$EGG/EggFigures.swift" "$EGG/EggJewish.swift" "$EGG/EggEffects.swift" \
  "$EGG/EggCatalog.swift" "$EGG/EggRules.swift" "$EGG/EggStage.swift" "$EGG/EggTrails.swift" \
  "$EGG/EggPuppet.swift" "$EGG/EggImageCore.swift" "$EGG/EggSynth.swift" "$EGG/EggLoader.swift" "$EGG/EggWordBank.swift" "$EGG/EggSymbol.swift" "$EGG/EggOnDevice.swift" "$EGG/EggActivities.swift" \
  "$HERE/MacOverlay.swift" "$HERE/MacEggStore.swift" "$HERE/MacSettingsView.swift" "$HERE/MacWords.swift" "$HERE/MacPhotos.swift" "$HERE/MacLoader.swift" "$HERE/MacMain.swift" \
  -o "$HERE/build/MACalendarMagic"
echo "$HERE/build/MACalendarMagic"

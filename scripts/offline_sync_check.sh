#!/usr/bin/env bash
#
# Prove the offline -> reconnect cycle on the phone, end to end, against a real Mac.
#
# The Coursework data-loss fix (commit bbe7892) was proven by reading the Swift
# and by server-side unit tests. This watches a row make the round trip: added
# on the phone with the Mac away, arriving on the Mac when it comes back,
# deleted with the Mac away again, and STAYING deleted — which is the bug that
# was reported ("delete a course offline and it comes back").
#
# Two halves, because neither can see the other's evidence:
#
#   MACalendarUITests/OfflineSyncUITests.swift   drives the real app in the
#       simulator through the real `mutate` -> `LocalStore.enqueue` ->
#       `syncPending` path, and reads the queue off the offline banner.
#   this script                                 watches the MAC's own database
#       over HTTP while that runs, because a UI test cannot see it.
#
# The test cannot know it reached the Mac and this script cannot know what the
# app did; together they answer both. The course name is minted HERE and handed
# to the test through `TEST_RUNNER_MACALENDAR_UITEST_COURSE` (xcodebuild passes
# any `TEST_RUNNER_`-prefixed variable to the test process with the prefix
# stripped), so this script knows exactly which row to look for.
#
# Usage:
#
#     scripts/offline_sync_check.sh                 # the booted simulator, the local API
#     SIM_ID=<udid> API=http://127.0.0.1:8080 scripts/offline_sync_check.sh
#
# It needs: a booted iOS simulator, `python -m assistant.api` running on this
# Mac, and Xcode. It takes about five minutes, most of it the test's six app
# launches and the waits for the queue to flush.
#
# WHAT IT CHANGES, AND PUTS BACK:
#   * the app is UNINSTALLED from the simulator first (a stale local cache or a
#     leftover queue from an earlier run would decide the answer), and left
#     installed afterwards;
#   * `features.coursework` on the Mac is switched ON by the test if it is off —
#     the tab cannot be driven while it is hidden — and this script restores
#     whatever it was;
#   * the course it creates is deleted by the test itself; any "UITest …" row
#     that survives a crash is swept up at the end.

set -uo pipefail

API="${API:-http://127.0.0.1:8080}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$HERE/MACalendar-iOS/MACalendar-iOS.xcodeproj"
SCHEME="MACalendarUITests"
BUNDLE_ID="com.macalendar.app"
DD="${DERIVED_DATA:-/tmp/macalendar-uitest-dd}"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL\033[0m  %s\n' "$*"; }
ok()   { printf '\033[32mok\033[0m    %s\n' "$*"; }

# -- the simulator ----------------------------------------------------------
# Not a UDID typed into the repository: `name=iPhone 17` is ambiguous when two
# simulators share the name, so the booted one is asked for by id.
if [[ -z "${SIM_ID:-}" ]]; then
  SIM_ID=$(xcrun simctl list devices booted -j \
    | python3 -c 'import json,sys; d=json.load(sys.stdin)["devices"]; ids=[x["udid"] for v in d.values() for x in v]; print(ids[0] if ids else "")')
fi
if [[ -z "$SIM_ID" ]]; then
  fail "no booted iOS simulator — boot one (Simulator.app) or pass SIM_ID=<udid>"
  exit 2
fi

# -- the Mac ----------------------------------------------------------------
if ! curl -fsS -m 5 "$API/features" >/dev/null; then
  fail "$API is not answering — start it with: python -m assistant.api"
  exit 2
fi

courses_json() { curl -fsS -m 10 "$API/courses"; }
has_course()   { courses_json | COURSE="$1" python3 -c 'import json,os,sys; sys.exit(0 if any(c["name"]==os.environ["COURSE"] for c in json.load(sys.stdin)) else 1)'; }
coursework_visible() {
  curl -fsS -m 5 "$API/features" \
    | python3 -c 'import json,sys; print(str([f["visible"] for f in json.load(sys.stdin) if f["name"]=="coursework"][0]).lower())'
}

BEFORE_VISIBLE=$(coursework_visible)
COURSE="UITest $(uuidgen | cut -c1-8)"
WORK=$(mktemp -d)
SEEN="$WORK/seen"

sweep_leftovers() {
  # Any "UITest …" row a crashed run left behind, this run's included. The test
  # deletes its own; this is the safety net, and it never touches a real course.
  courses_json 2>/dev/null | API="$API" python3 -c '
import json, os, subprocess, sys
api = os.environ["API"]
try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []
for c in rows:
    if c["name"].startswith("UITest "):
        subprocess.run(["curl", "-fsS", "-m", "5", "-X", "DELETE",
                        api + "/courses/" + str(c["id"])], capture_output=True)
        print("   swept up leftover course " + repr(c["name"]))
' 
}

restore() {
  [[ -n "${WATCH_PID:-}" ]] && kill "$WATCH_PID" 2>/dev/null
  curl -fsS -m 5 -X PATCH -H 'Content-Type: application/json' \
       -d "{\"visible\": $BEFORE_VISIBLE}" "$API/features/coursework" >/dev/null 2>&1
  sweep_leftovers
}
trap restore EXIT

say "Offline round trip — course: $COURSE"
echo "  simulator $SIM_ID"
echo "  Mac       $API   (features.coursework = $BEFORE_VISIBLE)"

# A clean phone: a cache or a queue left by an earlier run would answer the
# question before the test asked it.
xcrun simctl uninstall "$SIM_ID" "$BUNDLE_ID" >/dev/null 2>&1

# -- watch the Mac while the test runs --------------------------------------
# The test's own assertions cover the phone; this covers the Mac. It records
# that the row ARRIVED, which a single check at the end cannot: by then the
# test has deleted it again, and "never there" and "there and then gone" look
# identical.
(
  while true; do
    if has_course "$COURSE"; then : > "$SEEN"; fi
    sleep 2
  done
) &
WATCH_PID=$!
disown %% 2>/dev/null || true      # no "Terminated:" notice when it is killed

say "Running the UI test (about five minutes, six app launches)"
TEST_RUNNER_MACALENDAR_UITEST_COURSE="$COURSE" \
xcodebuild test \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -destination "platform=iOS Simulator,id=$SIM_ID" \
  -derivedDataPath "$DD" \
  2>&1 | grep -E "Test Case|error:|XCTAssert|Executed [0-9]"
TEST_STATUS=${PIPESTATUS[0]}

kill "$WATCH_PID" 2>/dev/null
WATCH_PID=""

# -- the Mac's own answer ---------------------------------------------------
say "Checking the Mac"
STATUS=0

if [[ -f "$SEEN" ]]; then
  ok "GET /courses saw '$COURSE' — the course added with the Mac away REACHED IT on reconnect"
else
  fail "'$COURSE' never appeared in GET /courses — the queued create never landed"
  STATUS=1
fi

if has_course "$COURSE"; then
  fail "'$COURSE' is STILL on the Mac — the delete made offline was lost (this is the reported bug)"
  STATUS=1
else
  ok "GET /courses no longer has '$COURSE' — the delete made offline STUCK"
fi

if [[ $TEST_STATUS -ne 0 ]]; then
  fail "the UI test itself failed (xcodebuild exit $TEST_STATUS) — read its assertion above"
  STATUS=1
else
  ok "the UI test passed: the phone kept the row offline, flushed it, and kept it deleted"
fi

say "Putting things back"
exit $STATUS

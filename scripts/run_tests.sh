#!/usr/bin/env bash
# The whole suite, the way CI runs it: everything in one pytest process,
# except each Qt UI test file, which gets a process of its own.
#
#   scripts/run_tests.sh -v          # extra args go to every pytest call
#   PYTHON=./.venv/bin/python scripts/run_tests.sh
#
# Why the Qt files are split out (2026-10-06, TASKS 53 recurring): CI
# segfaulted intermittently — runs 105-158, about one main run in twelve —
# always inside a Qt test walking a widget tree (findChildren / findChild),
# in whichever Qt test was running when it struck: the Settings dialog's
# observance tests on CI, the HUD's _make_read_only here. Reproduced locally
# on Python 3.11 with the code unchanged; never in a file run alone. A widget
# destroyed by an EARLIER test, at whatever moment the garbage collector frees
# it, leaves PyQt able to hand back a stale wrapper once its address is
# reused. Changing lifetimes inside one process made it worse both ways
# (deleting every leftover window: 4 crashes in 4 runs; keeping them all:
# 34 failures), so no test inherits another file's widgets instead.
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

QT_FILES=()
while IFS= read -r f; do QT_FILES+=("$f"); done < <(grep -l "PyQt6" tests/unit/test_*.py | sort)

ignores=()
for f in "${QT_FILES[@]}"; do ignores+=("--ignore=$f"); done

status=0
"$PY" -m pytest tests/ "${ignores[@]}" "$@" || status=$?

failed=()
for f in "${QT_FILES[@]}"; do
    "$PY" -m pytest "$f" "$@"
    rc=$?
    # 5 = nothing collected (every test skipped at import) — not a failure.
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 5 ]; then failed+=("$f (exit $rc)"); fi
done

if [ "${#failed[@]}" -gt 0 ]; then
    echo
    echo "Qt test files that failed:"
    printf '  %s\n' "${failed[@]}"
    status=1
fi
exit "$status"

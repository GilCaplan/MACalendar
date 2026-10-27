"""A long take keeps all of what was said, not its last sentence.

Gil, 2026-10-27: "when I record for, like, a long time, let's say over 30
seconds, it only seems to capture, like, the last part". On device, Apple's
recogniser can begin a new segment after a pause and report only that segment;
`handlePartial` set `liveText` to the latest partial, so everything before the
pause was dropped — and that transcript is what the phone reads and sends.

The rule is mirrored here in Python and checked against the Swift source, the
way the other iOS checks work (no Swift target in CI).
"""

from __future__ import annotations

import re

from tests.unit._ios_sources import ios_source

SRC = ios_source("VoiceRecorder.swift")


def _words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def starts_over(old: str, new: str) -> bool:
    """`VoiceRecorder.startsOver`, transcribed."""
    o, n = _words(old), _words(new)
    if len(o) < 3 or not n:
        return False
    if len(n) * 2 < len(o):
        return True
    return len(n) < len(o) and o[:2] != n[:2]


def heard(partials):
    """What `liveText` ends as after a stream of partials (no resume)."""
    done, last = "", ""
    for p in partials:
        if starts_over(last, p):
            done = f"{done} {last}".strip()
        last = p
    return f"{done} {last}".strip()


def test_a_new_segment_after_a_pause_is_added_not_swapped_in():
    stream = ["add", "add a meeting", "add a meeting with Dana tomorrow at ten",
              # pause — the recogniser starts a fresh segment
              "and", "and remind me", "and remind me to bring the slides"]
    assert heard(stream) == ("add a meeting with Dana tomorrow at ten "
                             "and remind me to bring the slides")


def test_a_partial_that_rewords_its_end_is_not_a_new_segment():
    stream = ["buy milk and eggs", "buy milk and egg", "buy milk and eggs please"]
    assert heard(stream) == "buy milk and eggs please"


def test_the_swift_keeps_segments_by_the_same_rule():
    body = SRC.split("private func handlePartial(", 1)[1].split("\n    }\n", 1)[0]
    assert "Self.startsOver(from: lastPartial, to: text)" in body
    assert "segmentsDone = Self.joined(segmentsDone, lastPartial)" in body
    assert "Self.joined(Self.joined(heardBefore, segmentsDone), text)" in body
    rule = SRC.split("static func startsOver(", 1)[1].split("\n    }\n", 1)[0]
    assert "o.count >= 3" in rule and "n.count * 2 < o.count" in rule
    assert "!o.prefix(2).elementsEqual(n.prefix(2))" in rule
    # a new take starts with nothing carried over
    start = SRC.split("func start(resume: Bool = false) {", 1)[1].split("\n    }\n", 1)[0]
    assert 'segmentsDone = ""; lastPartial = ""' in start

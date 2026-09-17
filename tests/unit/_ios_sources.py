"""Find an iOS source file by NAME, not by path.

Several Python tests read Swift source to check that the two platforms agree —
the same presets, the same refresh words, the same stage names. Each one used to
hardcode `MACalendar-iOS/MACalendar-iOS/Views/<file>.swift`.

Which broke the moment the iOS app was reorganised into per-feature folders
(`Features/Timer/TimerView.swift`), and would break again on the next move.
CLAUDE.md names this failure mode directly: *"A path or import in an
experiment, generator or checker rots silently, and only breaks when you next
run it."* These at least break loudly — but they break for a reason that has
nothing to do with what they are testing, which sends you looking in the wrong
place.

A filename is stable in a way a folder is not: `TimerView.swift` is still
`TimerView.swift` wherever it lives. So these look it up.
"""

from __future__ import annotations

import functools
import pathlib

IOS_ROOT = pathlib.Path(__file__).resolve().parents[2] / "MACalendar-iOS"


@functools.lru_cache(maxsize=None)
def _index() -> "dict[str, list[pathlib.Path]]":
    found: "dict[str, list[pathlib.Path]]" = {}
    for path in IOS_ROOT.rglob("*.swift"):
        found.setdefault(path.name, []).append(path)
    return found


def ios_source(filename: str) -> str:
    """The contents of the one iOS source file with this name.

    Raises if it is missing or ambiguous, rather than returning something
    plausible: a parity test reading the wrong file passes for the wrong reason,
    which is worse than failing.
    """
    matches = _index().get(filename, [])
    if not matches:
        raise FileNotFoundError(
            f"No {filename} anywhere under {IOS_ROOT}. If it was renamed, this "
            f"test's subject moved — update the name, not the path.")
    if len(matches) > 1:
        raise AssertionError(
            f"{len(matches)} files named {filename}: "
            + ", ".join(str(m.relative_to(IOS_ROOT)) for m in matches))
    return matches[0].read_text()


def all_ios_sources() -> str:
    """Every Swift source in the iOS target, concatenated.

    For questions of the form "does the app handle X anywhere?". Naming the two
    files that happened to handle it at the time makes the test a hostage to
    where the code lives: moving a branch into a feature folder then reads as
    the branch having been DELETED, which is a frightening and false result.
    """
    return "\n".join(p.read_text() for p in sorted(IOS_ROOT.rglob("*.swift")))

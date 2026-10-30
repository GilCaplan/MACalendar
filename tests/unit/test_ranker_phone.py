"""The phone's Ranker ranks by itself, by the Mac's rules.

Gil, 2026-10-12, on a phone whose Ranker tab said "Ranking runs on your Mac —
it isn't reachable right now": *"Ranking shouldnt be dependent on the os
server… just sync otherwise should work on phone according to original specs
i gave"*. So `Features/Ranker/RankerEngine.swift` is a port of `table.py`,
`rank.py` and `ocr.py`, and `RankerStore.swift` keeps the state on the phone
and syncs it.

This suite has no Swift compiler, so it holds the port to what CAN be read off
the source: the patterns that decide what counts as a number are the Python's
own, the tab sends no file to the Mac, and nothing on the ranking path waits
for it.
"""

from __future__ import annotations

import re

from assistant.features.ranker import ocr, rank, store, table
from tests.unit._ios_sources import ios_source

ENGINE = ios_source("RankerEngine.swift")
STORE = ios_source("RankerStore.swift")
VIEW = ios_source("RankerView.swift")
API = ios_source("RankerAPI.swift")


def _swift_patterns(src: str) -> list[str]:
    """Every NSRegularExpression pattern literal, unescaped to its regex."""
    return [m.encode().decode("unicode_escape")
            for m in re.findall(r'NSRegularExpression\(\s*pattern:\s*"((?:[^"\\]|\\.)*)"', src)]


def test_the_picture_rule_is_the_macs():
    """`#1172` counts, "Ruling Guild: #1169" does not — the same two patterns."""
    pats = _swift_patterns(ENGINE)
    assert ocr._HASHED.pattern in pats and ocr._BARE.pattern in pats


def test_a_cell_reads_as_a_number_by_the_macs_pattern():
    assert table._NUM.pattern in _swift_patterns(ENGINE)
    for suffix, size in table._SUFFIX.items():
        assert f'case "{suffix}": return v * 1e{len(str(int(size))) - 1}' in ENGINE, suffix


def test_the_comparisons_are_the_macs():
    ops = re.search(r"static let ops = \[([^\]]*)\]", ios_source("RankerModels.swift")).group(1)
    assert tuple(re.findall(r'"([^"]+)"', ops)) == rank.OPS


def test_a_fresh_phone_starts_on_the_macs_blank_ranking():
    assert f'RankerRecipe(name: "{store.BLANK_RECIPE["name"]}")' in STORE


def test_every_step_of_the_macs_ranking_is_ported():
    for step in ("func fit(", "func bestKey(", "func percentiles(", "func passes(", "func rank("):
        assert step in ENGINE, step
    # the score is a weighted average of percentiles; ties keep the table's order
    assert "-scores[$0], $0" in ENGINE


def test_the_tab_sends_no_file_and_never_waits_for_the_mac_to_rank():
    for src in (API, VIEW, STORE):
        assert "multipart" not in src
        assert "/ranker/rank" not in src and "/ranker/new" not in src
    # the view ranks through the store, which ranks with RankerMath
    assert "store.rank(" in VIEW and "RankerMath.rank(" in STORE
    assert "isn't reachable" not in VIEW and "Asking your Mac" not in VIEW


def test_every_write_to_the_mac_queues():
    """Each call the tab makes to the Mac is a `mutate` (queued offline) or a read."""
    for name in ("setRankerNumbers", "setRankerTable", "saveRankerPreset", "deleteRankerPreset",
                 "putRankerHistory", "setRankerHistoryArchived", "deleteRankerHistory"):
        body = API.split(f"func {name}(", 1)[1].split("\n    }\n", 1)[0]
        assert "mutate(" in body, name


def _func(src: str, name: str) -> str:
    return src.split(f"func {name}(", 1)[1].split("\n    }\n", 1)[0]


def test_the_phone_keeps_past_searches_and_syncs_them():
    """Gil, 2026-10-12: past searches kept, to reopen, archive or delete — on
    the phone too, in step with the Mac."""
    # a finished search is filed: New search, and a different table
    assert "fileCurrent(api: api)" in _func(STORE, "newSearch")
    assert "fileCurrent(api: api)" in _func(STORE, "readTable")
    # filed whole to the Mac, reopened, archived and deleted through queued writes
    assert "putRankerHistory" in _func(STORE, "fileCurrent")
    assert "setRankerHistoryArchived" in _func(STORE, "setArchived")
    delete = _func(STORE, "deleteHistory")
    assert "deleteRankerHistory" in delete and "deletedHistory" in delete
    # what the Mac deleted goes here too, and nothing deleted is pulled back
    sync = _func(STORE, "syncHistory")
    assert "gone.contains" in sync and "!mine.contains" in sync
    # it survives a restart
    assert 'o["history"]' in STORE and 'o["deleted_history"]' in STORE
    # the sheet: open, archive and delete — the last asked first
    assert "struct RankerHistorySheet" in VIEW and "confirmationDialog" in VIEW
    assert 'accessibilityIdentifier("ranker-history")' in VIEW

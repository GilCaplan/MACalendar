"""The search bar in Settings finds every page (Gil, 2026-10-29: "in settings
add a search bar to find things").

The index (`SettingsSearch.index` in SettingsView.swift) is written by hand,
so it drifts the day a page is added without it. These hold it to the
Settings root: every row the root opens has an entry, every entry opens a
page the root has, and every page in the index has somewhere to go. What a
search FINDS is driven in the simulator by `SettingsSearchUITests`.
"""
from __future__ import annotations

import re

from tests.unit._ios_sources import ios_source

SRC = ios_source("SettingsView.swift")


def _index_titles() -> "set[str]":
    block = SRC[SRC.index("static let index"):SRC.index("static func hits")]
    return set(re.findall(r'\("([^"]+)", \.', block))


def _page_names() -> "dict[str, str]":
    block = SRC[SRC.index("var name: String"):SRC.index("var icon: String")]
    return dict(re.findall(r"case \.(\w+): return \"([^\"]+)\"", block))


def test_every_row_on_the_settings_root_can_be_found():
    root = SRC[SRC.index("private var mainList"):SRC.index("// MARK: - Search")]
    rows = re.findall(r'row\("([^"]+)"', root)
    assert rows, "found no rows on the Settings root"
    findable = _index_titles() | set(_page_names().values())
    missing = [r for r in rows if r not in findable]
    assert not missing, f"Settings rows the search cannot find: {missing}"


def test_every_page_in_the_index_opens_something():
    switch = SRC[SRC.index("private func destination"):SRC.index("// MARK: - The pages")]
    for case in _page_names():
        assert f"case .{case}:" in switch, f"search page .{case} has no destination"


def test_the_search_bar_is_always_shown():
    assert ".navigationBarDrawer(displayMode: .always)" in SRC

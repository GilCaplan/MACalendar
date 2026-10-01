"""The Mac's magic-words helper is rebuilt when a Swift file it is built from
changes — it used to be built only when missing, so a change to the drawings
or the settings window never reached a Mac that already had a binary."""
from __future__ import annotations

import os

from assistant import magic_words


def _tree(tmp_path):
    here = tmp_path / "mac" / "MagicWords"
    egg = tmp_path / "MACalendar-iOS" / "MACalendar-iOS" / "EasterEgg"
    here.mkdir(parents=True)
    egg.mkdir(parents=True)
    (here / "build.sh").write_text('swiftc "$EGG/EggArt.swift" "$HERE/MacMain.swift"\n')
    (here / "MacMain.swift").write_text("")
    (egg / "EggArt.swift").write_text("")
    (egg / "EggSettingsView.swift").write_text("")       # the phone's own screen, not compiled here
    (here / "build").mkdir()
    binary = here / "build" / "MACalendarMagic"
    binary.write_text("")
    for p in [here / "build.sh", here / "MacMain.swift", egg / "EggArt.swift", egg / "EggSettingsView.swift"]:
        os.utime(p, (1000, 1000))
    os.utime(binary, (2000, 2000))
    return here, egg, binary


def test_a_changed_shared_file_makes_the_helper_stale(tmp_path, monkeypatch):
    here, egg, binary = _tree(tmp_path)
    monkeypatch.setattr(magic_words, "HERE", here)
    monkeypatch.setattr(magic_words, "BINARY", binary)
    assert not magic_words._stale()
    os.utime(egg / "EggSettingsView.swift", (3000, 3000))  # not in build.sh: no rebuild
    assert not magic_words._stale()
    os.utime(egg / "EggArt.swift", (3000, 3000))
    assert magic_words._stale()


def test_a_changed_mac_file_or_a_missing_binary_makes_it_stale(tmp_path, monkeypatch):
    here, _, binary = _tree(tmp_path)
    monkeypatch.setattr(magic_words, "HERE", here)
    monkeypatch.setattr(magic_words, "BINARY", binary)
    os.utime(here / "MacMain.swift", (3000, 3000))
    assert magic_words._stale()
    binary.unlink()
    assert magic_words._stale()

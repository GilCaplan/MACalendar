"""The phone peels the same stop words the Mac does (Gil, 2026-10-12: "when it
transcribes and then has word execute, it doesn't cut it off like it does with
the laptop").

The Mac's list is `assistant/engine/ingest/repair.py` `_BUILTIN_STOP_PATTERNS`;
the phone's is `LocalEngine.stopPatterns`. This reads both and holds them equal,
so a word added on one side and not the other goes red here — on any machine.
How the phone USES them (peeled before reading, Apple's model included) is
checked by `test_phone_engine.py` on a Mac with swiftc.
"""

from __future__ import annotations

import re

from assistant.engine.ingest import repair
from tests.unit._ios_sources import ios_source


def _swift_stop_patterns() -> list[str]:
    src = ios_source("LocalEngine.swift")
    block = src.split("static let stopPatterns = [", 1)[1].split("]\n", 1)[0]
    return re.findall(r'#"(.*?)"#', block)


def test_the_phone_peels_exactly_the_macs_stop_words():
    assert _swift_stop_patterns() == repair._BUILTIN_STOP_PATTERNS


def test_the_phone_peels_them_before_either_reader_reads():
    engine = ios_source("LocalEngine.swift")
    read = engine.split("static func read(", 1)[1].split("\n    }\n", 1)[0]
    assert "peelStopWords(said)" in read
    offline = ios_source("OfflineReader.swift")
    model = offline.split("static func read(", 1)[1]
    assert model.index("peelStopWords(text)") < model.index("guard !said.isEmpty")
    # peeled until nothing more comes off, like _peel_stop_keywords
    assert "while cur != prev" in engine.split("static func peelStopWords(", 1)[1]


def test_what_the_phone_heard_is_shown_and_sent_without_it():
    button = ios_source("VoiceButton.swift")
    assert "LocalEngine.peelStopWords(\n                await recorder.heardText(" in button

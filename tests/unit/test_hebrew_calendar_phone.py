"""The phone's Jewish calendar and Shabbat times agree with the Mac's.

A phone with no Mac (DEVQA Q85) computes holidays and Shabbat / yom tov
windows itself (`MACalendar-iOS/Engine/HebrewCalendar.swift`), ported from
`assistant/hebrew_calendar.py` (pyluach) and `assistant/observance.py`
(astral). The Mac's code is the reference: every holiday over seven civil
years, Israel and the diaspora, must match field for field; every window over
three years must match its days and names exactly and its candle-lighting and
nightfall labels to the minute — a minute is the whole point of the line.

macOS only: it compiles the port with `swiftc` against Foundation.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import platform
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IOS = ROOT / "MACalendar-iOS"

pytestmark = pytest.mark.skipif(platform.system() != "Darwin" or not shutil.which("swiftc"),
                                reason="needs swiftc and Apple's Foundation")


@pytest.fixture(scope="module")
def phone(tmp_path_factory):
    exe = tmp_path_factory.mktemp("hebrew") / "hebrew_cli"
    subprocess.run(["swiftc", "-parse-as-library", "-D", "HEBREW_CLI",
                    str(IOS / "Tools/hebrew_cli_models.swift"),
                    str(IOS / "MACalendar-iOS/Engine/HebrewCalendar.swift"),
                    str(IOS / "Tools/hebrew_cli.swift"), "-o", str(exe)], check=True, capture_output=True)

    def ask(lines: list[str]) -> list:
        out = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True)
        return [json.loads(x) for x in out.stdout.splitlines()]
    return ask


@pytest.mark.parametrize("israel", [True, False])
def test_every_holiday_over_seven_years(phone, israel):
    from assistant.hebrew_calendar import enumerate_holidays
    years = range(2024, 2031)
    asks = [f"holidays {y}-01-01 {y}-12-31 {int(israel)}" for y in years]
    for y, got in zip(years, phone(asks)):
        want = [{"name_en": h.name_en, "name_he": h.name_he, "category": h.category,
                 "gregorian_erev_start": h.gregorian_erev_start.isoformat(),
                 "gregorian_end": h.gregorian_end.isoformat()}
                for h in enumerate_holidays(datetime.date(y, 1, 1), datetime.date(y, 12, 31), israel)]
        assert len(want) > 18
        assert got == want, f"{y}: first difference {next(((a, b) for a, b in zip(got, want) if a != b), (len(got), len(want)))}"


def test_every_shabbat_and_yom_tov_window_to_the_minute(phone):
    from assistant.observance import ObservanceSettings, holy_windows
    s = ObservanceSettings()                       # Jerusalem, 18 minutes, 8.5 degrees: the phone's default too
    starts = [datetime.date(2025, 1, 1) + datetime.timedelta(days=30 * k) for k in range(37)]
    asks = [f"windows {d.isoformat()} {(d + datetime.timedelta(days=29)).isoformat()} 1" for d in starts]
    n = 0
    for d, got in zip(starts, phone(asks)):
        want = [w.as_dict() for w in holy_windows(d, d + datetime.timedelta(days=29), s, israel=True)]
        assert [(g["days"], g["name"], g["start_name"], g["end_name"]) for g in got] == \
               [(w["days"], w["name"], w["start_name"], w["end_name"]) for w in want], d
        assert [(g["start_label"], g["end_label"]) for g in got] == \
               [(w["start_label"], w["end_label"]) for w in want], d
        n += len(want)
    assert n > 150                                 # three years of Shabbatot and yamim tovim

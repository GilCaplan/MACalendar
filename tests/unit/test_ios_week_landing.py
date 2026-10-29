"""Where the phone's sideways Week lands (Settings ▸ Appearance ▸ "Week opens on").

It always opened on the week's first column, often an empty Sunday (Gil,
2026-10-29: "when it scrolls all the way to the left, to like Sunday, you
don't really see anything"). The default now lands on the days with events,
nearest today; "start" and "end" are the other two choices. CI has no Swift
toolchain, so this mirrors CalendarPrefs.weekLanding and reads the source.
"""
from pathlib import Path

IOS = Path(__file__).resolve().parents[2] / "MACalendar-iOS" / "MACalendar-iOS"
PREFS = (IOS / "Settings" / "AppSettings.swift").read_text()
WEEK = (IOS / "Features" / "Calendar" / "WeekView.swift").read_text()
SETTINGS_VIEW = (IOS / "Views" / "SettingsView.swift").read_text()


def landing(mode, counts, today, visible=3):
    """CalendarPrefs.weekLanding, line for line."""
    last = max(0, len(counts) - max(1, visible))
    if mode == "start":
        return 0
    if mode == "end":
        return last
    w = max(1, visible)
    load = lambda s: sum(counts[s:s + w])
    holds = lambda s, t: s <= t < s + w
    starts = list(range(last + 1))
    if today is not None and 0 <= today < len(counts) and counts[today] > 0:
        starts = [s for s in starts if holds(s, today)]
    most = max(map(load, starts))
    if most <= 0:
        return min(last, max(0, today - 1)) if today is not None else 0

    def key(s):
        if today is None:
            return (0, 0, s)
        away = 0 if holds(s, today) else min(abs(s - today), abs(s + w - 1 - today))
        return (away, abs(s - (today - 1)), s)
    return min((s for s in starts if load(s) == most), key=key)


def test_an_empty_sunday_is_not_where_it_opens():
    # Sun empty, events Wed–Fri, today Monday: land on Wed, not Sun.
    assert landing("busy", [0, 0, 0, 2, 1, 1, 0], today=1) == 3


def test_today_with_events_stays_in_view_with_the_day_before():
    # Today (Thu) has one event, Sun has five: today's stretch wins, and it
    # opens with Wednesday on the left for context.
    assert landing("busy", [5, 0, 0, 0, 1, 0, 0], today=4) == 3


def test_ties_go_to_the_stretch_nearest_today():
    # Two equally busy ends, today Friday with nothing booked: the late one.
    assert landing("busy", [1, 0, 0, 0, 0, 0, 1], today=5) == 4


def test_another_week_lands_on_its_busiest_stretch():
    assert landing("busy", [0, 1, 0, 3, 2, 0, 0], today=None) == 2
    assert landing("busy", [0, 0, 0, 0, 0, 0, 0], today=None) == 0


def test_an_empty_week_keeps_the_old_landing():
    # Nothing booked: today with the day before it, as before.
    assert landing("busy", [0] * 7, today=3) == 2
    assert landing("busy", [0] * 7, today=6) == 4


def test_start_and_end():
    assert landing("start", [0, 0, 0, 0, 0, 0, 9], today=6) == 0
    assert landing("end", [9, 0, 0, 0, 0, 0, 0], today=0) == 4


def test_landing_never_leaves_the_week():
    import itertools
    for counts in itertools.product([0, 1], repeat=7):
        for today in [None, *range(7)]:
            for mode in ("busy", "start", "end"):
                i = landing(mode, list(counts), today)
                assert 0 <= i <= 4
                if mode == "busy" and today is not None and counts[today]:
                    assert i <= today < i + 3, (counts, today, i)


def test_swift_matches_the_mirror_and_is_wired():
    assert "static func weekLanding(mode: String, counts: [Int], today: Int?, visible: Int) -> Int" in PREFS
    assert "starts = starts.filter { holds($0, t) }" in PREFS
    assert "return (away, abs(s - (t - 1)), s)" in PREFS
    assert '?? "busy"' in PREFS, "busiest days must be the default"
    assert "CalendarPrefs.weekLanding(mode: settings.weekScrollStart" in WEEK
    assert ".onAppear { land(days" in WEEK
    assert "if weekDays.first != landedWeek" in WEEK
    assert "$settings.weekScrollStart" in SETTINGS_VIEW
    for tag in ('.tag("busy")', '.tag("start")', '.tag("end")'):
        assert tag in SETTINGS_VIEW

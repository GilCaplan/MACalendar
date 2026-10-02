"""The phone's own reader (`MACalendar-iOS/Engine/LocalEngine.swift`, DEVQA Q85).

With no Mac, this is what a spoken or typed command means. These pin the
rulings it carries over from the Mac (Q25/Q26/Q47/Q50/Q57/Q61, the bare-hour
convention) and the one thing it must never do: act on a guess. The broad
measurement is `scripts/phone_engine_board.py` (FastRule TRAIN rows and the
HWU-64 real speech outside the sealed 300).

macOS only: it compiles the engine with `swiftc` against Foundation.
"""
from __future__ import annotations

import json
import pathlib
import platform
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
IOS = ROOT / "MACalendar-iOS"
NOW = "2026-10-02T10:00:00"          # a Friday

pytestmark = pytest.mark.skipif(platform.system() != "Darwin" or not shutil.which("swiftc"),
                                reason="needs swiftc and Apple's Foundation")


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    exe = tmp_path_factory.mktemp("engine") / "local_engine_cli"
    subprocess.run(["swiftc", "-parse-as-library", str(IOS / "MACalendar-iOS/Engine/LocalEngine.swift"),
                    str(IOS / "Tools/local_engine_cli.swift"), "-o", str(exe)], check=True, capture_output=True)

    def read(text: str, rows=None) -> list[dict]:
        req = {"text": text, "now": NOW}
        if rows is not None:
            req["rows"] = rows
        out = subprocess.run([str(exe)], input=json.dumps(req) + "\n", capture_output=True, text=True, check=True)
        return json.loads(out.stdout)["actions"]
    return read


def one(actions):
    assert len(actions) == 1, actions
    return actions[0]


@pytest.mark.parametrize("said, kind, title, date, start", [
    ("dentist tomorrow at 3", "event", "dentist", "2026-10-03", "15:00"),          # bare hour 1-8 is PM
    ("gym at 7 in the morning", "event", "gym", "2026-10-02", "07:00"),
    ("lunch with Dana on monday", "event", "lunch with Dana", "2026-10-05", "09:00"),   # Q47: a person on a day
    ("remind me to water the plants tonight", "todo", "water the plants", "2026-10-02", None),   # Q47: not a clock
    ("buy milk", "todo", "buy milk", None, None),                                   # no time: a to-do
    ("pay rent friday", "todo", "pay rent", "2026-10-09", None),                    # Q26: a bare day decides nothing
    ("i need to schedule a haircut", "todo", "schedule a haircut", None, None),
    ("book a meeting with Jamie in two days at 14:00 to discuss the budget", "event",
     "meeting with Jamie about the budget", "2026-10-04", "14:00"),                 # Q56
])
def test_what_a_create_means(engine, said, kind, title, date, start):
    a = one(engine(said))
    assert (a["op"], a["kind"], a["title"]) == ("create", kind, title)
    assert a.get("date") == date and a.get("start") == start


def test_a_series_gets_its_cadence_and_the_default_end(engine):
    a = one(engine("standup every weekday at 9:30"))
    assert a["recurrence"] == "weekly" and a["recur_days"] == ["monday", "tuesday", "wednesday", "thursday", "friday"]
    assert a["recurrence_end"] == "2026-11-27"                                     # Q57: weekly, 8 weeks
    b = one(engine("remind me to feed the cat once a week until this coming saturday"))
    assert b["kind"] == "event" and b["recurrence"] == "weekly"                    # Q61
    assert b["recurrence_end"] == "2026-10-02"                                     # "until" excludes its day


def test_a_call_to_a_role_is_an_event_and_a_todo(engine):
    a = one(engine("call the plumber tomorrow"))
    assert a["kind"] == "event" and a["start"] == "09:00" and a["linked_todo"]       # Q50
    b = one(engine("call Mom tomorrow"))
    assert b["kind"] == "event" and not b["linked_todo"]


def test_two_asks_in_one_breath(engine):
    acts = engine("add milk to my shopping list and then book the dentist tuesday at 4")
    assert [(a["op"], a["kind"]) for a in acts] == [("create", "todo"), ("create", "event")]
    assert len(engine("buy milk and eggs")) == 1


ROWS = [{"id": 1, "kind": "event", "title": "dentist appointment", "date": "2026-10-03", "start": "15:00"},
        {"id": 2, "kind": "event", "title": "team meeting", "date": "2026-10-05", "start": "10:00"},
        {"id": 3, "kind": "event", "title": "team meeting", "date": "2026-10-12", "start": "10:00"},
        {"id": 4, "kind": "todo", "title": "buy milk", "date": "", "start": ""}]


def test_an_edit_names_one_row_or_does_nothing(engine):
    assert one(engine("delete the dentist", ROWS))["match"] == 1
    many = one(engine("cancel the team meeting", ROWS))
    assert many.get("match_many") == [2, 3]                       # ambiguous: ask, never guess
    assert one(engine("cancel the team meeting on monday", ROWS))["match"] == 2
    gone = one(engine("delete the yoga class", ROWS))
    assert gone["op"] == "delete" and gone.get("match") is None   # nothing to point at: say so
    vague = one(engine("delete this reminder", ROWS))
    assert vague["target"] == "" and vague.get("match") is None


def test_moves_ticks_and_questions(engine):
    m = one(engine("move the dentist to monday at 4", ROWS))
    assert (m["op"], m["date"], m["start"], m["match"]) == ("update", "2026-10-05", "16:00", 1)
    p = one(engine("push the team meeting on monday back an hour", ROWS))
    assert p["shift_minutes"] == 60
    t = one(engine("mark buy milk as done", ROWS))
    assert (t["op"], t["match"]) == ("complete", 4)
    q = one(engine("what do i have tomorrow"))
    assert (q["op"], q["date"]) == ("query", "2026-10-03")
    assert one(engine("when is my next appointment with Dr. Smith?"))["op"] == "query"

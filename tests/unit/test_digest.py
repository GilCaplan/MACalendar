"""The day panel — one summary of today, not a stream of imminent things.

Gil, 2026-09-11: *"I want it to be more of a panel that nicely shows what i
have today and not when something is about to pop up… it's on or off and it
shows in a nice manner the event calendar and tasks for today."*

Two things are pinned here that are easy to lose later:

  * the WORDING is server-side. `build_digest` returns the finished title and
    body, not just rows, so the phone's notification and the Mac's banner say
    the same thing. The moment a client formats its own, the two drift — one
    learns about all-day events and the other doesn't.
  * the pre-event reminders are DORMANT, not deleted. `reminder_minutes` is a
    frozen engine contract and "with a 15 minute reminder" still parses and
    stores; `pre_event` off just stops it firing.
"""

from __future__ import annotations

import datetime

import pytest

from assistant import notify
from assistant.config import NotificationsConfig

DAY = datetime.date(2026, 9, 10)          # a Thursday — no observance in play


class _FixedDate(datetime.date):
    """`date.today()` pinned to DAY — an undated task is outstanding TODAY, so
    which day "today" is decides the answer."""

    @classmethod
    def today(cls):
        return DAY


class _DB:
    """Just the two accessors `build_digest` uses."""

    def __init__(self, events=(), todos=()):
        self._events, self._todos = list(events), list(todos)

    def get_events_for_day(self, day):
        return [e for e in self._events if e.get("date") == day.isoformat()]

    def get_todos(self, list_name=None, include_completed=False, tag=None):
        return list(self._todos)


def _event(title, start=None, **kw):
    return dict(id=kw.pop("id", 1), title=title, date=DAY.isoformat(),
                start_time=start, end_time=None, category="Work", **kw)


def _todo(title, **kw):
    row = dict(id=1, title=title, list_name="today", tags=[], due_date=None)
    row.update(kw)
    return row


@pytest.fixture(autouse=True)
def today_is_day(monkeypatch):
    """`date.today()` pinned to DAY for every test here.

    An UNDATED task is outstanding *today*, so which day "today" is decides
    what the panel contains — and a suite that ran green in September and red
    in December would be worse than useless.
    """
    monkeypatch.setattr(notify.datetime, "date", _FixedDate)


@pytest.fixture
def cfg():
    return NotificationsConfig()


# --- when it fires --------------------------------------------------------

def test_it_is_on_by_default_and_fires_at_the_configured_time(cfg):
    at, why = notify.digest_verdict(DAY, cfg)
    assert at == "2026-09-10T07:00" and why is None


def test_off_is_off(cfg):
    cfg.daily_digest = False
    assert notify.digest_verdict(DAY, cfg) == (None, None)


def test_the_master_switch_still_governs_it(cfg):
    cfg.enabled = False
    assert notify.digest_verdict(DAY, cfg) == (None, None)


def test_an_unreadable_time_does_not_take_the_notifier_down(cfg):
    """Read on a daemon thread — a typo in config.yaml must not raise."""
    cfg.digest_time = "half seven"
    assert notify.digest_time(cfg) is None
    assert notify.digest_verdict(DAY, cfg) == (None, None)


def test_it_holds_through_shabbat(cfg, monkeypatch):
    """DEVQA Q6's ruling applies whatever the notification is summarising: a
    07:00 panel on Shabbat morning is still a notification on Shabbat."""
    monkeypatch.setattr(notify, "quiet_window_end",
                        lambda moment: datetime.datetime(2026, 9, 12, 19, 25))
    import assistant.observance as ob
    monkeypatch.setattr(ob, "is_enabled", lambda: True)
    monkeypatch.setattr(ob, "is_yom_tov", lambda d: False)

    at, why = notify.digest_verdict(datetime.date(2026, 9, 12), cfg)
    assert at is None and why == "shabbat"


def test_no_solar_data_means_it_still_fires(cfg, monkeypatch):
    """Fails OPEN, like every other observance decision in this module."""
    monkeypatch.setattr(notify, "quiet_window_end", lambda moment: None)
    import assistant.observance as ob
    monkeypatch.setattr(ob, "is_enabled", lambda: True)
    at, why = notify.digest_verdict(DAY, cfg)
    assert at is not None and why is None


# --- what it says ---------------------------------------------------------

def test_the_day_reads_in_the_order_it_happens(cfg):
    db = _DB(events=[_event("standup", "09:30", id=2),
                     _event("Yom Iyun", None, id=1),      # all day
                     _event("dentist", "14:00", id=3)],
             todos=[_todo("buy milk")])
    d = notify.build_digest(DAY, cfg, db)

    assert d["body"].splitlines() == [
        "All day  Yom Iyun",
        "9:30 AM  standup",
        "2:00 PM  dentist",
        "—",
        "buy milk",
    ]
    assert [e["title"] for e in d["events"]] == ["Yom Iyun", "standup", "dentist"]


def test_the_title_counts_without_being_opened(cfg):
    db = _DB(events=[_event("standup", "09:30")], todos=[_todo("buy milk"),
                                                         _todo("call mum", id=2)])
    d = notify.build_digest(DAY, cfg, db)
    assert d["title"] == "Thursday 10 September — 1 event · 2 tasks"


def test_an_empty_day_says_so(cfg):
    d = notify.build_digest(DAY, cfg, _DB())
    assert d["title"] == "Thursday 10 September — nothing on"
    assert d["body"] == ""


def test_only_one_kind_means_no_separator(cfg):
    d = notify.build_digest(DAY, cfg, _DB(events=[_event("standup", "09:30")]))
    assert "—" not in d["body"] and d["title"].endswith("1 event")


def test_a_task_due_another_day_is_not_todays_business(cfg):
    db = _DB(todos=[_todo("buy milk"),
                    _todo("file taxes", id=2, due_date="2026-12-01")])
    d = notify.build_digest(DAY, cfg, db)
    assert [t["title"] for t in d["tasks"]] == ["buy milk"]


def test_an_undated_task_is_outstanding_today_and_nowhere_else(cfg):
    """It is on the list, not scheduled. Carrying it onto every future day made
    a `?date=` a week out claim tasks that are not that day's business."""
    db = _DB(todos=[_todo("buy milk"),
                    _todo("file taxes", id=2, due_date="2026-12-01")])

    assert [t["title"] for t in notify.build_digest(DAY, cfg, db)["tasks"]] \
        == ["buy milk"]
    later = notify.build_digest(datetime.date(2026, 12, 1), cfg, db)
    assert [t["title"] for t in later["tasks"]] == ["file taxes"]


def test_a_suppressed_panel_still_reports_the_day(cfg):
    """Suppressed is about DELIVERY. The content is still the answer to "what
    do I have", which is what the in-app surface shows."""
    cfg.daily_digest = False
    d = notify.build_digest(DAY, cfg, _DB(events=[_event("standup", "09:30")]))
    assert d["enabled"] is False and d["fires_at"] is None
    assert "standup" in d["body"]


# --- the pre-event half is dormant, not gone ------------------------------

def test_nothing_pops_up_before_an_event_by_default(cfg):
    """The behaviour Gil asked to stop."""
    ev = _event("standup", "09:30")
    ev["reminder_minutes"] = 15
    assert notify.notify_verdict(ev, cfg) == (None, None)


def test_turning_pre_event_back_on_restores_it_whole(cfg):
    """Dormant, not deleted — `reminder_minutes` is still a frozen engine
    contract and the voice phrase still stores one."""
    cfg.pre_event = True
    ev = _event("standup", "09:30")
    ev["reminder_minutes"] = 15
    at, why = notify.notify_verdict(ev, cfg)
    assert at == "2026-09-10T09:15" and why is None


# --- the Mac notifier fires it ---------------------------------------------

class _LogDB(_DB):
    """A _DB that also records reminder_log writes, like the real one."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.logged = []

    def log_reminder(self, event_id, fires_at, outcome):
        key = (event_id, fires_at)
        if key in [(e, f) for e, f, _o in self.logged]:
            return False                      # the real UNIQUE constraint
        self.logged.append((event_id, fires_at, outcome))
        return True


def _at(h, m=0):
    return datetime.datetime.combine(DAY, datetime.time(h, m))


def test_the_notifier_delivers_the_panel_once(cfg, monkeypatch):
    from assistant import notifier

    sent = []
    monkeypatch.setattr(notifier, "_deliver_digest",
                        lambda panel, c, v: sent.append(panel))
    db = _LogDB(events=[_event("standup", "09:30")])

    notifier._tick(db, cfg, now=_at(7, 1), last=_at(6, 59))
    assert len(sent) == 1 and "standup" in sent[0]["body"]

    # A second tick the same day must not send it again — the real guard is
    # reminder_log's UNIQUE (event_id, fires_at), reused rather than a new
    # table, with a negative sentinel id that no real event can collide with.
    notifier._tick(db, cfg, now=_at(7, 2), last=_at(7, 1))
    assert len(sent) == 1
    assert db.logged[0][0] == notifier.DIGEST_KEY < 0


def test_a_panel_that_arrives_at_four_pm_is_not_worth_sending(cfg, monkeypatch):
    """Unlike a pre-event reminder, which is still about something that has
    not happened yet, a summary of the day that turns up in the afternoon is
    just noise — and less noise was the point of the change."""
    from assistant import notifier

    sent = []
    monkeypatch.setattr(notifier, "_deliver_digest",
                        lambda panel, c, v: sent.append(panel))
    db = _LogDB(events=[_event("standup", "09:30")])

    notifier._tick(db, cfg, now=_at(16, 0), last=_at(6, 0))
    assert sent == []
    assert db.logged and db.logged[-1][2] == "missed"


def test_pre_event_banners_stay_off_while_the_panel_fires(cfg, monkeypatch):
    from assistant import notifier

    considered = []
    monkeypatch.setattr(notifier, "_deliver_digest", lambda *a: None)
    monkeypatch.setattr(notifier, "_consider",
                        lambda *a, **k: considered.append(a))
    ev = _event("standup", "09:30")
    ev["reminder_minutes"] = 15
    notifier._tick(_LogDB(events=[ev]), cfg, now=_at(7, 1), last=_at(6, 59))
    assert considered == [], "a pre-event banner fired with pre_event off"


# --- the endpoint ----------------------------------------------------------

def test_the_digest_endpoint_serves_the_panel():
    from assistant.api.server import create_app
    from assistant.db import get_db

    app = create_app()
    app.config["TESTING"] = True
    db = get_db()
    eid = db.create_event_from_dict({
        "title": "Standup", "date": "2026-09-10",
        "start_time": "09:30", "end_time": "09:45"})
    try:
        with app.test_client() as c:
            d = c.get("/digest?date=2026-09-10").get_json()
            assert d["date"] == "2026-09-10"
            assert "Standup" in d["body"]
            assert any(e["title"] == "Standup" for e in d["events"])
            assert "tasks" in d and "fires_at" in d

            assert c.get("/digest?date=not-a-date").status_code == 400
    finally:
        db.delete_event(eid)


def test_the_phone_gets_a_week_of_panels_in_one_answer():
    """The phone SCHEDULES ahead — it cannot ask at 06:59 for a 07:00 panel.

    So /digest/upcoming hands it the next several days at once, today first,
    and refuses to be talked into an unbounded range.
    """
    import datetime as _dt

    from assistant.api.server import create_app

    app = create_app()
    app.config["TESTING"] = True
    today = _dt.date.today()

    with app.test_client() as c:
        days = c.get("/digest/upcoming").get_json()["days"]
        assert len(days) == 7, "the default horizon is a week"
        assert days[0]["date"] == today.isoformat(), "today leads"
        assert [d["date"] for d in days] == [
            (today + _dt.timedelta(days=i)).isoformat() for i in range(7)]
        # Every day is a whole panel, wording included — the phone formats
        # nothing of its own.
        assert all({"title", "body", "fires_at", "enabled"} <= set(d) for d in days)

        assert len(c.get("/digest/upcoming?days=2").get_json()["days"]) == 2
        # Clamped at both ends rather than trusted.
        assert len(c.get("/digest/upcoming?days=99").get_json()["days"]) == 7
        assert len(c.get("/digest/upcoming?days=0").get_json()["days"]) == 1
        assert c.get("/digest/upcoming?days=lots").status_code == 400

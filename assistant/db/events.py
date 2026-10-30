"""Events: create (single and repeating), read, update, delete, reminders."""

from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import List, Optional

from assistant.actions.calendar.intent import CalendarIntent
from assistant.common.wordlists import WEEKDAY_INDEX as _WEEKDAY_NUM
from assistant.db.colours import _AUTO_COLORS, auto_category_and_color
from assistant.db.common import _memory_feedback, _utcnow_iso
from assistant.db.observance import _skip_for_observance, _skip_user_day
from assistant.db.schema import TWO_WAY_SOURCES
from assistant.db.series import _next_date, _SeriesSeed

logger = logging.getLogger(__name__)


class EventsMixin:
    """Events: create (single and repeating), read, update, delete, reminders."""

    def recategorise_all(self, force: bool = False) -> int:
        """(Re)assign category + colour for existing events. Without force, only events
        that still carry the default colour / no category are touched."""
        n = 0
        with self._conn() as conn:
            rows = conn.execute("SELECT id, title, date, start_time, attendees, location, description, color, category FROM events ORDER BY date, start_time").fetchall()
            for r in rows:
                rid, title, date, st, att, loc, desc, color, cat = r
                if not force and cat and color not in _AUTO_COLORS:
                    continue
                new_cat, new_color = auto_category_and_color(conn, title, date, st, att, loc, desc,
                                                             None if (force or color in _AUTO_COLORS) else color,
                                                             None if force else (cat or None), exclude_id=rid)
                conn.execute("UPDATE events SET category = ?, color = ? WHERE id = ?", (new_cat, new_color, rid))
                n += 1
        return n

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_event(self, intent: CalendarIntent, color: "str | None" = None) -> int:
        """Insert a single event (or first instance of a series). Returns new row id.

        `color=None` means CHOOSE BY CATEGORY, and it is the default because
        that is what almost every caller wants — only a user who actually
        picked a swatch has a colour to honour. It used to default to the
        literal `"#0078d4"`, which worked only for as long as that string
        stayed the app's idea of "no choice"; see `_AUTO_COLORS`.
        """
        recurrence = getattr(intent, "recurrence", None) or ""
        recur_until = getattr(intent, "recur_until", None) or ""

        with self._conn() as conn:
            category, color = auto_category_and_color(
                conn, intent.title, intent.date, intent.start_time, intent.attendees,
                intent.location or "", intent.description or "", color)
            cur = conn.execute(
                """
                INSERT INTO events
                    (title, date, start_time, end_time, attendees, location, description,
                     color, created_at, updated_at, series_id, recurrence, recurrence_end,
                     category, reminder_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.title,
                    intent.date,
                    intent.start_time,
                    intent.end_time,
                    ", ".join(intent.attendees),
                    intent.location or "",
                    intent.description or "",
                    color,
                    datetime.datetime.now().isoformat(),
                    # Stamped at creation, not only on the first edit, so a client
                    # can quote it back for the conflict check on PATCH.
                    _utcnow_iso(),
                    None,       # series_id set below if recurring
                    recurrence,
                    recur_until,
                    category,
                    getattr(intent, "reminder_minutes", None),
                ),
            )
            first_id = cur.lastrowid

            if recurrence:
                # Create all subsequent instances and link them with series_id
                self._create_series_instances(
                    conn, first_id, intent, recurrence, recur_until, color, category
                )
                # The series' weekdays, on every row of it (2026-09-24). The
                # column has existed since recur_days did, is served to the
                # clients, and was never written: "every tuesday and thursday"
                # expanded onto both days and then recorded '' — so anything
                # that later reads the series back saw a one-day weekly series.
                days = [d for d in (getattr(intent, "recur_days", None) or [])
                        if d in _WEEKDAY_NUM]
                if recurrence == "weekly" and len(days) > 1:
                    row = conn.execute("SELECT series_id FROM events WHERE id = ?",
                                       (first_id,)).fetchone()
                    sid = row[0] if row and row[0] is not None else first_id
                    conn.execute("UPDATE events SET recur_days = ? WHERE id = ? OR series_id = ?",
                                 (",".join(days), first_id, sid))

        return first_id

    def _create_series_instances(
        self,
        conn: sqlite3.Connection,
        first_id: int,
        intent: CalendarIntent,
        recurrence: str,
        recur_until: str,
        color: str,
        category: str = "",
    ) -> None:
        """Generate and insert all recurrence instances; also back-fill series_id on first row.

        `category` is the one the FIRST row resolved to, passed in rather than
        re-derived: every instance is the same event with the same title, so
        re-classifying per instance could only disagree with itself — and the
        instances used to get no category at all (2026-09-10).
        """
        end_date = (
            datetime.date.fromisoformat(recur_until)
            if recur_until
            else datetime.date.fromisoformat(intent.date) + datetime.timedelta(days=365)
        )

        # Back-fill series_id on the first (already inserted) row
        conn.execute("UPDATE events SET series_id = ? WHERE id = ?", (first_id, first_id))

        current = datetime.date.fromisoformat(intent.date)
        anchor_day = current.day  # original day-of-month; see _next_date docstring

        # A series whose first event is itself on Shabbat or yom tov was put
        # there deliberately — a Saturday shiur, a monthly review that happens
        # to fall on the 31st — and skipping every later one would leave a
        # "weekly" series with exactly one event in it. Observance skipping is
        # for series that cross Shabbat incidentally, like "every day at 1900",
        # not for ones anchored to it.
        anchored_on_holy = _skip_for_observance(
            current, intent.start_time, intent.title, intent.description or "",
            user_days=False)
        count = 0
        max_instances = 500  # hard safety cap

        while count < max_instances:
            current = _next_date(current, recurrence, anchor_day=anchor_day,
                                 recur_days=getattr(intent, "recur_days", None))
            if current > end_date:
                break
            # Anchored on Shabbat keeps Shabbat — but not a day the user
            # switched on by hand (DEVQA Q60), which is a date, not a rhythm.
            if (_skip_for_observance(
                    current, intent.start_time, intent.title, intent.description or "")
                    if not anchored_on_holy else _skip_user_day(current)):
                # Shabbat and yom tov are skipped, not shifted: "every day at
                # 1900" through a week that contains Shabbat means the six days
                # it can mean, and moving one to a Sunday would invent a second
                # event that evening. The cadence keeps its rhythm and the
                # calendar keeps the truth.
                #
                # Only days when work is forbidden count — yom_tov_name()
                # returns '' on chol hamoed, Chanukah and Purim, which are
                # ordinary days you can daven and run on.
                continue
            # EVERY INSTANCE CARRIES THE SERIES' CATEGORY (2026-09-10). This
            # insert used to omit `category`, `updated_at` and
            # `reminder_minutes` entirely, so instance 1 of a weekly event was
            # categorised and instances 2..n were not — they came back with an
            # empty category, fell through `color_for()` to Personal's colour,
            # and were invisible to any per-category setting (reminders,
            # notification leads, filters).
            #
            # The category is COPIED from the first row rather than
            # re-classified: it is the same title and the same event, so
            # re-running the classifier per instance could only disagree with
            # itself, and the colour must match the series anyway.
            conn.execute(
                """
                INSERT INTO events
                    (title, date, start_time, end_time, attendees, location, description,
                     color, created_at, updated_at, series_id, recurrence, recurrence_end,
                     category, reminder_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.title,
                    current.isoformat(),
                    intent.start_time,
                    intent.end_time,
                    ", ".join(intent.attendees),
                    intent.location or "",
                    intent.description or "",
                    color,
                    datetime.datetime.now().isoformat(),
                    _utcnow_iso(),
                    first_id,
                    recurrence,
                    recur_until,
                    category,
                    getattr(intent, "reminder_minutes", None),
                ),
            )
            count += 1

    def find_duplicate_event(self, title: str, date: str, start_time: str,
                             recurrence: str = "") -> "dict | None":
        """The event this one would duplicate, or None: same title (case and
        spacing aside), same day, same start, same repeat.

        Gil, 2026-09-28, after one queued command booked the same daily series
        four times: *"reason duplicates if same event were created"*. The
        run-once receipt (`api/receipts.py`) stops the same UPLOAD running
        twice; this stops the same EVENT being written twice however it
        arrives — said twice, typed twice, resent by an older phone. A
        one-off never blocks a series (the repeat must match too), and a
        different time is a different event."""
        # Titles compared by their WORDS: an emoji the title got at commit
        # (TASKS 51, `label/title_emoji`) must not make "walk my dog" said
        # twice look like two different events.
        from assistant.engine.label.title_icons import strip as _words
        want = _words(title).lower()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, title, date, start_time, end_time, recurrence, series_id
                FROM events
                WHERE date = ? AND start_time = ? AND COALESCE(recurrence, '') = ?
                ORDER BY id
                """,
                (date or "", start_time or "", recurrence or ""),
            ).fetchall()
        for row in rows:
            if _words(row["title"]).lower() == want:
                return dict(row)
        return None

    def create_event_from_dict(self, data: dict) -> int:
        """Create an event from a plain dict (used by EventDialog)."""
        recurrence = data.get("recurrence", "")
        recur_until = data.get("recurrence_end", "")

        with self._conn() as conn:
            category, color = auto_category_and_color(
                conn, data["title"], data["date"], data["start_time"], data.get("attendees", ""),
                data.get("location", ""), data.get("description", ""), data.get("color"), data.get("category"))
            data = dict(data, color=color)
            cur = conn.execute(
                """
                INSERT INTO events
                    (title, date, start_time, end_time, attendees, location, description,
                     color, created_at, updated_at, series_id, recurrence, recurrence_end,
                     category, reminder_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["title"],
                    data["date"],
                    data["start_time"],
                    data["end_time"],
                    data.get("attendees", ""),
                    data.get("location", ""),
                    data.get("description", ""),
                    color,
                    datetime.datetime.now().isoformat(),
                    _utcnow_iso(),      # so clients have a version to quote back
                    None,
                    recurrence,
                    recur_until,
                    category,
                    data.get("reminder_minutes"),
                ),
            )
            first_id = cur.lastrowid

            # A category the PERSON chose for a new event, in an editor
            # (`category_explicit`, set only by the event editors) — their
            # label, filed for the learned labeller. Never for a copy, an undo
            # or a restore, which carry a category nobody just chose.
            if data.get("category_explicit") and data.get("category"):
                try:
                    from assistant.actions.calendar import categories as _cat
                    from assistant.engine.label import feedback as _fb
                    guess = _cat.classify(data["title"], data.get("attendees", ""),
                                          data.get("location", ""), data.get("description", ""))
                    _fb.record_category(data["title"], guess, str(data["category"]),
                                        origin=_fb.EXPLICIT)
                except Exception:
                    logger.warning("Could not record the category chosen for %r",
                                   data.get("title"), exc_info=True)

            if recurrence:
                # `category` travels with the colour: the instances used to be
                # generated uncategorised here (the 2026-09-10 fix reached only
                # the voice path's `create_event`), so a series typed into the
                # dialog had one coloured-by-category event and the rest grey.
                self._create_series_instances(
                    conn, first_id, _SeriesSeed(data), recurrence, recur_until,
                    data.get("color", "#0078d4"), category,
                )

        return first_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_events_for_month(self, year: int, month: int) -> List[dict]:
        """Return all events whose date falls in the given month."""
        prefix = f"{year:04d}-{month:02d}"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE date LIKE ? ORDER BY date, start_time",
                (f"{prefix}%",),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_events_for_week(self, start_date: datetime.date) -> List[dict]:
        """Return events for the 7 days starting from start_date."""
        end_date = start_date + datetime.timedelta(days=6)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE date >= ? AND date <= ? ORDER BY date, start_time",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_events_for_day(self, date: datetime.date) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE date = ? ORDER BY start_time",
                (date.isoformat(),),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_events_between(self, start: datetime.date, end: datetime.date) -> List[dict]:
        """Every event from `start` to `end` inclusive, in time order."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start_time",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_event(self, event_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def search_events(self, q: str, limit: int = 50) -> List[dict]:
        """Substring match over title/location/description, soonest first."""
        like = f"%{q}%"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE title LIKE ? OR location LIKE ? "
                "OR description LIKE ? ORDER BY date, start_time LIMIT ?",
                (like, like, like, limit)).fetchall()
        return [dict(r) for r in rows]

    def log_reminder(self, event_id: int, fires_at: str, outcome: str) -> bool:
        """Record a reminder outcome; False if this (event, fire time) is
        already logged — the notifier's re-fire guard across --reload
        restarts."""
        with self._conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO reminder_log (event_id, fires_at, fired_at, outcome) "
                    "VALUES (?, ?, ?, ?)",
                    (event_id, fires_at, datetime.datetime.now().isoformat(), outcome))
                return True
            except sqlite3.IntegrityError:
                return False

    def reminder_logged(self, event_id: int, fires_at: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM reminder_log WHERE event_id = ? AND fires_at = ?",
                (event_id, fires_at)).fetchone()
        return row is not None

    def find_events_at(self, date: str = "", start_time: str = "") -> List[dict]:
        """Events on `date` and/or starting at `start_time`, earliest first.
        Neither given is no filter at all, so it returns [] rather than
        every event."""
        if not date and not start_time:
            return []
        query, params = "SELECT * FROM events WHERE 1=1", []
        if date:
            query += " AND date = ?"
            params.append(date)
        if start_time:
            query += " AND start_time = ?"
            params.append(start_time)
        with self._conn() as conn:
            rows = conn.execute(query + " ORDER BY start_time", params).fetchall()
        return [dict(r) for r in rows]

    def events_nearest(self, day: str) -> List[dict]:
        """Every event, nearest `day` first (then by start time): how the
        assistant ranks candidates when a command names an event."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY ABS(julianday(date) - julianday(?)), start_time",
                (day,)).fetchall()
        return [dict(r) for r in rows]

    def upcoming_event_titles(self, since: str) -> "set[str]":
        """The distinct titles of events on or after `since`."""
        with self._conn() as conn:
            return {r[0] for r in conn.execute(
                "SELECT DISTINCT title FROM events WHERE date >= ?", (since,))}

    def series_first_date(self, series_id: int) -> str:
        """The date a repeating series starts on, "" when it has no rows."""
        with self._conn() as conn:
            row = conn.execute("SELECT MIN(date) FROM events WHERE series_id = ?",
                               (series_id,)).fetchone()
        return (row[0] if row else "") or ""

    def event_titles(self) -> List[str]:
        """Every event's title (non-empty), for mining the user's own words."""
        with self._conn() as conn:
            return [r[0] for r in conn.execute("SELECT title FROM events") if r[0]]

    def event_keys(self) -> "set[tuple]":
        """(title, date, start_time) of every event: what an import checks
        before adding a row, so the same event is not imported twice."""
        with self._conn() as conn:
            return {tuple(r) for r in conn.execute("SELECT title, date, start_time FROM events")}

    def has_events(self) -> bool:
        """Is there any event at all? A cheap existence check, not a match."""
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM events LIMIT 1").fetchone() is not None

    def get_series_events(self, series_id: int) -> List[dict]:
        """Return all events belonging to a recurring series."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE series_id = ? OR id = ? ORDER BY date, start_time",
                (series_id, series_id),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def _is_externally_locked(self, conn: sqlite3.Connection, event_id: int) -> bool:
        """True if *event_id* must not be edited/deleted locally right now.

        ICS-subscribed events are always locked — there is no write path
        behind a webcal/ICS link. Outlook-sourced events are locked unless
        two-way sync is currently on: editing one while it's off would mark
        the row dirty with no push ever happening, silently and permanently
        diverging it from the real Outlook event (see `pull()`'s dirty-row
        preservation logic in calendar_sync/outlook_sync.py).
        """
        row = conn.execute("SELECT source FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return False
        source = row["source"]
        if source == "ics":
            return True
        if source in TWO_WAY_SOURCES:
            two_way = conn.execute(
                "SELECT two_way FROM calendar_sources WHERE kind = ? LIMIT 1", (source,)
            ).fetchone()
            return not (two_way and two_way["two_way"])
        return False

    def is_event_locked(self, event: dict) -> bool:
        """UI-facing check: can *event* (a dict, e.g. from get_event()) be
        edited/deleted right now? See `_is_externally_locked` for policy."""
        source = event.get("source")
        if source == "ics":
            return True
        if source in TWO_WAY_SOURCES:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT two_way FROM calendar_sources WHERE kind = ? LIMIT 1", (source,)
                ).fetchone()
            return not (row and row["two_way"])
        return False

    def _relabelled(self, conn: sqlite3.Connection, event_id: int, updates: dict) -> dict:
        """`updates` plus a refreshed category/colour, when the words changed."""
        if "title" not in updates or "category" in updates:
            return updates
        row = conn.execute(
            "SELECT title, date, start_time, attendees, location, description, color, category "
            "FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return updates
        was = dict(zip(("title", "date", "start_time", "attendees",
                        "location", "description", "color", "category"), row))
        now = {**was, **{k: v for k, v in updates.items() if k in was}}
        # `_AUTO_COLORS` only recognises a colour NOBODY has touched yet, so it
        # says "hand-picked" about every event that has ever been categorised —
        # the category's own colour was written at creation. A colour that is
        # still its category's colour was assigned by this code, not chosen, so
        # it may follow the new category; anything else the user picked and keeps.
        color_in = now["color"]
        try:
            from assistant.actions.calendar.categories import color_for
            if was["category"] and color_in in color_for(was["category"]):
                color_in = None
        except Exception:                   # pragma: no cover - defensive
            pass
        cat, color = auto_category_and_color(
            conn, now["title"], now["date"], now["start_time"], now["attendees"] or "",
            now["location"] or "", now["description"] or "", color_in,
            None, exclude_id=event_id)
        out = dict(updates, category=cat)
        if "color" not in updates:
            out["color"] = color
        return out

    def _note_label_change(self, kind: str, row_id: int, fields: dict) -> None:
        """A person changed a label — the one signal worth learning from.

        Recorded here because this is where every surface converges: the Mac
        dialog, the iOS sheet and the HTTP PATCH all land on `update_event` /
        `set_todo_tags`, so hooking them catches a correction wherever it was
        made. Failures are swallowed — collecting training data must never
        break a user's edit.

        **Only a CHANGE is recorded.** A label the system assigned and nobody
        objected to is not agreement, and training on it would teach the model
        its own output; `engine/label/feedback.py` carries the full reasoning.
        """
        try:
            from assistant.engine.label import feedback as _fb
            if kind == "event" and "category" in fields:
                row = self.get_event(row_id) or {}
                _fb.record_category(row.get("title", ""), row.get("category"),
                                    str(fields["category"]), origin=_fb.CORRECTION)
            elif kind == "todo" and "tags" in fields:
                row = self.get_todo(row_id) or {}
                _fb.record_tags(row.get("title", ""), row.get("tags"),
                                list(fields["tags"] or []), origin=_fb.CORRECTION)
        except Exception:
            logger.warning("Could not record a label correction on %s %s",
                           kind, row_id, exc_info=True)

    def update_event(self, event_id: int, **fields) -> None:
        if "category" in fields:
            self._note_label_change("event", event_id, fields)
        allowed = {"title", "date", "start_time", "end_time", "attendees",
                   "location", "description", "color", "recurrence",
                   "recurrence_end", "category", "reminder_minutes"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        _memory_feedback("event", event_id, "corrected", updates)
        with self._conn() as conn:
            if self._is_externally_locked(conn, event_id):
                return
            # Rename an event and its label should follow the words. Renaming
            # is how a manual add gets fixed — book "meeting", correct it to
            # "gym" — and the category used to keep describing the typo, which
            # also means the wrong COLOUR for the rest of that event's life.
            # Only ever fills in what nobody chose: a caller passing `category`
            # has decided, and `auto_category_and_color` still refuses to
            # overwrite a colour picked by hand.
            updates = self._relabelled(conn, event_id, updates)
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [_utcnow_iso(), event_id]
            # updated_at is stamped in UTC (comparable against Graph's
            # lastModifiedDateTime for last-write-wins conflict resolution).
            # sync_dirty is only ever set here for outlook/google rows — the
            # periodic sync worker clears it once the push succeeds. Reaching
            # here at all already implies two-way is on (see the lock check
            # above), so this is never dirtied for a row nothing will push.
            conn.execute(
                f"UPDATE events SET {set_clause}, updated_at = ?, "
                f"sync_dirty = CASE WHEN source IN ('outlook', 'google') THEN 1 ELSE sync_dirty END "
                f"WHERE id = ?",
                values,
            )
            self._follow_event(conn, event_id, updates)

    def promote_to_series(self, event_id: int) -> None:
        """Promote a standalone event that already has recurrence set into a full series.

        Called when the user adds recurrence to a previously non-recurring event via the
        edit dialog.  The event becomes the series root and all future instances are
        generated.  No-op if the event already belongs to a series or has no recurrence.
        """
        event = self.get_event(event_id)
        if not event or not event.get("recurrence") or event.get("series_id"):
            return

        recurrence = event["recurrence"]
        recur_until = event.get("recurrence_end", "")

        with self._conn() as conn:
            self._create_series_instances(
                conn, event_id, _SeriesSeed(event), recurrence, recur_until,
                event.get("color", "#0078d4"), event.get("category") or "",
            )

    def update_series(self, series_id: int, start_from_instance_id: int, **fields) -> None:
        """
        Update this instance and all future instances in the series.
        Series-wide properties (title, times, recurrence, recurrence_end, etc.) are
        propagated to ALL instances (past and future) so that any instance always
        reflects the current series definition.  Future instances are then re-generated
        whenever the schedule changes.
        """
        instance = self.get_event(start_from_instance_id)
        if not instance:
            return

        recurrence = fields.get("recurrence", instance.get("recurrence", ""))
        recur_until = fields.get("recurrence_end", instance.get("recurrence_end", "")) or ""
        # The end date is INCLUSIVE ("ends on 30 Oct" books the 30th — the same
        # reading `_create_series_instances` has always applied) and may not
        # fall before the instance the edit is made through: the regeneration
        # below starts there, so an earlier end would trim nothing between the
        # two dates and leave instances standing past the series' own end.
        # Both editors floor their date picker at the event's own date; this
        # is the same rule for any other caller.
        if recurrence and recur_until:
            try:
                until_d = datetime.date.fromisoformat(recur_until)
            except ValueError:
                raise ValueError(f"recurrence_end must be an ISO date, not {recur_until!r}")
            if until_d.isoformat() < instance["date"]:
                raise ValueError(
                    f"recurrence_end {recur_until} is before this event ({instance['date']})")

        # Fields that are series-wide and should be propagated to ALL instances
        # (including past ones) so every instance always reflects the current series state.
        # recurrence + recurrence_end are included so past instances show the right until date.
        common = {
            "title", "start_time", "end_time", "attendees",
            "location", "description", "color",
            "recurrence", "recurrence_end",
        }
        updates = {k: v for k, v in fields.items() if k in common}

        with self._conn() as conn:
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [series_id, series_id]
                conn.execute(
                    f"UPDATE events SET {set_clause} WHERE series_id = ? OR id = ?",
                    values,
                )

            # Re-generate future instances whenever the series has any recurrence
            # (keeps things simple: title/time changes also re-sync future slots).
            old_recur = instance.get("recurrence", "")
            old_until = instance.get("recurrence_end", "")
            if "title" in updates:
                # the series' rolling to-do (Q61) is the same thing, renamed
                conn.execute(
                    "UPDATE todos SET title = ?, updated_at = ? WHERE linked_event_id IN "
                    "(SELECT id FROM events WHERE series_id = ? OR id = ?)",
                    (updates["title"], _utcnow_iso(), series_id, series_id))
            if recurrence != old_recur or recur_until != old_until or recurrence:
                # The rolling to-do of a repeating to-do (Q61) points at an
                # instance about to be regenerated; the delete trigger would
                # unlink it, so it is re-linked below to the first rebuilt
                # instance on or after the date it was due.
                riding = conn.execute(
                    "SELECT t.id, e.date FROM todos t JOIN events e ON e.id = t.linked_event_id "
                    "WHERE (e.series_id = ? OR e.id = ?) AND e.date > ?",
                    (series_id, series_id, instance["date"])).fetchall()
                # Delete all future instances after the edited one
                conn.execute(
                    "DELETE FROM events WHERE (series_id = ? OR id = ?) AND date > ?",
                    (series_id, series_id, instance["date"]),
                )

                # Re-generate from the edited instance's date forward. The seed
                # is the instance as it now reads (fields over the stored row),
                # so the rebuilt instances keep its guests, its category, its
                # reminder and — for a "tuesday and thursday" series — both
                # weekdays; each of those used to be dropped here.
                if recurrence:
                    seed_row = {**instance, **fields}
                    self._create_series_instances(
                        conn, series_id, _SeriesSeed(seed_row, date=instance["date"]),
                        recurrence, recur_until,
                        seed_row.get("color") or instance["color"],
                        seed_row.get("category") or instance.get("category") or "",
                    )
                for todo_id, was in riding:
                    row = conn.execute(
                        "SELECT id, date FROM events WHERE (series_id = ? OR id = ?) AND date >= ? "
                        "ORDER BY date, start_time LIMIT 1",
                        (series_id, series_id, was)).fetchone()
                    if row is not None:
                        self._move_link(conn, todo_id, row)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_event(self, event_id: int) -> None:
        """Delete a single event instance.

        If the deleted instance is the series root (series_id == id), the series is
        re-rooted to the next chronological instance so remaining instances keep a
        valid series_id reference and can still be edited/extended as a group.
        """
        _memory_feedback("event", event_id, "rejected")
        with self._conn() as conn:
            if self._is_externally_locked(conn, event_id):
                return

            # Reaching here means this isn't an ICS event and, if it's an
            # Outlook event, two-way sync is on — queue a tombstone so the
            # periodic sync worker deletes it on the Outlook side too. The
            # row (and its external_id) won't exist to retry from once the
            # DELETE below runs.
            synced = conn.execute(
                "SELECT external_source, external_id FROM events "
                "WHERE id = ? AND external_source IN ('outlook', 'google') AND external_id != ''",
                (event_id,),
            ).fetchone()
            if synced:
                conn.execute(
                    "INSERT INTO calendar_sync_deletes (external_source, external_id, created_at) "
                    "VALUES (?, ?, ?)",
                    (synced["external_source"], synced["external_id"], _utcnow_iso()),
                )

            # Check whether this event is the series root
            row = conn.execute(
                "SELECT id FROM events WHERE id = ? AND series_id = id",
                (event_id,),
            ).fetchone()
            if row:
                # Find the earliest remaining instance to become the new root
                next_row = conn.execute(
                    "SELECT id FROM events WHERE series_id = ? AND id != ? ORDER BY date, start_time LIMIT 1",
                    (event_id, event_id),
                ).fetchone()
                if next_row:
                    new_root = next_row["id"]
                    # Point all sibling instances at the new root
                    conn.execute(
                        "UPDATE events SET series_id = ? WHERE series_id = ?",
                        (new_root, event_id),
                    )
                    # Make the new root self-referential
                    conn.execute(
                        "UPDATE events SET series_id = ? WHERE id = ?",
                        (new_root, new_root),
                    )

            # One occurrence of a repeating to-do's series (Q61): its to-do
            # moves to the next occurrence rather than going with this one.
            linked = conn.execute("SELECT id FROM todos WHERE linked_event_id = ?",
                                  (event_id,)).fetchone()
            nxt = self._next_instance(conn, event_id) if linked else None
            if nxt is not None:
                self._move_link(conn, linked["id"], nxt)
            conn.execute("DELETE FROM todos WHERE linked_event_id = ?", (event_id,))
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def delete_series(self, series_id: int) -> int:
        """Delete all events in a series. Returns the count deleted."""
        with self._conn() as conn:
            conn.execute("DELETE FROM todos WHERE linked_event_id IN "
                         "(SELECT id FROM events WHERE series_id = ? OR id = ?)",
                         (series_id, series_id))
            cur = conn.execute(
                "DELETE FROM events WHERE series_id = ? OR id = ?",
                (series_id, series_id),
            )
            return cur.rowcount

    def delete_series_from(self, series_id: int, from_date: str) -> int:
        """Delete this event and all future instances in the series.

        If the root instance falls within the deleted range, re-roots the series
        to the latest remaining instance so past instances stay properly linked.
        """
        with self._conn() as conn:
            # Check if the root is being deleted
            root_row = conn.execute(
                "SELECT id FROM events WHERE id = ? AND id = series_id AND date >= ?",
                (series_id, from_date),
            ).fetchone()
            if root_row:
                # Find the latest past instance to become new root
                prev_row = conn.execute(
                    "SELECT id FROM events WHERE (series_id = ? OR id = ?) AND date < ? "
                    "ORDER BY date DESC, start_time DESC LIMIT 1",
                    (series_id, series_id, from_date),
                ).fetchone()
                if prev_row:
                    new_root = prev_row["id"]
                    conn.execute(
                        "UPDATE events SET series_id = ? WHERE series_id = ? AND date < ?",
                        (new_root, series_id, from_date),
                    )
                    conn.execute(
                        "UPDATE events SET series_id = ? WHERE id = ?",
                        (new_root, new_root),
                    )

            conn.execute("DELETE FROM todos WHERE linked_event_id IN "
                         "(SELECT id FROM events WHERE (series_id = ? OR id = ?) AND date >= ?)",
                         (series_id, series_id, from_date))
            cur = conn.execute(
                "DELETE FROM events WHERE (series_id = ? OR id = ?) AND date >= ?",
                (series_id, series_id, from_date),
            )
            return cur.rowcount

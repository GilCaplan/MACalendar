"""Timers and their sessions; counters, their presses and payouts."""

from __future__ import annotations

import datetime

from assistant.db.schema import DIRECTIONS


def _direction(value: str) -> str:
    """Which way the money runs; anything but a known value is refused, since
    a typo stored here would silently read as the default."""
    if value not in DIRECTIONS:
        raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}, not {value!r}")
    return value


def counter_press_amount(press: dict, price_per_unit: float) -> float:
    """What one press adds to its counter's payout: its own `amount` when it
    has one (signed by its delta), else `delta × price_per_unit`."""
    delta = int(press.get("delta") or 0)
    amount = press.get("amount")
    if amount is not None:
        return float(amount) if delta >= 0 else -float(amount)
    return delta * float(price_per_unit or 0)


def instant(iso: str) -> datetime.datetime:
    """An ISO timestamp as a comparable moment. A naive one (a time typed into
    a Mac dialog) is read as this machine's local time.

    Presses and cash-outs arrive in three spellings: the Mac's own clock
    writes microseconds, the phone writes whole seconds, and a dialog writes
    no offset. Compared as TEXT, "12:00:00.5+02:00" sorts after
    "12:00:00+02:00" because "." outranks "+", so a press made in the same
    second as a cash-out survived it.
    """
    dt = datetime.datetime.fromisoformat(iso)
    return dt.astimezone() if dt.tzinfo is None else dt


def open_presses(presses: list[dict]) -> list[dict]:
    """The presses still owed: those no cash-out has paid (`payout_id` NULL).

    A press records the cash-out that paid it, so the open cycle does not
    depend on clocks. It used to be "every press after the last cash-out's
    time", and that lost money: a press made offline at 10:00 and synced after
    an 11:00 cash-out was before the cash-out, so it was not in the new
    cycle, and it was not in the payout either. Now it is simply unpaid.
    """
    return [p for p in presses if p.get("payout_id") is None]


def link_presses_to_payouts(conn) -> None:
    """One-time backfill when `payout_id` is added: give each press the
    cash-out that, by the old time rule, paid it, so every count reads the
    same before and after. Presses after the last cash-out stay open."""
    counters = [r[0] for r in conn.execute("SELECT DISTINCT counter_id FROM counter_payouts")]
    for cid in counters:
        payouts = conn.execute("SELECT id, payout_at FROM counter_payouts WHERE counter_id = ?", (cid,)).fetchall()
        presses = conn.execute("SELECT id, pressed_at FROM counter_presses WHERE counter_id = ?", (cid,)).fetchall()
        try:
            payouts = sorted(payouts, key=lambda r: instant(r[1]))
        except ValueError:
            payouts = sorted(payouts, key=lambda r: r[1])
        unpaid = list(presses)
        for pid, payout_at in payouts:
            paid = [r for r in unpaid if _at_or_before(r[1], payout_at)]
            conn.executemany("UPDATE counter_presses SET payout_id = ? WHERE id = ?", [(pid, r[0]) for r in paid])
            unpaid = [r for r in unpaid if r not in paid]


def _at_or_before(when: str, limit: str) -> bool:
    """`when` is at or before `limit`; an unreadable time counts as before, so
    the backfill matches what the old rule showed."""
    try:
        return instant(when) <= instant(limit)
    except ValueError:
        return when <= limit


class TimersMixin:
    """Timers and their sessions; counters, their presses and payouts."""

    # ------------------------------------------------------------------
    # Util
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def create_timer(
        self,
        title: str = "Untitled Timer",
        hourly_rate: float = 0.0,
        color: str = "#1a6fc4",
        timer_type: str = "work",
        currency: str = "ILS",
        max_session_minutes: int = 0,
        direction: str = "owed_to_me",
    ) -> int:
        """Create a new timer project. Returns new row id."""
        direction = _direction(direction)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO timers (title, hourly_rate, color, created_at, timer_type, currency, "
                "max_session_minutes, direction) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, hourly_rate, color, datetime.datetime.now().isoformat(), timer_type, currency,
                 max_session_minutes, direction),
            )
            return cur.lastrowid

    def get_timers(self, include_archived: bool = False) -> list[dict]:
        """Return all timer projects as dicts, newest first."""
        with self._conn() as conn:
            where = "" if include_archived else "WHERE archived = 0"
            rows = conn.execute(
                f"SELECT * FROM timers {where} ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_timer(self, timer_id: int, **kwargs) -> None:
        """Update allowed fields on a timer."""
        allowed = {"title", "hourly_rate", "color", "archived", "timer_type", "currency", "max_session_minutes",
                   "direction"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if "direction" in fields:
            fields["direction"] = _direction(fields["direction"])
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE timers SET {sets} WHERE id = ?",
                (*fields.values(), timer_id),
            )

    def delete_timer(self, timer_id: int) -> None:
        """Delete a timer and all its sessions."""
        with self._conn() as conn:
            conn.execute("DELETE FROM timer_sessions WHERE timer_id = ?", (timer_id,))
            conn.execute("DELETE FROM timers WHERE id = ?", (timer_id,))

    # ------------------------------------------------------------------
    # Timer Sessions
    # ------------------------------------------------------------------

    def create_timer_session(self, timer_id: int, title: str = "", start_time: str | None = None) -> int:
        """Start a new session for a timer. Returns new row id."""
        now = datetime.datetime.now().astimezone().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO timer_sessions (timer_id, title, start_time, end_time, notes, created_at) VALUES (?, ?, ?, NULL, '', ?)",
                (timer_id, title, start_time or now, now),
            )
            return cur.lastrowid

    def get_timer_sessions(self, timer_id: int) -> list[dict]:
        """Return all sessions for a timer, oldest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM timer_sessions WHERE timer_id = ? ORDER BY start_time ASC",
                (timer_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_running_session(self, timer_id: int) -> dict | None:
        """Return the currently running (open) session for a timer, or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM timer_sessions WHERE timer_id = ? AND end_time IS NULL LIMIT 1",
                (timer_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_timer_session(self, session_id: int, **kwargs) -> None:
        """Update allowed fields on a timer session."""
        allowed = {"title", "start_time", "end_time", "notes"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE timer_sessions SET {sets} WHERE id = ?",
                (*fields.values(), session_id),
            )

    def stop_timer_session(self, session_id: int, end_time: str | None = None) -> None:
        """Close an open session by setting end_time."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE timer_sessions SET end_time = ? WHERE id = ?",
                (end_time or datetime.datetime.now().astimezone().isoformat(), session_id),
            )

    def delete_timer_session(self, session_id: int) -> None:
        """Delete a single timer session."""
        with self._conn() as conn:
            conn.execute("DELETE FROM timer_sessions WHERE id = ?", (session_id,))

    def split_timer_session(self, session_id: int, split_at: str | None = None) -> int:
        """
        Split a session at split_at (ISO datetime string) or its midpoint.
        Closes the original session at split_at and creates a new one.
        Returns the id of the new session.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM timer_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Session {session_id} not found")
            session = dict(row)

        start = datetime.datetime.fromisoformat(session["start_time"])
        if start.tzinfo is None:
            start = start.astimezone()
        end_raw = session.get("end_time")
        end = datetime.datetime.fromisoformat(end_raw) if end_raw else datetime.datetime.now()
        if end.tzinfo is None:
            end = end.astimezone()

        if split_at:
            mid = datetime.datetime.fromisoformat(split_at)
        else:
            mid = start + (end - start) / 2

        self.update_timer_session(session_id, end_time=mid.isoformat())
        return self.create_timer_session(
            session["timer_id"],
            title=session["title"],
            start_time=mid.isoformat(),
        )

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    def create_counter(
        self,
        title: str = "Untitled Counter",
        price_per_unit: float = 0.0,
        currency: str = "ILS",
        color: str = "#1a6fc4",
        direction: str = "owed_to_me",
    ) -> int:
        """Create a new tally counter. Returns new row id."""
        direction = _direction(direction)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO counters (title, price_per_unit, currency, color, created_at, direction) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title, price_per_unit, currency, color, datetime.datetime.now().isoformat(), direction),
            )
            return cur.lastrowid

    def get_counters(self, include_archived: bool = False) -> list[dict]:
        """Return all counters as dicts, newest first."""
        with self._conn() as conn:
            where = "" if include_archived else "WHERE archived = 0"
            rows = conn.execute(
                f"SELECT * FROM counters {where} ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_counter(self, counter_id: int, **kwargs) -> None:
        """Update allowed fields on a counter."""
        allowed = {"title", "price_per_unit", "currency", "color", "archived", "direction"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if "direction" in fields:
            fields["direction"] = _direction(fields["direction"])
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE counters SET {sets} WHERE id = ?",
                (*fields.values(), counter_id),
            )

    def delete_counter(self, counter_id: int) -> None:
        """Delete a counter and all its presses and payout history."""
        with self._conn() as conn:
            conn.execute("DELETE FROM counter_presses WHERE counter_id = ?", (counter_id,))
            conn.execute("DELETE FROM counter_payouts WHERE counter_id = ?", (counter_id,))
            conn.execute("DELETE FROM counters WHERE id = ?", (counter_id,))

    # ------------------------------------------------------------------
    # Counter Presses
    # ------------------------------------------------------------------

    def create_counter_press(
        self,
        counter_id: int,
        delta: int = 1,
        label: str = "",
        pressed_at: str | None = None,
        amount: float | None = None,
    ) -> int:
        """Log a single +/- tap on a counter. Returns new row id.

        `amount` overrides the counter's price for this one press (None = the
        usual price)."""
        now = datetime.datetime.now().astimezone().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO counter_presses (counter_id, delta, label, pressed_at, created_at, amount) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (counter_id, delta, label, pressed_at or now, now, amount),
            )
            return cur.lastrowid

    def get_counter_presses(self, counter_id: int) -> list[dict]:
        """Return all presses for a counter, oldest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM counter_presses WHERE counter_id = ? ORDER BY pressed_at ASC",
                (counter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_counter_press(self, press_id: int, **kwargs) -> None:
        """Update allowed fields on a counter press."""
        allowed = {"delta", "label", "pressed_at", "amount"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE counter_presses SET {sets} WHERE id = ?",
                (*fields.values(), press_id),
            )

    def delete_counter_press(self, press_id: int) -> None:
        """Delete a single counter press."""
        with self._conn() as conn:
            conn.execute("DELETE FROM counter_presses WHERE id = ?", (press_id,))

    # ------------------------------------------------------------------
    # Counter Payouts ("cash out" a counter's current tally cycle)
    # ------------------------------------------------------------------

    def create_counter_payout(
        self,
        counter_id: int,
        cycle_started_at: str,
        payout_at: str,
        count: int,
        amount: float | None,
        currency: str,
        note: str = "",
    ) -> int:
        """Log a payout that closes out a counter's current tally cycle.

        `count` is a snapshot of the net delta-sum for that cycle at the
        moment of payout — it is never recomputed later, so subsequent edits
        or deletions of presses don't retroactively rewrite payout history.
        Returns the new row id.
        """
        now = datetime.datetime.now().astimezone().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO counter_payouts "
                "(counter_id, cycle_started_at, payout_at, count, amount, currency, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (counter_id, cycle_started_at, payout_at, count, amount, currency, note, now),
            )
            return cur.lastrowid

    def get_counter_payouts(self, counter_id: int) -> list[dict]:
        """Return all payouts for a counter, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM counter_payouts WHERE counter_id = ? ORDER BY payout_at DESC",
                (counter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_counter_payout(self, payout_id: int, **kwargs) -> None:
        """Update allowed fields on a counter payout.

        `count` and `cycle_started_at` are immutable snapshots and are not
        in the allowed set — only the human-editable fields (when it was
        paid, how much, and any note) can change after the fact.
        """
        allowed = {"payout_at", "amount", "note"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE counter_payouts SET {sets} WHERE id = ?",
                (*fields.values(), payout_id),
            )

    def cash_out_counter(
        self,
        counter_id: int,
        payout_at: str,
        *,
        bank_until: str | None = None,
        count: int | None = None,
        amount: float | None = None,
        note: str = "",
    ) -> dict | None:
        """Pay the presses still owed, up to `bank_until` (default `payout_at`),
        in ONE write: the payout row and each press's link to it.

        Returns None, and writes nothing, when nothing is owed. That is what
        makes a second tap, or a queued request replayed after its reply was
        lost, harmless: the first paid everything, the second finds nothing.
        A press stamped later (another device, while this request waited)
        stays open and lands on top of the new cycle.

        `count` and `amount` override the computed ones (the Mac's dialog lets
        you correct them); both are snapshots, never recomputed later.
        """
        limit = bank_until or payout_at
        now = datetime.datetime.now().astimezone().isoformat()
        with self._conn() as conn:
            counter = conn.execute("SELECT * FROM counters WHERE id = ?", (counter_id,)).fetchone()
            if counter is None:
                return None
            unpaid = [dict(r) for r in conn.execute(
                "SELECT * FROM counter_presses WHERE counter_id = ? AND payout_id IS NULL", (counter_id,))]
            paid = [p for p in unpaid if _at_or_before(p["pressed_at"], limit)]
            if not paid:
                return None
            price = float(counter["price_per_unit"] or 0)
            first = min(paid, key=lambda p: p["pressed_at"])["pressed_at"]
            row = {
                "counter_id": counter_id,
                "cycle_started_at": first,
                "payout_at": payout_at,
                "count": sum(int(p["delta"]) for p in paid) if count is None else count,
                "amount": round(sum(counter_press_amount(p, price) for p in paid), 2) if amount is None else amount,
                "currency": counter["currency"],
                "note": note,
                "created_at": now,
            }
            cur = conn.execute(
                "INSERT INTO counter_payouts (counter_id, cycle_started_at, payout_at, count, amount, currency, "
                "note, created_at) VALUES (:counter_id, :cycle_started_at, :payout_at, :count, :amount, "
                ":currency, :note, :created_at)", row)
            row["id"] = cur.lastrowid
            conn.executemany("UPDATE counter_presses SET payout_id = ? WHERE id = ?",
                             [(row["id"], p["id"]) for p in paid])
            return row

    def delete_counter_payout(self, payout_id: int) -> None:
        """Delete a payout. Its presses become owed again: deleting a cash-out
        says it did not happen. The press log itself is untouched."""
        with self._conn() as conn:
            conn.execute("UPDATE counter_presses SET payout_id = NULL WHERE payout_id = ?", (payout_id,))
            conn.execute("DELETE FROM counter_payouts WHERE id = ?", (payout_id,))

    def get_counter_cycle_start(self, counter_id: int) -> str | None:
        """Return the start of the counter's current (open) tally cycle.

        This is the most recent payout's `payout_at` for that counter, or
        None if it has never been cashed out — in which case the current
        cycle spans the counter's entire press history.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payout_at FROM counter_payouts WHERE counter_id = ?",
                (counter_id,),
            ).fetchall()
        # Latest by MOMENT, not by text: the stamps come in mixed spellings
        # (see `instant`).
        stamps = [r["payout_at"] for r in rows]
        if not stamps:
            return None
        try:
            return max(stamps, key=instant)
        except ValueError:
            return max(stamps)

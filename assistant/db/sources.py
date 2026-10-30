"""Connected calendars (ICS, Outlook, Google) and the sync bookkeeping on events."""

from __future__ import annotations

import datetime

from assistant.db.common import _utcnow_iso
from assistant.db.schema import TWO_WAY_SOURCES


def _source_for(external_source: str) -> str:
    """events.source for a row synced from *external_source* (an ICS feed's
    external_source is 'ics:<id>')."""
    return external_source if external_source in TWO_WAY_SOURCES else "ics"


class SourcesMixin:
    """Connected calendars (ICS, Outlook, Google) and the sync bookkeeping on events."""

    # ------------------------------------------------------------------
    # Connected calendars (ICS subscriptions + Outlook two-way sync)
    # ------------------------------------------------------------------

    def get_calendar_sources(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM calendar_sources ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_calendar_source(self, source_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_sources WHERE id = ?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_calendar_source_by_kind(self, kind: str) -> dict | None:
        """There's only ever one 'outlook' source (a single account) —
        this avoids callers fetching the whole table just to find it."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_sources WHERE kind = ? LIMIT 1", (kind,)
            ).fetchone()
        return dict(row) if row else None

    def create_calendar_source(
        self, kind: str, label: str = "", url: str = "",
        color: str = "#0078d4", two_way: bool = False,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO calendar_sources "
                "(kind, label, url, color, two_way, last_synced, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, '', 1, ?)",
                (kind, label, url, color, int(two_way), _utcnow_iso()),
            )
            return cur.lastrowid

    def update_calendar_source(self, source_id: int, **fields) -> None:
        allowed = {"label", "url", "color", "two_way", "last_synced", "enabled",
                   "last_error", "account", "sync_token"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE calendar_sources SET {set_clause} WHERE id = ?",
                (*updates.values(), source_id),
            )

    def delete_calendar_source(self, source_id: int) -> None:
        """Remove a connected source and any local events it produced.

        Outlook events (external_source='outlook') are left in place — that
        connection is a single shared account, not a deletable per-source
        feed, and disconnecting Outlook is handled separately (it just stops
        the sync worker from touching those rows again).
        """
        with self._conn() as conn:
            source = conn.execute(
                "SELECT kind, id FROM calendar_sources WHERE id = ?", (source_id,)
            ).fetchone()
            if source and source["kind"] == "ics_url":
                conn.execute(
                    "DELETE FROM events WHERE external_source = ?",
                    (f"ics:{source_id}",),
                )
            conn.execute("DELETE FROM calendar_sources WHERE id = ?", (source_id,))

    def get_events_by_external_source(self, external_source: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE external_source = ?", (external_source,)
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_external_event(self, external_source: str, external_id: str, data: dict) -> int:
        """Insert or update a read-only/synced event keyed by (external_source, external_id).

        Used by both ICS subscription refresh and Outlook pull. Returns the
        local row id. UPDATE and INSERT share the same field dict so a
        column added to one path can't silently be forgotten on the other
        (this previously happened to `attendees`, which was only ever set on
        first insert and never refreshed on subsequent syncs).
        """
        fields = {
            "title": data["title"],
            "date": data["date"],
            "start_time": data["start_time"],
            "end_time": data["end_time"],
            "attendees": data.get("attendees", ""),
            "location": data.get("location", ""),
            "description": data.get("description", ""),
            "color": data.get("color", "#0078d4"),
        }
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM events WHERE external_source = ? AND external_id = ?",
                (external_source, external_id),
            ).fetchone()
            if row:
                event_id = row["id"]
                set_clause = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(
                    f"UPDATE events SET {set_clause}, updated_at = ? WHERE id = ?",
                    (*fields.values(), _utcnow_iso(), event_id),
                )
                return event_id

            columns = list(fields) + [
                "created_at", "updated_at", "source", "external_id", "external_source"
            ]
            placeholders = ", ".join("?" for _ in columns)
            cur = conn.execute(
                f"INSERT INTO events ({', '.join(columns)}) VALUES ({placeholders})",
                (
                    *fields.values(),
                    _utcnow_iso(), _utcnow_iso(),
                    _source_for(external_source),
                    external_id, external_source,
                ),
            )
            return cur.lastrowid

    def delete_events_not_in(self, external_source: str, keep_external_ids: list[str]) -> int:
        """Remove previously-synced events whose external_id no longer appears upstream.

        Only ever touches rows already tagged with *external_source* — never
        local/manual events. Returns the number removed.
        """
        with self._conn() as conn:
            if keep_external_ids:
                placeholders = ", ".join("?" for _ in keep_external_ids)
                cur = conn.execute(
                    f"DELETE FROM events WHERE external_source = ? "
                    f"AND external_id NOT IN ({placeholders})",
                    (external_source, *keep_external_ids),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM events WHERE external_source = ?", (external_source,)
                )
            return cur.rowcount

    def get_dirty_outlook_events(self) -> list[dict]:
        """Non-recurring local events pending push to Outlook (created or edited)."""
        return self.get_dirty_synced_events("outlook")

    def get_dirty_synced_events(self, source: str) -> list[dict]:
        """Non-recurring events pending push to *source* ('outlook' | 'google').
        A row with an empty external_id has never reached the service — the
        push CREATES it there."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE source = ? "
                "AND sync_dirty = 1 AND series_id IS NULL", (source,)
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_sync_dirty(self, event_id: int, if_updated_at: str | None = None) -> None:
        """Mark a row pushed. With *if_updated_at*, only when nobody edited it
        while the push was in flight — otherwise that edit would never go out."""
        with self._conn() as conn:
            if if_updated_at is None:
                conn.execute("UPDATE events SET sync_dirty = 0 WHERE id = ?", (event_id,))
            else:
                conn.execute("UPDATE events SET sync_dirty = 0 WHERE id = ? AND updated_at = ?",
                             (event_id, if_updated_at))

    def mark_for_push(self, event_id: int, source: str) -> bool:
        """Mirror a plain local event to *source*: the next sync creates it
        there and it becomes a two-way row. Only for a local, non-series event
        that is not already synced anywhere. Returns whether it was marked."""
        if source not in TWO_WAY_SOURCES:
            return False
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE events SET source = ?, external_source = ?, external_id = '', "
                "sync_dirty = 1, updated_at = ? WHERE id = ? AND source = 'local' "
                "AND external_source = '' AND series_id IS NULL",
                (source, source, _utcnow_iso(), event_id))
            return cur.rowcount > 0

    def mark_new_local_events_for_push(self, source: str, since: str) -> int:
        """`mark_for_push` for every eligible local event created at or after
        *since* (UTC ISO) — the `mirror_new_events` switch. Events that existed
        before the connection are never swept up."""
        if source not in TWO_WAY_SOURCES or not since:
            return 0
        # events.created_at is LOCAL naive time (add_event), `since` is UTC.
        try:
            since = (datetime.datetime.fromisoformat(since)
                     .astimezone().replace(tzinfo=None).isoformat())
        except ValueError:
            return 0
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE events SET source = ?, external_source = ?, external_id = '', "
                "sync_dirty = 1 WHERE source = 'local' AND external_source = '' "
                "AND series_id IS NULL AND created_at >= ?",
                (source, source, since))
            return cur.rowcount

    def detach_from_remote(self, event_id: int) -> None:
        """The remote copy is gone but the local edit is newer: forget the
        remote id and keep the row dirty, so the next push re-creates it."""
        with self._conn() as conn:
            conn.execute("UPDATE events SET external_id = '', sync_dirty = 1 WHERE id = ?",
                         (event_id,))

    def delete_external_event(self, external_source: str, external_id: str) -> int:
        """Remove a synced row because the SERVICE deleted it — no tombstone,
        unlike `delete_event`, which would echo the delete back."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM events WHERE external_source = ? AND external_id = ?",
                (external_source, external_id))
            return cur.rowcount

    def release_synced_events(self, external_source: str, keep: bool) -> int:
        """On disconnect: keep the synced rows as plain local events, or remove
        them. Queued tombstones for that service are dropped either way."""
        with self._conn() as conn:
            conn.execute("DELETE FROM calendar_sync_deletes WHERE external_source = ?",
                         (external_source,))
            if keep:
                cur = conn.execute(
                    "UPDATE events SET source = 'local', external_source = '', "
                    "external_id = '', sync_dirty = 0 WHERE external_source = ?",
                    (external_source,))
            else:
                cur = conn.execute("DELETE FROM events WHERE external_source = ?",
                                   (external_source,))
            return cur.rowcount

    def set_event_external_id(self, event_id: int, external_source: str, external_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE events SET source = ?, external_source = ?, external_id = ?, "
                "sync_dirty = 0 WHERE id = ?",
                (_source_for(external_source),
                 external_source, external_id, event_id),
            )

    def pop_sync_deletes(self, external_source: str | None = None) -> list[dict]:
        """Return and clear queued tombstones for the sync worker to push —
        only *external_source*'s when given. Each provider pops its OWN: popping
        all of them meant the first provider to drain the queue silently
        dropped every other provider's deletes."""
        with self._conn() as conn:
            if external_source is None:
                rows = conn.execute("SELECT * FROM calendar_sync_deletes").fetchall()
                conn.execute("DELETE FROM calendar_sync_deletes")
            else:
                rows = conn.execute("SELECT * FROM calendar_sync_deletes WHERE external_source = ?",
                                    (external_source,)).fetchall()
                conn.execute("DELETE FROM calendar_sync_deletes WHERE external_source = ?",
                             (external_source,))
        return [dict(r) for r in rows]

    def requeue_sync_delete(self, external_source: str, external_id: str) -> None:
        """Re-enqueue a tombstone whose push attempt failed, for the next sync cycle."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO calendar_sync_deletes (external_source, external_id, created_at) "
                "VALUES (?, ?, ?)",
                (external_source, external_id, _utcnow_iso()),
            )

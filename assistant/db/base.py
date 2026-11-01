"""Opening the file: the test guard, the connection, the schema and its migrations,
and the client-token lookups every area's creates share."""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from assistant.db.common import _note_own_write
from assistant.db.schema import (
    _CALENDAR_SOURCE_MIGRATIONS,
    _COUNTER_MIGRATIONS,
    _COUNTER_PRESS_MIGRATIONS,
    _CREATE_ASSIGNMENTS_TABLE,
    _CREATE_CALENDAR_SOURCES_TABLE,
    _CREATE_COUNTER_PAYOUTS_TABLE,
    _CREATE_COUNTER_PRESSES_TABLE,
    _CREATE_COUNTERS_TABLE,
    _CREATE_COURSES_TABLE,
    _CREATE_INDEXES,
    _CREATE_REMINDER_LOG_TABLE,
    _CREATE_SUBTASKS_TABLE,
    _CREATE_SYNC_DELETES_TABLE,
    _CREATE_TABLE,
    _CREATE_TAG_SUGGESTION_STATE_TABLE,
    _CREATE_TAGS_TABLE,
    _CREATE_TIMER_SESSIONS_TABLE,
    _CREATE_TIMERS_TABLE,
    _CREATE_TODOS_TABLE,
    _CREATE_WORKOUT_EXERCISES_TABLE,
    _CREATE_WORKOUT_PLAN_ITEMS_TABLE,
    _CREATE_WORKOUT_PLANS_TABLE,
    _CREATE_WORKOUT_SESSIONS_TABLE,
    _CREATE_WORKOUT_SET_LOGS_TABLE,
    _CREATE_WORKOUT_TEMPLATE_BLOCKS_TABLE,
    _CREATE_WORKOUT_TEMPLATE_SETS_TABLE,
    _CREATE_WORKOUT_TEMPLATES_TABLE,
    _IDEMPOTENT_TABLES,
    _LEGACY_LINK_SOURCE,
    _MIGRATIONS,
    _TAG_SUGGESTION_MIGRATIONS,
    _TIMER_MIGRATIONS,
    _TODO_MIGRATIONS,
    _WORKOUT_MIGRATIONS,
    DEFAULT_TODO_TAGS,
    SCHEMA_VERSION,
)
from assistant.db.timers import link_presses_to_payouts

logger = logging.getLogger(__name__)


def _default_path() -> str:
    """`assistant.db.DB_PATH`, read at call time as the single-file module
    read its own global, so code that sets it (tests, scripts) still steers
    `CalendarDB()` and the real-file guard."""
    import assistant.db as pkg
    return pkg.DB_PATH


class StoreBase:
    """Opening the file: the test guard, the connection, the schema and its migrations,
and the client-token lookups every area's creates share."""

    @staticmethod
    def _guard_real_db(path: str) -> None:
        """Never open the real database from a test run.

        A test script with no isolation once emptied the real calendar — 657
        events — because `CalendarDB()` with no path quietly means "the user's
        own data". Under pytest that is never what is wanted, so it is refused
        outright rather than left to each script to remember.
        """
        if not (os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION")):
            return
        real = os.path.realpath(path)
        default = _default_path()
        real_root = os.path.realpath(os.path.dirname(default))
        if real == os.path.realpath(default) or real.startswith(
                os.path.join(real_root, "users") + os.sep):
            raise RuntimeError(
                f"Refusing to open the real calendar database ({default}) from a test. "
                "Set MACALENDAR_DB, or call tests.isolation.isolate() before importing "
                "anything from `assistant`."
            )

    def __init__(self, path: str | None = None) -> None:
        # MACALENDAR_DB lets tests/audits point at a scratch database.
        if path is None:
            path = os.environ.get("MACALENDAR_DB") or None
            # No explicit path → the BOUND user's calendar. The Mac window
            # builds `CalendarDB()` directly (window.py), so resolving only in
            # get_db() would leave it opening a fresh, empty file at the old
            # location once the data had moved under users/<uid>/.
            from assistant.users import paths as _paths
            path = _paths.resolve(path or _default_path())
        self.path = path
        self.owner_id: str | None = None
        self._guard_real_db(self.path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._conn() as conn:
            conn.execute(_CREATE_TABLE)
            self._migrate(conn)
            conn.execute(_CREATE_TODOS_TABLE)
            self._migrate_todos(conn)
            self._migrate_links(conn)
            conn.execute(_CREATE_TAGS_TABLE)
            self._seed_default_tags(conn)
            conn.execute(_CREATE_SUBTASKS_TABLE)
            conn.execute(_CREATE_TIMERS_TABLE)
            self._migrate_timers(conn)
            conn.execute(_CREATE_TIMER_SESSIONS_TABLE)
            conn.execute(_CREATE_COUNTERS_TABLE)
            self._add_columns(conn, "counters", _COUNTER_MIGRATIONS)
            conn.execute(_CREATE_COUNTER_PRESSES_TABLE)
            linked = "payout_id" in {r[1] for r in conn.execute("PRAGMA table_info(counter_presses)")}
            self._add_columns(conn, "counter_presses", _COUNTER_PRESS_MIGRATIONS)
            conn.execute(_CREATE_COUNTER_PAYOUTS_TABLE)
            if not linked:
                link_presses_to_payouts(conn)
            conn.execute(_CREATE_COURSES_TABLE)
            conn.execute(_CREATE_ASSIGNMENTS_TABLE)
            conn.execute(_CREATE_REMINDER_LOG_TABLE)
            conn.execute(_CREATE_CALENDAR_SOURCES_TABLE)
            self._add_columns(conn, "calendar_sources", _CALENDAR_SOURCE_MIGRATIONS)
            conn.execute(_CREATE_SYNC_DELETES_TABLE)
            conn.execute(_CREATE_WORKOUT_EXERCISES_TABLE)
            conn.execute(_CREATE_WORKOUT_TEMPLATES_TABLE)
            conn.execute(_CREATE_WORKOUT_TEMPLATE_BLOCKS_TABLE)
            conn.execute(_CREATE_WORKOUT_TEMPLATE_SETS_TABLE)
            conn.execute(_CREATE_WORKOUT_SESSIONS_TABLE)
            conn.execute(_CREATE_WORKOUT_SET_LOGS_TABLE)
            conn.execute(_CREATE_WORKOUT_PLANS_TABLE)
            conn.execute(_CREATE_WORKOUT_PLAN_ITEMS_TABLE)
            self._migrate_workouts(conn)
            self._migrate_client_tokens(conn)
            conn.execute(_CREATE_TAG_SUGGESTION_STATE_TABLE)
            self._add_columns(conn, "tag_suggestion_state", _TAG_SUGGESTION_MIGRATIONS)
            for stmt in _CREATE_INDEXES.strip().splitlines():
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            self._stamp_version(conn)

    @staticmethod
    def _add_columns(conn: sqlite3.Connection, table: str, statements) -> None:
        """Run each `ALTER TABLE … ADD COLUMN` whose column is not there yet."""
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for stmt in statements:
            if stmt.split("ADD COLUMN")[1].strip().split()[0] not in existing:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass                    # another process added it first

    def table_names(self) -> set[str]:
        """Every table in the file, for health checks (`assistant doctor`)."""
        with self._conn() as conn:
            return {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}

    def _stamp_version(self, conn: sqlite3.Connection) -> None:
        """Record the schema in the file (see `schema.SCHEMA_VERSION`)."""
        found = conn.execute("PRAGMA user_version").fetchone()[0]
        if found > SCHEMA_VERSION:
            logger.warning("%s was written by newer code (schema %d, this code knows %d)",
                           self.path, found, SCHEMA_VERSION)
        elif found < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def row_by_client_token(self, table: str, client_token: str) -> dict | None:
        """The row a client already created with this token, or None.

        Table-agnostic on purpose: six tables need exactly this and a method
        each would be six chances to write it slightly differently. The table
        name is checked against a fixed tuple rather than interpolated blindly —
        it reaches here from a route, and a route's input is never a table name.
        """
        token = (client_token or "").strip()
        if not token or table not in _IDEMPOTENT_TABLES:
            return None
        with self._conn() as conn:
            try:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE client_token = ?", (token,)).fetchone()
            except sqlite3.OperationalError:
                return None
        return dict(row) if row else None

    def set_client_token(self, table: str, row_id: int, client_token: str) -> bool:
        """Stamp a freshly created row with the client's idempotency token.

        False means the UNIQUE INDEX refused it — another pass created the row
        first, between our lookup and our insert. That is not an error and must
        not be logged as one: it is exactly the race the index exists to
        referee, and the caller's job is then to return the row that won.
        """
        token = (client_token or "").strip()
        if not token or table not in _IDEMPOTENT_TABLES:
            return False
        try:
            with self._conn() as conn:
                conn.execute(f"UPDATE {table} SET client_token = ? WHERE id = ?",
                             (token, row_id))
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.OperationalError:
            return False

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Apply any missing schema migrations safely."""
        self._add_columns(conn, "events", _MIGRATIONS)
        # DATA, not schema: `Running` and `Gym` fold into the one `Fitness`
        # category (Gil, 2026-09-10). The planner stopped writing them that
        # day; 38 rows written before it still carried the old names on
        # 2026-09-22. Idempotent, so it costs one no-op UPDATE per open.
        try:
            conn.execute("UPDATE events SET category='Fitness' "
                         "WHERE category IN ('Running', 'Gym')")
        except sqlite3.OperationalError:
            pass

    def _migrate_todos(self, conn: sqlite3.Connection) -> None:
        """Apply any missing todos schema migrations safely."""
        self._add_columns(conn, "todos", _TODO_MIGRATIONS)

    def _migrate_links(self, conn: sqlite3.Connection) -> None:
        """The link's invariants, enforced by the database rather than by every
        caller: one to-do per event (a partial UNIQUE index), and no to-do left
        pointing at an event that is gone. Events are deleted from a dozen places
        — series regeneration, both calendar syncs, a reset — so a trigger
        UNLINKS on every one of them; only a delete the user asked for
        (`delete_event`, `delete_series*`) removes the to-do as well."""
        try:
            conn.execute(
                "UPDATE todos SET linked_event_id = source_event_id, "
                "source_event_id = NULL, source = 'manual' WHERE source = ?",
                (_LEGACY_LINK_SOURCE,))
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_todos_linked_event "
                "ON todos(linked_event_id) WHERE linked_event_id IS NOT NULL")
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS trg_events_unlink_todo "
                "AFTER DELETE ON events BEGIN "
                "UPDATE todos SET linked_event_id = NULL WHERE linked_event_id = OLD.id; "
                "END")
        except sqlite3.OperationalError:
            pass    # events table not created yet on a brand-new file

    def _migrate_client_tokens(self, conn: sqlite3.Connection) -> None:
        """Give every client-creatable table a creation idempotency key.

        The UNIQUE INDEX is the part that actually enforces it — the column
        alone only lets a route look a token up, and two overlapping sync
        passes can both look up, both miss, and both insert. It is PARTIAL
        (`WHERE client_token != ''`) because every row created in-process —
        voice, the Mac GUI, calendar import — has an empty token and must not
        collide with the others.
        """
        for table in _IDEMPOTENT_TABLES:
            try:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            except sqlite3.OperationalError:
                continue                    # table not created yet
            if not cols:
                continue
            if "client_token" not in cols:
                try:
                    conn.execute(f"ALTER TABLE {table} "
                                 "ADD COLUMN client_token TEXT NOT NULL DEFAULT ''")
                except sqlite3.OperationalError:
                    pass
            try:
                conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_client_token "
                    f"ON {table}(client_token) WHERE client_token != ''")
            except sqlite3.OperationalError:
                pass

    def _migrate_workouts(self, conn: sqlite3.Connection) -> None:
        """Apply any missing workout schema migrations safely.

        Unlike the events/todos migrators this one spans two tables, so each
        statement carries the table its column belongs to.
        """
        cache: dict = {}
        for table, stmt in _WORKOUT_MIGRATIONS:
            if table not in cache:
                cache[table] = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            col = stmt.split("ADD COLUMN")[1].strip().split()[0]
            if col not in cache[table]:
                try:
                    conn.execute(stmt)
                    cache[table].add(col)
                except sqlite3.OperationalError:
                    pass  # already exists

    def _seed_default_tags(self, conn: sqlite3.Connection) -> None:
        """Insert the built-in tag palette once (first launch after upgrade)."""
        if conn.execute("SELECT COUNT(*) FROM todo_tags").fetchone()[0]:
            return
        now = datetime.datetime.now().isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO todo_tags (name, color, builtin, created_at) VALUES (?, ?, 1, ?)",
            [(n, c, now) for n, c in DEFAULT_TODO_TAGS],
        )

    def _migrate_timers(self, conn: sqlite3.Connection) -> None:
        """Apply any missing timers schema migrations safely."""
        self._add_columns(conn, "timers", _TIMER_MIGRATIONS)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            changed = conn.total_changes
            conn.commit()
            if changed:
                _note_own_write(self.path)
        finally:
            conn.close()

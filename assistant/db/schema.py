"""The tables in calendar.db, their migrations and indexes.

One file so the whole schema reads in one place; each area module (events,
todos, timers, …) holds the code for its own tables.
"""

#: The `todos.source` the first linked to-dos (DEVQA Q50, 2026-09-25 morning)
#: were stored under, before the link got its own column; `_migrate_links`
#: moves them onto `linked_event_id`.
_LEGACY_LINK_SOURCE = "linked_event"

_CREATE_TODOS_TABLE = """
CREATE TABLE IF NOT EXISTS todos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    list            TEXT    NOT NULL DEFAULT 'today',
    completed       INTEGER NOT NULL DEFAULT 0,
    priority        TEXT    NOT NULL DEFAULT 'none',
    due_date        TEXT    NOT NULL DEFAULT '',
    notes           TEXT    NOT NULL DEFAULT '',
    source          TEXT    NOT NULL DEFAULT 'manual',
    source_event_id INTEGER,
    created_at      TEXT    NOT NULL,
    completed_at    TEXT    NOT NULL DEFAULT '',
    position        INTEGER NOT NULL DEFAULT 0,
    quantity        INTEGER NOT NULL DEFAULT 1
)
"""

_TODO_MIGRATIONS = [
    "ALTER TABLE todos ADD COLUMN priority TEXT NOT NULL DEFAULT 'none'",
    "ALTER TABLE todos ADD COLUMN due_date TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE todos ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE todos ADD COLUMN source_event_id INTEGER",
    "ALTER TABLE todos ADD COLUMN completed_at TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE todos ADD COLUMN position INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE todos ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE events ADD COLUMN category TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE todos ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE todos ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1",
    # Version stamp, so a client that edited a task while disconnected can say
    # which version it was working from (see PATCH /todos/<id>).
    "ALTER TABLE todos ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
    # Idempotency key for creation. A client mints one token per task the user
    # asked for and sends it on every attempt — the first live POST and every
    # later replay of the same queued create. POST /todos returns the existing
    # row for a token it has already stored instead of inserting a second one,
    # so a retried create can no longer become a duplicate task. Empty for
    # rows created in-process (voice, calendar sync, the Mac GUI), which never
    # go over the wire and so can never be retried.
    "ALTER TABLE todos ADD COLUMN client_token TEXT NOT NULL DEFAULT ''",
    # The event this to-do IS (see "A to-do and an event linked as one thing").
    # Its own column, not `source`/`source_event_id`: those say where a row
    # CAME FROM (the calendar->tasks sync mirrors events through them), and a
    # link is not an origin — any to-do can be linked, and unlinked, later.
    "ALTER TABLE todos ADD COLUMN linked_event_id INTEGER",
]

#: Tables whose rows a CLIENT can create, and which therefore need a creation
#: idempotency key. Same key, same reason and same shape as
#: `todos.client_token`, which was added after 32 duplicate "buy groceries"
#: rows accumulated in the Today list: a queued create that reaches the Mac but
#: whose reply is lost stays at the head of the phone's queue and is replayed,
#: and without a token the second attempt inserts a second row.
#:
#: `todos` is absent because it already has one. `events` has its own.
_IDEMPOTENT_TABLES = ("courses", "assignments", "timers", "counters",
                      "timer_sessions", "counter_presses", "events")

# Known tag names (so user-created tags persist even when no todo uses them).
# `todos.tags` holds a JSON list of tag names; this table is the palette.
_CREATE_TAGS_TABLE = """
CREATE TABLE IF NOT EXISTS todo_tags (
    name       TEXT PRIMARY KEY,
    color      TEXT NOT NULL DEFAULT '',
    builtin    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""

DEFAULT_TODO_TAGS = [
    ("Coursework", "#7c6ff0"),
    ("Groceries",  "#3fb27f"),
    ("Errands",    "#e0a020"),
    ("Work",       "#4a9edd"),
    ("Personal",   "#e0608a"),
    # 2026-09-24 (Gil: "the ideal amount of categories"): the two clusters his
    # untagged and mis-tagged to-dos fell into — paperwork and bills, and the
    # weekly Shabbat preparation. Seeded only on a NEW database; an existing
    # one gets them through POST /tags, so a user who deletes one keeps it gone.
    ("Admin",      "#8a94a6"),
    ("Shabbat",    "#c084fc"),
]

_CREATE_SUBTASKS_TABLE = """
CREATE TABLE IF NOT EXISTS subtasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_id    INTEGER NOT NULL,
    title      TEXT    NOT NULL,
    completed  INTEGER NOT NULL DEFAULT 0,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
)
"""

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT    NOT NULL,
    date           TEXT    NOT NULL,
    start_time     TEXT    NOT NULL,
    end_time       TEXT    NOT NULL,
    attendees      TEXT    NOT NULL DEFAULT '',
    location       TEXT    NOT NULL DEFAULT '',
    description    TEXT    NOT NULL DEFAULT '',
    color          TEXT    NOT NULL DEFAULT '#0078d4',
    created_at     TEXT    NOT NULL,
    series_id      INTEGER,               -- NULL = not recurring; shared by all instances
    recurrence     TEXT    NOT NULL DEFAULT '',   -- '' | 'daily' | 'weekly' | 'monthly' | 'yearly'
    recur_days     TEXT    NOT NULL DEFAULT '',   -- weekly only: 'tuesday,thursday'
    recurrence_end TEXT    NOT NULL DEFAULT ''    -- '' or ISO date (last allowed date)
)
"""

# Columns added after initial release — migrated on first open
_MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN series_id INTEGER",
    "ALTER TABLE events ADD COLUMN recurrence TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE events ADD COLUMN recurrence_end TEXT NOT NULL DEFAULT ''",
    # External calendar sync bookkeeping (ICS subscriptions + two-way Outlook sync)
    "ALTER TABLE events ADD COLUMN source TEXT NOT NULL DEFAULT 'local'",
    "ALTER TABLE events ADD COLUMN external_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE events ADD COLUMN external_source TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE events ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE events ADD COLUMN sync_dirty INTEGER NOT NULL DEFAULT 0",
    # Pre-event notifications: NULL = inherit (category default, then global),
    # 0 = explicitly none, N>0 = fire N minutes before start_time.
    "ALTER TABLE events ADD COLUMN reminder_minutes INTEGER",
    # A weekly series can name SEVERAL weekdays ("every tuesday and thursday").
    # Stored comma-separated and lowercase; empty means "the same weekday as the
    # first instance", which is every series written before 2026-09-08.
    "ALTER TABLE events ADD COLUMN recur_days TEXT NOT NULL DEFAULT ''",
]

_CREATE_CALENDAR_SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS calendar_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,             -- 'ics_url' | 'outlook' | 'google'
    label       TEXT    NOT NULL DEFAULT '',
    url         TEXT    NOT NULL DEFAULT '',  -- ics_url only
    color       TEXT    NOT NULL DEFAULT '#0078d4',
    two_way     INTEGER NOT NULL DEFAULT 0,   -- outlook/google — push local changes back
    last_synced TEXT    NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
)
"""

# Added with the brain-side sync (2026-09-24): what the connect/status routes
# show on both apps, and Google's incremental-sync cursor.
_CALENDAR_SOURCE_MIGRATIONS = [
    "ALTER TABLE calendar_sources ADD COLUMN last_error TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calendar_sources ADD COLUMN account TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calendar_sources ADD COLUMN sync_token TEXT NOT NULL DEFAULT ''",
]

#: The two-way providers. A row whose `source` is one of these is a mirror of
#: an event on that service: edits mark it dirty and deletes leave a tombstone.
TWO_WAY_SOURCES = ("outlook", "google")

_CREATE_SYNC_DELETES_TABLE = """
CREATE TABLE IF NOT EXISTS calendar_sync_deletes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_source TEXT    NOT NULL,
    external_id     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL
)
"""

_CREATE_TIMERS_TABLE = """
CREATE TABLE IF NOT EXISTS timers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL DEFAULT 'Untitled Timer',
    hourly_rate REAL    NOT NULL DEFAULT 0.0,
    color       TEXT    NOT NULL DEFAULT '#1a6fc4',
    created_at  TEXT    NOT NULL,
    archived    INTEGER NOT NULL DEFAULT 0,
    timer_type  TEXT    NOT NULL DEFAULT 'work',
    currency    TEXT    NOT NULL DEFAULT 'ILS',
    max_session_minutes INTEGER NOT NULL DEFAULT 0,
    direction   TEXT    NOT NULL DEFAULT 'owed_to_me'
)
"""

_TIMER_MIGRATIONS = [
    "ALTER TABLE timers ADD COLUMN timer_type TEXT NOT NULL DEFAULT 'work'",
    "ALTER TABLE timers ADD COLUMN currency TEXT NOT NULL DEFAULT 'ILS'",
    "ALTER TABLE timers ADD COLUMN max_session_minutes INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE timers ADD COLUMN direction TEXT NOT NULL DEFAULT 'owed_to_me'",
]

_CREATE_TIMER_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS timer_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timer_id   INTEGER NOT NULL,
    title      TEXT    NOT NULL DEFAULT '',
    start_time TEXT    NOT NULL,
    end_time   TEXT,
    notes      TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
)
"""

_CREATE_COUNTERS_TABLE = """
CREATE TABLE IF NOT EXISTS counters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL DEFAULT 'Untitled Counter',
    price_per_unit  REAL    NOT NULL DEFAULT 0.0,
    currency        TEXT    NOT NULL DEFAULT 'ILS',
    color           TEXT    NOT NULL DEFAULT '#1a6fc4',
    created_at      TEXT    NOT NULL,
    archived        INTEGER NOT NULL DEFAULT 0,
    direction       TEXT    NOT NULL DEFAULT 'owed_to_me'
)
"""

# Which way the money runs on a timer or counter: 'owed_to_me' (the default,
# and what every row meant before 2026-11-01: a carpool rider owes me, a client
# pays my hours) or 'i_owe' (I pay the carpool driver, the babysitter's hours).
# It changes the label, never the arithmetic.
DIRECTIONS = ("owed_to_me", "i_owe")

_COUNTER_MIGRATIONS = [
    "ALTER TABLE counters ADD COLUMN direction TEXT NOT NULL DEFAULT 'owed_to_me'",
]

# Each tap of +/- is logged as its own row (mirrors timer_sessions) so the
# running count is always derivable — never stored redundantly — and every
# tap keeps a timestamp (for the date / time-of-day bucket) plus an optional
# label describing what that tap was for.
_CREATE_COUNTER_PRESSES_TABLE = """
CREATE TABLE IF NOT EXISTS counter_presses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    counter_id  INTEGER NOT NULL,
    delta       INTEGER NOT NULL DEFAULT 1,
    label       TEXT    NOT NULL DEFAULT '',
    pressed_at  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    amount      REAL
)
"""

# `amount` is what ONE press is worth when it is not the counter's usual
# price — a carpool that cost 5 instead of the usual 7.5. NULL means "the
# counter's price", read at the time the total is computed, so changing the
# rate still reprices every ordinary press as it always did.
_COUNTER_PRESS_MIGRATIONS = [
    "ALTER TABLE counter_presses ADD COLUMN amount REAL",
    # The cash-out that paid this press; NULL = still owed (see
    # `timers.open_presses`). Backfilled once by `link_presses_to_payouts`.
    "ALTER TABLE counter_presses ADD COLUMN payout_id INTEGER",
]

# A "cash out" closes the counter's current tally cycle: it snapshots the
# net count for that cycle (so later press edits/deletes never retroactively
# rewrite payout history — mirrors how timer session totals aren't
# recomputed after the fact) and records when/how much was paid. Cycle
# boundaries are pure time boundaries against counter_presses.pressed_at —
# cycle_started_at is the previous payout's payout_at, or the counter's own
# created_at for the first-ever payout — so no migration of counter_presses
# is ever needed.
_CREATE_COUNTER_PAYOUTS_TABLE = """
CREATE TABLE IF NOT EXISTS counter_payouts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    counter_id        INTEGER NOT NULL,
    cycle_started_at  TEXT    NOT NULL,
    payout_at         TEXT    NOT NULL,
    count             INTEGER NOT NULL,
    amount            REAL,
    currency          TEXT    NOT NULL,
    note              TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL
)
"""

_CREATE_COURSES_TABLE = """
CREATE TABLE IF NOT EXISTS courses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    number     TEXT    NOT NULL DEFAULT '',
    name       TEXT    NOT NULL,
    color      TEXT    NOT NULL DEFAULT '#1a6fc4',
    partners   TEXT    NOT NULL DEFAULT '[]',
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
)
"""

_CREATE_REMINDER_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS reminder_log (
    event_id INTEGER NOT NULL,
    fires_at TEXT    NOT NULL,               -- ISO local datetime it was due
    fired_at TEXT    NOT NULL DEFAULT '',    -- when it actually delivered
    outcome  TEXT    NOT NULL DEFAULT '',    -- fired | suppressed | missed
    UNIQUE (event_id, fires_at)
)
"""

# DB-backed (not in-memory) because the API runs with --reload: every source
# edit restarts the process, and an in-memory fired-set would re-fire
# constantly during development.

_CREATE_ASSIGNMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS assignments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id         INTEGER NOT NULL,
    title             TEXT    NOT NULL,
    due_date          TEXT    NOT NULL DEFAULT '',
    completed         INTEGER NOT NULL DEFAULT 0,
    calendar_event_id INTEGER,
    created_at        TEXT    NOT NULL
)
"""

# ---------------------------------------------------------------------------
# Workout (Phase 1: backend-only sync target for the existing local-only iOS
# Workout feature — see MACalendar-iOS/.../Workout/WorkoutModels.swift).
#
# Unlike events/todos (server-assigned autoincrement Int id + temp-id remap
# for offline creation), these tables use client-generated UUIDs (TEXT
# PRIMARY KEY) end-to-end, matching how the iOS structs already mint their
# own `id: UUID` at creation time. The server just stores whatever id the
# client sends — no remap dance needed, conflict-free by construction.
#
# Normalized child tables (no JSON blob columns), matching this codebase's
# existing convention (see todos/subtasks, timers/timer_sessions).
# ---------------------------------------------------------------------------

_CREATE_WORKOUT_EXERCISES_TABLE = """
CREATE TABLE IF NOT EXISTS workout_exercises (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_WORKOUT_TEMPLATES_TABLE = """
CREATE TABLE IF NOT EXISTS workout_templates (
    id                              TEXT PRIMARY KEY,
    name                            TEXT    NOT NULL,
    default_rest_between_sets       INTEGER NOT NULL DEFAULT 90,
    default_rest_between_exercises  INTEGER NOT NULL DEFAULT 120,
    created_at                      TEXT    NOT NULL,
    status                          TEXT    NOT NULL DEFAULT 'saved'
    -- status: 'saved' | 'draft' — 'draft' = pending review after
    -- GenerateWorkoutRoutineAction auto-generation; excluded from normal
    -- template list queries unless explicitly requested.
)
"""

_CREATE_WORKOUT_TEMPLATE_BLOCKS_TABLE = """
CREATE TABLE IF NOT EXISTS workout_template_blocks (
    id                          TEXT PRIMARY KEY,
    template_id                 TEXT    NOT NULL,
    order_index                 INTEGER NOT NULL DEFAULT 0,
    kind                        TEXT    NOT NULL,   -- 'single' | 'superset'
    -- .single
    exercise_id                 TEXT,
    rest_between_sets_override  INTEGER,
    -- .superset
    exercise_id_a               TEXT,
    exercise_id_b               TEXT,
    rest_after_round            INTEGER
)
"""

_CREATE_WORKOUT_TEMPLATE_SETS_TABLE = """
CREATE TABLE IF NOT EXISTS workout_template_sets (
    id             TEXT PRIMARY KEY,
    block_id       TEXT    NOT NULL,
    side           TEXT    NOT NULL DEFAULT 'single',  -- 'single' | 'a' | 'b'
    set_index      INTEGER NOT NULL DEFAULT 0,
    type           TEXT    NOT NULL,                   -- 'reps' | 'time'
    target_reps    INTEGER,
    weight_kg      REAL,
    target_seconds INTEGER,
    note           TEXT    NOT NULL DEFAULT ''
)
"""

_CREATE_WORKOUT_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS workout_sessions (
    id          TEXT PRIMARY KEY,
    template_id TEXT,             -- NULL = ad-hoc session
    started_at  TEXT NOT NULL,
    ended_at    TEXT,              -- NULL = in progress (should be finished before sync in practice)
    notes       TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_WORKOUT_SET_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS workout_set_logs (
    id               TEXT PRIMARY KEY,
    session_id       TEXT    NOT NULL,
    exercise_id      TEXT    NOT NULL,
    set_index        INTEGER NOT NULL DEFAULT 0,
    type             TEXT    NOT NULL,     -- 'reps' | 'time'
    actual_reps      INTEGER,
    actual_seconds   INTEGER,
    actual_weight_kg REAL,
    completed_at     TEXT,
    skipped          INTEGER NOT NULL DEFAULT 0
)
"""

# Columns added to the workout tables after the gym-only first release. Running
# needs a third kind of set: not reps-and-weight, not a timed hold, but a
# distance at a target pace — "5 x 400m @ 3:50". Modelled as set type
# 'distance' so the existing block/set/session/log machinery (and the
# follow-along that rides on it) is reused rather than duplicated.
_WORKOUT_MIGRATIONS = [
    ("workout_template_sets", "ALTER TABLE workout_template_sets ADD COLUMN distance_m REAL"),
    ("workout_template_sets", "ALTER TABLE workout_template_sets ADD COLUMN target_pace_sec_per_km INTEGER"),
    ("workout_set_logs",      "ALTER TABLE workout_set_logs ADD COLUMN actual_distance_m REAL"),
    ("workout_set_logs",      "ALTER TABLE workout_set_logs ADD COLUMN actual_pace_sec_per_km INTEGER"),
]

# ---------------------------------------------------------------------------
# Workout scheduling: a dated block of sessions.
#
# Templates answer "what does this session consist of?"; plans answer "on which
# day does it happen, and in which part of that day?". Keeping them in separate
# tables is what allows one template ("Threshold 2 x 12 min") to be scheduled
# many times, and a plan to be re-flowed around a chag without touching the
# session content.
#
# Each item carries `event_id`: the calendar event it was materialised into.
# That link is what makes re-planning update the calendar rather than litter it
# with duplicates, and it is why deleting a plan can clean up after itself.
# ---------------------------------------------------------------------------

_CREATE_WORKOUT_PLANS_TABLE = """
CREATE TABLE IF NOT EXISTS workout_plans (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    goal       TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active'   -- 'active' | 'draft' | 'archived'
)
"""

_CREATE_WORKOUT_PLAN_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS workout_plan_items (
    id              TEXT PRIMARY KEY,
    plan_id         TEXT    NOT NULL,
    date            TEXT    NOT NULL,
    start_time      TEXT    NOT NULL DEFAULT '',
    end_time        TEXT    NOT NULL DEFAULT '',
    -- 'long'|'easy'|'threshold'|'speed'|'tt'|'gym'|'calisthenics'|'rest'
    kind            TEXT    NOT NULL,
    discipline      TEXT    NOT NULL DEFAULT 'run',   -- 'run' | 'strength'
    title           TEXT    NOT NULL,
    detail          TEXT    NOT NULL DEFAULT '',
    distance_km     REAL,
    template_id     TEXT,                             -- follow-along template
    event_id        INTEGER,                          -- materialised calendar event
    window_label    TEXT    NOT NULL DEFAULT '',      -- 'morning'|'daytime'|'evening'
    observance_note TEXT    NOT NULL DEFAULT '',      -- why it sits where it does
    session_id      TEXT,                             -- logged session, once done
    created_at      TEXT    NOT NULL
)
"""

#: What the tag-discovery popup has asked and been told
#: (`assistant/actions/todo/tag_discovery.py`). It used to create this table
#: itself, from outside the store, the first time it ran.
_CREATE_TAG_SUGGESTION_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS tag_suggestion_state (
    name    TEXT PRIMARY KEY,
    status  TEXT NOT NULL,          -- refused | accepted | asked
    ts      TEXT NOT NULL,
    hidden  INTEGER NOT NULL DEFAULT 0
)
"""
_TAG_SUGGESTION_MIGRATIONS = [
    "ALTER TABLE tag_suggestion_state ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0",
]

#: The schema this code writes, stamped into the file as `PRAGMA user_version`
#: once every migration has run. Bump it with any migration you add. A file
#: stamped HIGHER was written by newer code than this, which is worth a
#: warning: this code may not know a column the newer code relies on.
#: 1 = the schema at the per-area split (2026-10-30), tag suggestions included.
#: 2 = timers and counters say which way the money runs (`direction`).
#: 3 = each counter press records the cash-out that paid it (`payout_id`).
SCHEMA_VERSION = 3

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_events_date      ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_series    ON events(series_id);
CREATE INDEX IF NOT EXISTS idx_todos_list       ON todos(list, completed);
CREATE UNIQUE INDEX IF NOT EXISTS idx_todos_client_token ON todos(client_token) WHERE client_token != '';
CREATE INDEX IF NOT EXISTS idx_subtasks_todo    ON subtasks(todo_id, position);
CREATE INDEX IF NOT EXISTS idx_timer_sessions   ON timer_sessions(timer_id);
CREATE INDEX IF NOT EXISTS idx_counter_presses  ON counter_presses(counter_id);
CREATE INDEX IF NOT EXISTS idx_counter_payouts  ON counter_payouts(counter_id);
CREATE INDEX IF NOT EXISTS idx_assignments_course ON assignments(course_id);
CREATE INDEX IF NOT EXISTS idx_events_external    ON events(external_source, external_id);
CREATE INDEX IF NOT EXISTS idx_workout_templates_status  ON workout_templates(status, created_at);
CREATE INDEX IF NOT EXISTS idx_workout_blocks_template   ON workout_template_blocks(template_id, order_index);
CREATE INDEX IF NOT EXISTS idx_workout_sets_block        ON workout_template_sets(block_id, set_index);
CREATE INDEX IF NOT EXISTS idx_workout_sessions_started  ON workout_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_workout_set_logs_session  ON workout_set_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_workout_plan_items_date   ON workout_plan_items(date);
CREATE INDEX IF NOT EXISTS idx_workout_plan_items_plan   ON workout_plan_items(plan_id, date);
CREATE INDEX IF NOT EXISTS idx_workout_plan_items_event  ON workout_plan_items(event_id);
"""

# Replication — one main copy, a synced copy on each computer

Gil, 2026-10-22: the main server moved to the PC; *"all devices should be
synchronized... local back up in each, then sync when possible at reasonable
pace or after something is updated a request is sent."* DEVQA Q94.

    phone ──REST──▶ HUB (the PC: an ordinary MACalendar server)
                     ▲ │  /sync/push   /sync/pull
                     │ ▼
                   REPLICA (the Mac: its own calendar.db, its own window)

- **The phone** is unchanged: it already keeps its own copy and queues what it
  could not send (`MACalendar-iOS/LocalStore.swift`, the offline queue), and
  talks to the hub's REST routes.
- **A replica** keeps its own file, so the Mac window, the voice engine and
  everything else read and write it exactly as before — and keep working with
  the hub away. `sync.hub` in config.yaml makes a server a replica.

## How a change travels

**Triggers, not wrappers** (`changelog.py`). Every replicated table has
insert/update/delete triggers writing `(table, id, op, origin)` into
`_sync_log`. They see every write from every process — the 49 write methods
the window uses, the engine, cascades — and a method written next month.
The log is STATE-based: whoever reads an entry reads the row as it is now.

- **Replica → hub.** The log is the outbox. The loop (`replica.py`, a thread in
  the Mac's `assistant.api`) checks it every second and pushes what is there.
  The hub applies it in one transaction under the replica's name (`origin`).
- **Hub → replica.** The hub's log is the feed. The replica pulls everything
  after its cursor every `pull_seconds` (and right after a push), minus rows
  whose last change came from itself. It applies them with `mute` set so they
  are not queued to go back up.
- **Push before pull, always.** A row edited here and not yet sent is skipped
  by a pull: the local edit goes up next and wins.

## Ids

Both sides number rows the same way, so a row the Mac makes offline and one
the phone makes on the hub can take the same id. A pushed row the Mac CREATED
keeps its id when the hub has no such row; when it has one (and it did not
come from this replica — a resent push is not a collision) the hub gives a
fresh id and returns `remap`, and the Mac moves its copy and every row pointing
at it (`changelog.FKS`). Same in the other direction: a pulled row landing on
an id the Mac gave to an unsent row of its own moves the Mac's row first.

## What does not travel

`calendar_sources`, `calendar_sync_deletes` (each server's calendar sign-ins —
a replica does not run calendar_sync at all, or every external event would be
imported twice) and `reminder_log` (what this machine has already shown).
Only `calendar.db`, and only the default user (the admin a request with no
login is bound to): the flashcards, command memory, vocabulary, categories,
Jude chats and other users' calendars are each still one machine's — TASKS.

## First sync

A replica's file usually has a life of its own already. `python -m
assistant.sync reconcile` compares it with the hub's snapshot and prints, per
table: rows only here (sent), only on the hub (taken), the same id holding two
different rows (judged by `created_at`; sent as new), and one row changed on
both (the hub's kept). `--apply` backs the file up and does it. Until a
replica has reconciled once, its loop moves nothing.

## Tests

`tests/unit/test_sync_replica.py` — a real hub (the API app) against a second
file: first sync, both directions, deletes, an id collision with a child row,
an unsent edit against the hub's older copy, and no echo.

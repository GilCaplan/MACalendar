"""Creating the same thing twice, when the phone had to ask twice.

A write made while the Mac was away is queued and replayed on reconnect
(`APIClient.mutate` → `LocalStore.enqueue` → `syncPending`). Replay is
AT-LEAST-ONCE by construction: if the create reaches the Mac and commits but
the reply is lost, the entry stays at the head of the phone's queue and goes
out again. Without a key to recognise it by, the second attempt inserts a
second row.

That is not hypothetical. It is how **32 duplicate "buy groceries" rows**
accumulated in the Today list over 2026-09-04..06, which is why `todos` grew a
`client_token`. Courses, assignments, timers, counters, timer sessions and
counter presses had the same exposure and no key, right up until the phone
started queueing their writes — at which point the exposure became real.

The client mints one token per thing the USER asked to create and sends the
same token on the live attempt and every replay. The server returns the row it
already has.
"""

from __future__ import annotations


def idempotent_create(table: str, data: dict, create, *, db=None):
    """Run `create()` unless this token already made a row. Returns (body, status).

    `201` for a row created now, `200` for one that already existed — the
    distinction matters to the phone, which uses the id either way but should
    not treat a duplicate as new.

    The lookup-then-insert is a RACE, and deliberately not locked: two sync
    passes can both miss and both insert. The partial unique index on
    `client_token` referees that, `set_client_token` returns False for the
    loser, and the loser then returns the winner's row. A lock here would
    serialise every create on this machine to avoid a collision that the
    database already handles.
    """
    if db is None:
        from assistant.api import server
        db = server.get_db()

    token = str(data.get("client_token") or "").strip()
    if token:
        existing = db.row_by_client_token(table, token)
        if existing is not None:
            return {"id": existing["id"], "duplicate": True}, 200

    new_id = create()

    if token and not db.set_client_token(table, new_id, token):
        # Somebody else got there first. Return THEIR row, and leave ours —
        # deleting it would be a second write racing the same window.
        existing = db.row_by_client_token(table, token)
        if existing is not None:
            return {"id": existing["id"], "duplicate": True}, 200
    return {"id": new_id}, 201

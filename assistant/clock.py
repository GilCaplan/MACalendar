"""The moment a command was SAID — what "now", "today", "tomorrow" and
"tonight" mean while it is read.

Gil, 2026-10-09: two commands typed on the phone on Thursday sat in its
queue (Tailscale was off) and would have been read on Friday — "date
tomorrow at 10:30" landing on Saturday. *"the now should be a variable and
used by the timestamp of the command not hardcoded"*. So everything that
READS a command asks this module, never the wall clock:

    now()      the said moment, plus however long the reading has taken
    today()    now().date()
    said_at(ts)  context manager: read this command as of `ts` (epoch
                 seconds); None, or a moment in the future, means now

Bookkeeping stays on the real clock — a row's created/updated stamp, a
notification, a sync — because it records when something HAPPENED.

A `ContextVar`, like the bound user (`assistant/users`), so it is per
request, and `users.thread` carries it into the engine's worker threads.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as _dt
import time as _time
from typing import Iterator

#: Seconds between the real clock and the said moment; 0 for a live command.
_behind: "contextvars.ContextVar[float]" = contextvars.ContextVar(
    "macalendar_said_behind", default=0.0)

#: A command older than this is not trusted to know its own moment — a phone
#: whose clock is wrong would book a year away. Read as of now instead.
MAX_AGE_S = 60 * 24 * 3600


def now() -> _dt.datetime:
    return _dt.datetime.now() - _dt.timedelta(seconds=_behind.get())


def today() -> _dt.date:
    return now().date()


def behind() -> float:
    """How far behind the real clock this command is read (0 when live)."""
    return _behind.get()


@contextlib.contextmanager
def said_at(ts: "float | str | None") -> Iterator[None]:
    try:
        lag = _time.time() - float(ts) if ts not in (None, "") else 0.0
    except (TypeError, ValueError):
        lag = 0.0
    # a moment in the future (clock skew) or a few seconds old is "now";
    # one older than MAX_AGE_S is not believed
    if lag < 5 or lag > MAX_AGE_S:
        lag = 0.0
    token = _behind.set(lag)
    try:
        yield
    finally:
        _behind.reset(token)

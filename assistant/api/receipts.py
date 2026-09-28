"""One queued command, one run — however many times the phone sends it.

Found 2026-09-28: "Walk Jada every day…" was uploaded three times in 55 s and
booked three identical 12-event series, each with its own linked to-do. The
phone's offline queue marks a command `.running`, uploads it, and on anything
it reads as "offline" — the app backgrounded, the network blinked mid-upload —
puts it back to `.queued` and sends it again on the next flush. The Mac had
already received the first copy and was 74 s into running it; nothing on the
server could tell the second copy from a new command.

So a queued command now carries the phone's own id for it (`client_id`, the
`PendingVoiceCommand.id` UUID). The first request with an id runs; a request
with an id that is running WAITS for that run and gets its answer; one with an
id that already ran gets the stored answer at once. Either way it runs once.

HTTP plumbing, not parsing or execution — which is why it sits beside
`server.py` rather than in the engine. In memory: the resends it guards
against arrive within seconds to minutes, and the API reloading between two
copies of the same upload is the one gap left.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

#: How long an answer is kept for a late resend. The phone revives a command
#: stranded in `.running` after 900 s (LocalStore.reviveStalledVoice), so an
#: hour covers every resend it can make.
TTL_SEC = 3600
#: How long a duplicate waits for the first copy before giving up. Longer than
#: the phone's own request timeout (120 s), so it answers before the phone
#: gives up on the duplicate as well.
WAIT_SEC = 110

_lock = threading.Lock()
_runs: dict[str, "_Run"] = {}


class _Run:
    __slots__ = ("done", "result", "at")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: "dict[str, Any] | None" = None
        self.at = time.monotonic()


def _sweep(now: float) -> None:
    for cid in [c for c, r in _runs.items() if r.done.is_set() and now - r.at > TTL_SEC]:
        del _runs[cid]


def clean(client_id: "str | None") -> str:
    """Bounded and stripped like `device_id` — it keys a dict and a log line."""
    return "".join(ch for ch in (client_id or "") if ch.isalnum() or ch in "-_")[:64]


def run_once(client_id: "str | None", fn: Callable[[], Any]) -> Any:
    """Run `fn` once per `client_id`. Without an id it simply runs.

    Only a successful answer (a dict) is kept; an error response or an
    exception frees the id, so a genuine retry of a command that FAILED still
    runs. A duplicate that outwaits the first copy gets an honest "still
    running" rather than a second run.
    """
    cid = clean(client_id)
    if not cid:
        return fn()
    with _lock:
        _sweep(time.monotonic())
        run = _runs.get(cid)
        owner = run is None
        if owner:
            run = _runs[cid] = _Run()
    if not owner:
        run.done.wait(WAIT_SEC)
        if run.result is not None:
            return dict(run.result, duplicate=True)
        return {"message": "This command is already running on your Mac.",
                "actions": [], "refresh": "none", "parse": "duplicate",
                "duplicate": True}
    try:
        result = fn()
    except BaseException:
        with _lock:
            _runs.pop(cid, None)
        run.done.set()
        raise
    if isinstance(result, dict):
        run.result = result
        run.at = time.monotonic()
    else:
        with _lock:
            _runs.pop(cid, None)
    run.done.set()
    return result


def _reset() -> None:
    """Tests only."""
    with _lock:
        _runs.clear()

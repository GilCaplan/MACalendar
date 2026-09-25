"""The brain's calendar sync: one function every trigger shares, and the loop.

Until 2026-09-24 the 15-minute sync was a QTimer in the calendar WINDOW, so
with the window closed — most of the day — nothing synced, and a phone asking
for "Sync now" had no way to ask. It lives in `assistant.api` now, the process
that is always up, and the GUI's button and the phone's both call `sync_now`
through the API.

One run at a time: a manual sync that arrives mid-cycle is told so rather than
running a second pull against the same rows.
"""

from __future__ import annotations

import logging
import threading
import time

from assistant.db import _utcnow_iso

logger = logging.getLogger(__name__)

THREAD_NAME = "calendar-sync"
_FIRST_DELAY_S = 45.0      # let the API finish booting (and ride out --reload restarts)

_run_lock = threading.Lock()
_state: dict = {"running": False, "last_run": None}
_started = False
_start_lock = threading.Lock()


def _empty_results() -> dict:
    return {"ics_synced": 0, "ics_removed": 0,
            "outlook_pulled": 0, "outlook_pushed": 0,
            "google_pulled": 0, "google_pushed": 0, "google_removed": 0,
            "errors": []}


def run_all(db, config) -> dict:
    """Refresh every connected source once: ICS links, Outlook, Google.
    Each provider's failure is recorded on its row and in `errors`; none stops
    the others, and nothing raises."""
    from assistant.calendar_sync.google_sync import sync_google
    from assistant.calendar_sync.ics_subscription import sync_all_ics_sources

    results = _empty_results()
    try:
        kept, removed, ics_errors = sync_all_ics_sources(db)
        results["ics_synced"], results["ics_removed"] = kept, removed
        results["errors"].extend(ics_errors)
    except Exception as e:  # noqa: BLE001
        logger.exception("ICS refresh failed")
        results["errors"].append(f"ICS: {e}")

    try:
        from assistant.calendar_sync.outlook_sync import sync_outlook
        o = sync_outlook(db, config)
        results["outlook_pulled"], results["outlook_pushed"] = o["pulled"], o["pushed"]
        if o["error"]:
            results["errors"].append(o["error"])
    except Exception as e:  # noqa: BLE001 — e.g. msal missing
        logger.exception("Outlook sync failed")
        results["errors"].append(f"Outlook sync: {e}")

    g = sync_google(db, config)
    results["google_pulled"], results["google_pushed"] = g["pulled"], g["pushed"]
    results["google_removed"] = g["removed"]
    if g["error"]:
        results["errors"].append(g["error"])
    return results


def sync_now(db=None, config=None) -> dict:
    """Run one sync in THIS thread, unless one is already running.
    Returns the results, or {"busy": True} when another run holds the lock."""
    if not _run_lock.acquire(blocking=False):
        return {"busy": True}
    _state["running"] = True
    started = _utcnow_iso()
    try:
        if db is None:
            from assistant.db import get_db
            db = get_db()
        if config is None:
            from assistant.config import load_config
            config = load_config()
        results = run_all(db, config)
    except Exception as e:  # noqa: BLE001 — config unreadable, DB locked …
        logger.exception("Calendar sync failed")
        results = {**_empty_results(), "errors": [str(e)]}
    finally:
        _state["running"] = False
        _run_lock.release()
    _state["last_run"] = {"started": started, "finished": _utcnow_iso(), "results": results}
    if results.get("errors"):
        logger.warning("📅 Calendar sync finished with errors: %s", "; ".join(results["errors"]))
    else:
        logger.info("📅 Calendar sync: %s", {k: v for k, v in results.items() if v and k != "errors"})
    return results


def sync_in_background() -> bool:
    """`sync_now` on a worker thread. False when a run is already going."""
    if _run_lock.locked():
        return False
    threading.Thread(target=sync_now, daemon=True, name="calendar-sync-now").start()
    return True


def state() -> dict:
    return {"running": _state["running"], "last_run": _state["last_run"]}


def _has_sources() -> bool:
    from assistant.db import get_db
    return any(s["enabled"] for s in get_db().get_calendar_sources())


def start_background() -> bool:
    """Start the periodic loop once per process; returns whether it did.

    Only `create_app()` calls this, and only when it starts its other
    background workers — never under the suite's no-warm-up flag, and never in
    the --reload watcher (which would sync a second time from the same Mac)."""
    global _started
    with _start_lock:
        if _started:
            return False
        _started = True

    def _loop() -> None:
        from assistant.config import load_config
        time.sleep(_FIRST_DELAY_S)
        while True:
            interval_min = 15
            try:
                cfg = load_config()      # re-read each tick: an edit needs no restart
                interval_min = max(1, int(cfg.calendar_sync.interval_minutes))
                # No connected source means no network call at all — the
                # default posture stays fully offline.
                if cfg.calendar_sync.enabled and _has_sources():
                    sync_now(config=cfg)
            except Exception as e:  # noqa: BLE001 — the loop must outlive any one failure
                logger.warning("📅 Calendar sync loop error: %s", e)
            time.sleep(interval_min * 60)

    threading.Thread(target=_loop, daemon=True, name=THREAD_NAME).start()
    logger.info("📅 Calendar sync loop started")
    return True

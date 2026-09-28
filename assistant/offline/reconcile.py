"""Compare the phone's offline reading with what the Mac's engine committed.

Called by the voice routes AFTER the engine has run the resent command, so
nothing here decides anything the engine does — the Mac's reading has already
won by the time this runs. This only says HOW the two readings relate, for two
readers: the phone (which removes its placeholders and tells the speaker when
the Mac read it differently) and the log (which is how the offline reader is
measured).

Verdicts:
    same        every item the phone booked, the Mac booked too — same kind,
                a matching title, same day, start and repeat
    changed     the Mac's reading differs; its rows replace the phone's
    pending     the Mac's own model was unavailable, so it queued the command
                (`pending_id`); the phone keeps its placeholders until the Mac
                has run it
    deferred    the phone booked nothing (it left the command for the Mac)
    unverified  a protocol this Mac does not know — compared with nothing
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from assistant.offline import log
from assistant.offline.spec import MAY_COMMIT, PROTOCOL

_STOP = {"a", "an", "the", "my", "to", "with", "for", "at", "on", "in", "of"}


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (title or "").lower()) if w not in _STOP}


def titles_match(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return (a or "").strip().lower() == (b or "").strip().lower()
    return wa <= wb or wb <= wa or len(wa & wb) / len(wa | wb) >= 0.5


def _hhmm(t: str) -> str:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", t or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _rec(r: str) -> str:
    r = (r or "").strip().lower()
    return "" if r in ("", "none") else r


def phone_items(reading: dict) -> list[dict]:
    out = []
    for it in reading.get("items") or []:
        if not isinstance(it, dict):
            continue
        out.append({
            "kind": str(it.get("kind") or "other"),
            "title": str(it.get("title") or "").strip(),
            "date": str(it.get("date") or "").strip(),
            "start": _hhmm(str(it.get("start") or "")),
            "end": _hhmm(str(it.get("end") or "")),
            "recurrence": _rec(str(it.get("recurrence") or "")),
        })
    return out


def mac_items(resp: dict) -> list[dict]:
    """What the engine CREATED for this command, read back from the store it
    wrote to (the request's user is still bound here)."""
    from assistant.db import get_db
    db = get_db()
    out = []
    for c in resp.get("committed") or []:
        if not str(c.get("action", "")).startswith("create"):
            continue
        if c.get("kind") == "event":
            row = db.get_event(int(c["id"]))
            if not row:
                continue
            date = row.get("date", "")
            if row.get("series_id"):
                # a series is compared by its FIRST date, which is what the
                # phone's reading names
                try:
                    with db._conn() as conn:
                        first = conn.execute("SELECT MIN(date) FROM events WHERE series_id=?",
                                             (row["series_id"],)).fetchone()[0]
                    date = first or date
                except Exception:                       # noqa: BLE001
                    pass
            out.append({"kind": "event", "title": row.get("title", ""), "date": date,
                        "start": _hhmm(row.get("start_time", "")),
                        "end": _hhmm(row.get("end_time", "")),
                        "recurrence": _rec(row.get("recurrence", ""))})
        elif c.get("kind") == "todo":
            row = db.get_todo(int(c["id"]))
            if not row:
                continue
            out.append({"kind": "todo", "title": row.get("title", ""),
                        "date": row.get("due_date", "") or "", "start": "", "end": "",
                        "recurrence": ""})
    return out


def compare(phone: list[dict], mac: list[dict]) -> dict:
    """Pair each item the phone booked with one the Mac booked, and list what
    differs. Fields are compared only where the phone said something: an
    `end` the phone left empty is the Mac's default duration, not a
    disagreement."""
    booked = [p for p in phone if p["kind"] in MAY_COMMIT]
    left = list(mac)
    fields: list[str] = []
    unmatched: list[str] = []
    for p in booked:
        hit = next((m for m in left if m["kind"] == p["kind"]
                    and titles_match(p["title"], m["title"])), None)
        if hit is None:
            unmatched.append(p["title"])
            continue
        left.remove(hit)
        for f in ("date", "start", "recurrence"):
            if p[f] != hit[f]:
                fields.append(f)
        if p["end"] and hit["end"] and p["end"] != hit["end"]:
            fields.append("end")
    return {"fields": sorted(set(fields)), "phone_only": unmatched,
            "mac_only": [m["title"] for m in left]}


def attach(reading: Any, resp: Any, *, source: str = "", device: str = "") -> Any:
    """Add the `offline` block to a voice reply, and log the comparison.
    A reply without a reading, or a non-dict reply (an HTTP error), passes
    through untouched."""
    if isinstance(reading, str):
        try:
            reading = json.loads(reading)
        except ValueError:
            reading = None
    if not isinstance(reading, dict) or not isinstance(resp, dict):
        return resp

    phone = phone_items(reading)
    booked = [p for p in phone if p["kind"] in MAY_COMMIT]
    mac: list[dict] = []
    diff: dict = {}
    if reading.get("protocol") != PROTOCOL:
        verdict, said = "unverified", ""
    elif resp.get("parse") == "error" and resp.get("pending_id") is not None:
        verdict = "pending"
        said = ("Your Mac will read this itself as soon as its model is free — "
                "what the phone added stays until then.") if booked else ""
    elif not booked:
        verdict, said = "deferred", ""
    else:
        mac = mac_items(resp)
        diff = compare(phone, mac)
        same = not diff["fields"] and not diff["phone_only"] and not diff["mac_only"]
        verdict = "same" if same else "changed"
        said = ("" if same else
                "Your Mac read this differently, and its version replaced the phone's.")

    block = {"protocol": PROTOCOL, "verdict": verdict, "said": said,
             "mac_items": mac, "differences": diff}
    resp["offline"] = block
    try:
        log.append({
            "ts": time.time(), "source": source, "device": device,
            "reader": str(reading.get("reader") or ""),
            "spec_version": str(reading.get("spec_version") or ""),
            "schema": reading.get("schema"), "protocol": reading.get("protocol"),
            "phone_text": str(reading.get("text") or ""),
            "mac_text": resp.get("transcript") or "",
            "read_ms": reading.get("ms"),
            "phone_items": phone, "mac_items": mac,
            "verdict": verdict, "differences": diff,
            "mac_parse": resp.get("parse"),
        })
    except OSError:
        pass                    # a full disk must not fail the command itself
    return resp

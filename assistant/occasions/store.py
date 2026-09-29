"""Each person's own occasions, kept per user (``users.paths.resolve``).

    {"id", "kind", "title", "calendar": "gregorian"|"hebrew",
     "month", "day", "year"|None, "adar": "adar1"|"adar2"|"both"|None,
     "remind_days": int|None, "color": str|None, "note": str,
     "created_at", "updated_at"}

- ``kind``: birthday, anniversary, yahrzeit, countdown (a one-off date with
  "N days to …"), custom (any other yearly date).
- ``calendar``: a Hebrew-dated occasion stores pyluach's month number
  (Nisan = 1 … Adar = 12, Adar II = 13) and repeats by the Hebrew calendar.
- ``year``: optional — the year it started (birth year, wedding year, year
  of passing), in the same calendar; with it the banner counts the years.
- ``remind_days``: None follows Settings ▸ Occasions for the kind.

``MACALENDAR_OCCASIONS`` redirects the file; ``tests/conftest.py`` does.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import threading
import time
import uuid

from assistant.users import paths as _paths

PATH = pathlib.Path(os.environ.get("MACALENDAR_OCCASIONS")
                    or (pathlib.Path.home() / ".assistant_tools" / "occasions.json"))
KINDS = ("birthday", "anniversary", "yahrzeit", "countdown", "custom")
CALENDARS = ("gregorian", "hebrew")
ADAR = ("adar1", "adar2", "both")

_lock = threading.Lock()


def _path() -> pathlib.Path:
    return _paths.resolve(PATH)


def load() -> list[dict]:
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _save(recs: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(recs, indent=2, ensure_ascii=False))
    os.replace(tmp, p)


def clean(rec: dict) -> "tuple[dict | None, str]":
    """A valid record from what a client sent, or (None, why not)."""
    kind = str(rec.get("kind") or "").lower()
    if kind not in KINDS:
        return None, f"kind must be one of {', '.join(KINDS)}"
    title = str(rec.get("title") or "").strip()[:120]
    if not title:
        return None, "a name is needed (whose birthday, which anniversary …)"
    cal = str(rec.get("calendar") or "gregorian").lower()
    if cal not in CALENDARS:
        return None, "calendar must be gregorian or hebrew"
    try:
        month, day = int(rec.get("month")), int(rec.get("day"))
    except (TypeError, ValueError):
        return None, "month and day are needed"
    year = rec.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        return None, "year must be a number"
    if cal == "gregorian":
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None, "not a date"
        try:
            datetime.date(year or 2024, month, day)          # 2024: Feb 29 exists
        except ValueError:
            return None, "not a date"
    else:
        if not (1 <= month <= 13 and 1 <= day <= 30):
            return None, "not a Hebrew date (month 1 = Nisan … 12 = Adar, 13 = Adar II)"
    if kind == "countdown" and (cal != "gregorian" or not year):
        return None, "a countdown needs a full date"
    adar = rec.get("adar")
    if cal == "hebrew" and month in (12, 13):
        adar = adar if adar in ADAR else ("adar1" if kind == "yahrzeit" else "adar2")
    else:
        adar = None
    remind = rec.get("remind_days")
    try:
        remind = int(remind) if remind not in (None, "") else None
    except (TypeError, ValueError):
        return None, "remind_days must be a number"
    color = rec.get("color") or None
    if color and not (isinstance(color, str) and color.startswith("#") and len(color) in (4, 7)):
        return None, "colour must be like #ec4899"
    return {"kind": kind, "title": title, "calendar": cal, "month": month, "day": day,
            "year": year, "adar": adar, "remind_days": remind, "color": color,
            "note": str(rec.get("note") or "")[:500]}, ""


def add(rec: dict) -> "tuple[dict | None, str]":
    got, why = clean(rec)
    if got is None:
        return None, why
    now = time.time()
    got.update(id="o-" + uuid.uuid4().hex[:10], created_at=now, updated_at=now)
    with _lock:
        recs = load()
        recs.append(got)
        _save(recs)
    return got, ""


def update(oid: str, fields: dict) -> "tuple[dict | None, str]":
    with _lock:
        recs = load()
        for i, r in enumerate(recs):
            if r.get("id") == oid:
                got, why = clean(dict(r, **fields))
                if got is None:
                    return None, why
                got.update(id=oid, created_at=r.get("created_at"), updated_at=time.time())
                recs[i] = got
                _save(recs)
                return got, ""
    return None, "no such occasion"


def delete(oid: str) -> bool:
    with _lock:
        recs = load()
        kept = [r for r in recs if r.get("id") != oid]
        if len(kept) == len(recs):
            return False
        _save(kept)
        return True

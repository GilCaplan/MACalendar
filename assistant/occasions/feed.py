"""One list of all-day banners for a date range — what both apps draw.

    {"date", "title", "kind", "source", "color", "editable", "occasion_id"?,
     "years"?}

``source`` is "mine" for a person's own occasion (editable: its banner opens
the editor) or the computed calendar's name (jewish, national, christian,
islamic — switched and recoloured in Settings, not edited one by one).
Ranges are capped at 400 days: Daf Yomi alone is a banner a day.
"""

from __future__ import annotations

import datetime
import time

from assistant.occasions import calendars, dates, store

MAX_DAYS = 400
_cache: dict = {"at": 0.0, "cfg": None}


def _cfg():
    """The config, re-read at most every 2 s: the views ask on every refresh."""
    if time.time() - _cache["at"] > 2 or _cache["cfg"] is None:
        from assistant.config import load_config
        try:
            _cache.update(cfg=load_config(), at=time.time())
        except Exception:
            _cache["at"] = time.time()
    return _cache["cfg"]


def settings():
    cfg = _cfg()
    return getattr(cfg, "occasions", None) if cfg is not None else None


def holiday_types() -> set:
    """Which Jewish holiday categories show (display only)."""
    s = settings()
    return set(getattr(s, "holiday_types", None) or ["major", "minor", "fast", "modern"])


def shown_holidays(holidays: list) -> list:
    """The holidays a view should draw — Settings ▸ Occasions ▸ Jewish holidays."""
    types = holiday_types()
    return [h for h in holidays if getattr(h, "category", None) in types]


def banners(start: datetime.date, end: datetime.date, israel: "bool | None" = None,
            recs: "list | None" = None) -> list[dict]:
    if end < start:
        return []
    end = min(end, start + datetime.timedelta(days=MAX_DAYS))
    s = settings()
    colors = dict(getattr(s, "colors", None) or {})
    if israel is None:
        cfg = _cfg()
        israel = bool(getattr(getattr(cfg, "hebrew_calendar", None), "israel_holidays", True))
    out: list[dict] = []
    for rec in (store.load() if recs is None else recs):
        for occ in dates.occurrences(rec, start, end):
            out.append(dict(occ, kind=rec["kind"], source="mine", editable=True,
                            occasion_id=rec.get("id"),
                            color=rec.get("color") or colors.get(rec["kind"], "#8b5cf6")))
    computed = []
    if s is not None:
        if s.parasha:
            computed += calendars.parasha(start, end, israel)
        if s.omer:
            computed += calendars.omer(start, end)
        if s.rosh_chodesh:
            computed += calendars.rosh_chodesh(start, end)
        if s.daf_yomi:
            computed += calendars.daf_yomi(start, end)
        if s.country:
            computed += calendars.national(s.country, start, end)
        if s.christian:
            computed += calendars.christian(start, end)
        if s.islamic:
            computed += calendars.islamic(start, end)
    for b in computed:
        out.append(dict(b, kind=b["source"], editable=False,
                        color=colors.get(b["source"], "#64748b")))
    order = {"mine": 0, "jewish": 1, "national": 2, "christian": 3, "islamic": 4}
    return sorted(out, key=lambda b: (b["date"], order.get(b["source"], 9), b["title"]))


def countdowns(today: "datetime.date | None" = None) -> list[dict]:
    """Countdowns still ahead: {"id", "title", "date", "days_left"}, soonest first."""
    today = today or datetime.date.today()
    out = []
    for r in store.load():
        if r.get("kind") != "countdown":
            continue
        try:
            d = datetime.date(int(r["year"]), int(r["month"]), int(r["day"]))
        except (KeyError, TypeError, ValueError):
            continue
        if d >= today:
            out.append({"id": r["id"], "title": r["title"], "date": d.isoformat(),
                        "days_left": (d - today).days})
    return sorted(out, key=lambda c: c["days_left"])

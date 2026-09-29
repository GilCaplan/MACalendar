"""When each occasion falls: the civil dates of a yearly date in a range.

Three calendar facts decide it, each with the choice written down:

- **Feb 29** in a common year falls on Feb 28 (the day it would have been
  before March; the choice most people make).
- **Adar in a leap year** (two Adars): each Hebrew-dated occasion in Adar
  carries ``adar`` — adar1, adar2 or both. The defaults are the common
  customs: a yahrzeit in Adar I, a birthday or anniversary in Adar II. An
  occasion that began in Adar II of a leap year is Adar in a common year.
- **A 30th the month lacks** (Cheshvan and Kislev have 29 or 30 days, and
  Adar I has 30 while Adar has 29): the last day of that month.

A Hebrew date begins the evening before its civil date; banners sit on the
civil date, and a yahrzeit's reminder says it begins the evening before.
"""

from __future__ import annotations

import datetime

from pyluach import dates as _hd
from pyluach import hebrewcal as _hc


def gregorian_in(month: int, day: int, start: datetime.date, end: datetime.date):
    """(civil date, civil year) for each yearly Gregorian date in [start, end]."""
    for y in range(start.year, end.year + 1):
        try:
            d = datetime.date(y, month, day)
        except ValueError:                      # Feb 29 in a common year
            d = datetime.date(y, 2, 28)
        if start <= d <= end:
            yield d, y


def _hebrew_day(hy: int, month: int, day: int) -> "datetime.date | None":
    try:
        return _hd.HebrewDate(hy, month, day).to_pydate()
    except ValueError:
        pass
    for last in (29, 28):                       # the month is shorter this year
        try:
            return _hd.HebrewDate(hy, month, last).to_pydate()
        except ValueError:
            continue
    return None


def hebrew_months(hy: int, month: int, adar: "str | None") -> list[int]:
    """Which month(s) of Hebrew year ``hy`` hold an occasion stored in
    ``month`` (pyluach: 12 = Adar / Adar I, 13 = Adar II)."""
    leap = _hc.Year(hy).leap
    if month not in (12, 13):
        return [month]
    if not leap:
        return [12]                             # one Adar: Adar II falls there too
    if month == 13:
        return [13]
    return {"adar1": [12], "adar2": [13], "both": [12, 13]}.get(adar or "adar2", [13])


def hebrew_in(month: int, day: int, adar: "str | None", start: datetime.date, end: datetime.date):
    """(civil date, Hebrew year) for each yearly Hebrew date in [start, end]."""
    first = _hd.HebrewDate.from_pydate(start).year
    last = _hd.HebrewDate.from_pydate(end).year
    for hy in range(first, last + 1):
        for m in hebrew_months(hy, month, adar):
            d = _hebrew_day(hy, m, day)
            if d is not None and start <= d <= end:
                yield d, hy


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def occurrences(rec: dict, start: datetime.date, end: datetime.date) -> list[dict]:
    """The banners one occasion puts in [start, end]."""
    kind, title = rec.get("kind"), rec.get("title", "")
    out = []
    if kind == "countdown":
        try:
            d = datetime.date(int(rec["year"]), int(rec["month"]), int(rec["day"]))
        except (KeyError, TypeError, ValueError):
            return []
        if start <= d <= end:
            out.append({"date": d.isoformat(), "title": title, "years": None})
        return out
    if rec.get("calendar") == "hebrew":
        hits = hebrew_in(int(rec["month"]), int(rec["day"]), rec.get("adar"), start, end)
    else:
        hits = gregorian_in(int(rec["month"]), int(rec["day"]), start, end)
    for d, y in hits:
        years = (y - rec["year"]) if rec.get("year") and y >= rec["year"] else None
        out.append({"date": d.isoformat(), "title": banner_title(kind, title, years),
                    "years": years})
    return out


def banner_title(kind: str, title: str, years: "int | None") -> str:
    """"Dana's 30th birthday", "Gil & Dana — 5 years", "Yahrzeit · Grandpa"."""
    if kind == "birthday":
        if title.lower().endswith("birthday"):            # "My birthday"
            return title.replace("birthday", f"{ordinal(years)} birthday") if years and years > 0 else title
        if years and years > 0:
            return f"{title}'s {ordinal(years)} birthday"
        return f"{title}'s birthday"
    if kind == "anniversary":
        base = title if "anniversary" in title.lower() else f"{title} (anniversary)"
        if years:
            return f"{title} — {years} year{'s' if years != 1 else ''}"
        return base
    if kind == "yahrzeit":
        return f"Yahrzeit · {title}" + (f" ({years})" if years else "")
    return title

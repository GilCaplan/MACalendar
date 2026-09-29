"""Computed calendars: each a switch in Settings ▸ Occasions, all offline.

    jewish     parasha (each Shabbat), the Omer count, Rosh Chodesh, Daf Yomi
    national   a country's public holidays (the ``holidays`` package)
    christian  the main Western dates (Easter-based and fixed)
    islamic    the main dates by the Umm al-Qura Hijri calendar
               (``hijridate``) — "expected": local moon sighting can move
               them a day, and the banner says so

Each returns banners ``{"date", "title", "source"}`` for [start, end].
"""

from __future__ import annotations

import datetime
import logging

from pyluach import dates as _hd
from pyluach import parshios as _parshios

logger = logging.getLogger(__name__)

# -- Jewish weekly extras ----------------------------------------------------------


def parasha(start: datetime.date, end: datetime.date, israel: bool = True) -> list[dict]:
    out = []
    d = start + datetime.timedelta(days=(5 - start.weekday()) % 7)        # first Saturday
    while d <= end:
        name = _parshios.getparsha_string(_hd.HebrewDate.from_pydate(d), israel=israel)
        if name:
            out.append({"date": d.isoformat(), "title": f"Parashat {name}", "source": "jewish"})
        d += datetime.timedelta(days=7)
    return out


def omer(start: datetime.date, end: datetime.date) -> list[dict]:
    """Day N on the civil date of 15 Nisan + N (it is counted the evening
    before), days 1–49."""
    out = []
    for hy in {_hd.HebrewDate.from_pydate(start).year, _hd.HebrewDate.from_pydate(end).year}:
        first = _hd.HebrewDate(hy, 1, 16).to_pydate()
        for n in range(1, 50):
            d = first + datetime.timedelta(days=n - 1)
            if start <= d <= end:
                out.append({"date": d.isoformat(), "title": f"Omer · day {n}", "source": "jewish"})
    return out


def rosh_chodesh(start: datetime.date, end: datetime.date) -> list[dict]:
    """The 30th of a month (for the month after it) and the 1st of every
    month but Tishrei — 1 Tishrei is Rosh Hashana, its own holiday, and Elul
    never has a 30th."""
    out = []
    d = start
    while d <= end:
        hd = _hd.HebrewDate.from_pydate(d)
        month = None
        if hd.day == 30:
            month = (hd + 1).month_name()
        elif hd.day == 1 and hd.month != 7:
            month = hd.month_name()
        if month:
            out.append({"date": d.isoformat(), "title": f"Rosh Chodesh {month}",
                        "source": "jewish"})
        d += datetime.timedelta(days=1)
    return out


#: Daf Yomi (Bavli), in study order: (tractate, last daf). Each starts at daf 2,
#: except Kinnim, Tamid and Midot, which continue Meilah's numbering. 2,711
#: days per cycle (tests/unit/test_occasions.py checks the sum).
_DAF = [("Berachot", 64), ("Shabbat", 157), ("Eruvin", 105), ("Pesachim", 121),
        ("Shekalim", 22), ("Yoma", 88), ("Sukkah", 56), ("Beitzah", 40),
        ("Rosh Hashanah", 35), ("Taanit", 31), ("Megillah", 32), ("Moed Katan", 29),
        ("Chagigah", 27), ("Yevamot", 122), ("Ketubot", 112), ("Nedarim", 91),
        ("Nazir", 66), ("Sotah", 49), ("Gittin", 90), ("Kiddushin", 82),
        ("Bava Kamma", 119), ("Bava Metzia", 119), ("Bava Batra", 176),
        ("Sanhedrin", 113), ("Makkot", 24), ("Shevuot", 49), ("Avodah Zarah", 76),
        ("Horayot", 14), ("Zevachim", 120), ("Menachot", 110), ("Chullin", 142),
        ("Bechorot", 61), ("Arachin", 34), ("Temurah", 34), ("Keritot", 28),
        ("Meilah", 22)]
_DAF_TAIL = [("Kinnim", 23, 25), ("Tamid", 26, 33), ("Midot", 34, 37), ("Niddah", 2, 73)]
#: Cycle 14 began with Berachot 2 on 5 January 2020.
_DAF_EPOCH = datetime.date(2020, 1, 5)


def _daf_sequence() -> list[tuple[str, int]]:
    seq = [(t, d) for t, last in _DAF for d in range(2, last + 1)]
    seq += [(t, d) for t, a, b in _DAF_TAIL for d in range(a, b + 1)]
    return seq


_DAF_SEQ = _daf_sequence()


def daf_on(d: datetime.date) -> tuple[str, int]:
    return _DAF_SEQ[(d - _DAF_EPOCH).days % len(_DAF_SEQ)]


def daf_yomi(start: datetime.date, end: datetime.date) -> list[dict]:
    out = []
    d = start
    while d <= end:
        t, n = daf_on(d)
        out.append({"date": d.isoformat(), "title": f"Daf Yomi · {t} {n}", "source": "jewish"})
        d += datetime.timedelta(days=1)
    return out


# -- other calendars -------------------------------------------------------------------


def national(country: str, start: datetime.date, end: datetime.date) -> list[dict]:
    if not country:
        return []
    try:
        import holidays
        cal = holidays.country_holidays(country.upper(), years=range(start.year, end.year + 1))
    except Exception as exc:                       # unknown code, missing package
        logger.warning("no national holidays for %r: %s", country, exc)
        return []
    return [{"date": d.isoformat(), "title": name, "source": "national"}
            for d, name in sorted(cal.items()) if start <= d <= end]


def christian(start: datetime.date, end: datetime.date) -> list[dict]:
    from dateutil.easter import easter
    out = []
    for y in range(start.year, end.year + 1):
        e = easter(y)
        days = [(datetime.date(y, 1, 6), "Epiphany"),
                (e - datetime.timedelta(days=46), "Ash Wednesday"),
                (e - datetime.timedelta(days=7), "Palm Sunday"),
                (e - datetime.timedelta(days=2), "Good Friday"),
                (e, "Easter Sunday"),
                (e + datetime.timedelta(days=39), "Ascension Day"),
                (e + datetime.timedelta(days=49), "Pentecost"),
                (datetime.date(y, 11, 1), "All Saints' Day"),
                (datetime.date(y, 12, 24), "Christmas Eve"),
                (datetime.date(y, 12, 25), "Christmas Day")]
        out += [{"date": d.isoformat(), "title": n, "source": "christian"}
                for d, n in days if start <= d <= end]
    return sorted(out, key=lambda b: b["date"])


#: (Hijri month, day, name)
_ISLAMIC = [(1, 1, "Islamic New Year"), (1, 10, "Ashura"), (3, 12, "Mawlid"),
            (9, 1, "Ramadan begins"), (9, 27, "Laylat al-Qadr"), (10, 1, "Eid al-Fitr"),
            (12, 9, "Day of Arafah"), (12, 10, "Eid al-Adha")]


def islamic(start: datetime.date, end: datetime.date) -> list[dict]:
    try:
        from hijridate import Gregorian, Hijri
        first = Gregorian(start.year, start.month, start.day).to_hijri().year
        last = Gregorian(end.year, end.month, end.day).to_hijri().year
    except Exception as exc:                       # outside the table's years
        logger.warning("no Hijri dates for %s–%s: %s", start, end, exc)
        return []
    out = []
    for hy in range(first, last + 1):
        for m, dd, name in _ISLAMIC:
            try:
                g = Hijri(hy, m, dd).to_gregorian()
            except Exception:
                continue
            d = datetime.date(g.year, g.month, g.day)
            if start <= d <= end:
                out.append({"date": d.isoformat(), "title": f"{name} (expected)",
                            "source": "islamic"})
    return sorted(out, key=lambda b: b["date"])

""""HH:MM" and minutes since midnight — the arithmetic every clock site did by hand.

The conversion was identical in all ~14 copies; what differed was only what a
site does at the edge of the day, so that stays a CHOICE at the call site:

    to_hhmm(wrap_day(total))    past midnight -> the next day's clock
    to_hhmm(clamp_day(total))   past midnight -> 23:59, the day's last minute
    to_hhmm(total)              the caller already knows it stays in the day
"""
from __future__ import annotations

DAY = 24 * 60
LAST_MINUTE = DAY - 1


def to_minutes(hhmm: str) -> int:
    """"14:30" -> 870. Seconds, if present, are ignored."""
    h, m = (int(x) for x in str(hhmm).split(":")[:2])
    return h * 60 + m


def to_hhmm(total: int) -> str:
    """870 -> "14:30". No wrapping: pass `wrap_day` or `clamp_day` first."""
    return f"{total // 60:02d}:{total % 60:02d}"


def wrap_day(total: int) -> int:
    return total % DAY


def clamp_day(total: int) -> int:
    return min(total, LAST_MINUTE)

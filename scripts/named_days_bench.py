"""Named-day bench: does the engine put "dinner on erev Pesach" on the right day?

    python -m scripts.named_days_bench            # both halves
    python -m scripts.named_days_bench --negative # only the false-positive count

GENERATED, and which half is real: the FRAMES are ordinary event commands in
the shapes of the FastRule practice set, the NAMED-DAY phrases are written by
hand, and nothing here is observed speech — the observed half is the NEGATIVE
surface below, run over every corpus we have. The expected date of each phrase
is computed INDEPENDENTLY of assistant/named_days.py: a Hebrew date by scanning
civil days with pyluach until one matches, never through the holiday table the
reader uses, so a mistake in that table cannot agree with itself.

Two readers are scored, because a command reaches a date by one of two roads:

    fast   intent/rule_parser._extract_temporal — FastRule's date reading
    deep   segmentation's find_time_refs, then decompose_validate's
           resolve_date on the time words it cut — the deep track's
           deterministic half (the model's parse is not in it)

Metric: date-correct = the reader's date equals the expected date; n is rows
scored / total. Anchor: 2026-09-29 (mid-Sukkot 5787, a leap year — Adar II).

NEGATIVE: ``named_days.find_all`` over the FastRule 7,200 TRAIN half, the
verification pool's TRAIN rows and the real command history — every row it
fires on is printed, because a date read out of a name is a wrong date said
confidently.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

os.environ.setdefault("MACALENDAR_NO_WARMUP", "1")
os.environ.setdefault("MACALENDAR_LLM_DISABLED", "1")
os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = datetime.date(2026, 9, 29)


def _next_hebrew(month: int, day: int, frm: datetime.date = TODAY) -> datetime.date:
    """The first civil day on/after ``frm`` whose Hebrew date is (month, day);
    a plain Adar (12) in a leap year is matched in Adar II (13)."""
    from pyluach import dates as _hd, hebrewcal
    d = frm
    for _ in range(3 * 385):
        h = _hd.HebrewDate.from_pydate(d)
        want = month
        if month == 12 and hebrewcal.Year(h.year).leap:
            want = 13
        if h.month == want and h.day == day:
            return d
        d += datetime.timedelta(days=1)
    raise ValueError((month, day))


def _phrases() -> "list[tuple[str, datetime.date, str]]":
    """(phrase, expected date, shape) — the lead word is part of the phrase."""
    one = datetime.timedelta(days=1)
    out = []
    months = [("Nisan", 1), ("Nissan", 1), ("Iyar", 2), ("Sivan", 3), ("Tammuz", 4),
              ("Elul", 6), ("Tishrei", 7), ("Cheshvan", 8), ("Heshvan", 8), ("Kislev", 9),
              ("Tevet", 10), ("Teves", 10), ("Shevat", 11), ("Shvat", 11), ("Adar", 12)]
    for word, m in months:
        for day in (3, 12, 21):
            want = _next_hebrew(m, day)
            out.append((f"on {day} {word}", want, "hebrew-date"))
            out.append((f"on the {day}th of {word}" if day not in (3, 21, 1)
                        else f"on {word} {day}", want, "hebrew-date"))
    purim, pesach = _next_hebrew(12, 14), _next_hebrew(1, 15)
    hol = [
        ("Purim", purim), ("Shushan Purim", _next_hebrew(12, 15)),
        ("Pesach", pesach), ("Passover", pesach), ("Shavuot", _next_hebrew(3, 6)),
        ("Lag BaOmer", _next_hebrew(2, 18)), ("Tu BiShvat", _next_hebrew(11, 15)),
        ("Chanukah", _next_hebrew(9, 25)), ("Hanukkah", _next_hebrew(9, 25)),
        ("Rosh Hashana", _next_hebrew(7, 1)), ("Yom Kippur", _next_hebrew(7, 10)),
        ("Tisha B'Av", _next_hebrew(5, 9)), ("Tu B'Av", _next_hebrew(5, 15)),
        ("Pesach Sheni", _next_hebrew(2, 14)), ("Yom Yerushalayim", _next_hebrew(2, 28)),
        ("Shemini Atzeret", _next_hebrew(7, 22)), ("Simchat Torah", _next_hebrew(7, 22)),
        ("Hoshana Rabba", _next_hebrew(7, 21)),
    ]
    for name, first in hol:
        out.append((f"on {name}", first, "holiday"))
    for name, first in [("Pesach", pesach), ("Purim", purim), ("Yom Kippur", _next_hebrew(7, 10)),
                        ("Shavuot", _next_hebrew(3, 6)), ("Rosh Hashana", _next_hebrew(7, 1))]:
        out.append((f"on erev {name}", first - one, "erev"))
    for name, last in [("Yom Kippur", _next_hebrew(7, 10)), ("Purim", purim),
                       ("Shavuot", _next_hebrew(3, 6))]:
        out.append((f"the day after {name}", last + one, "day-after"))
    out += [("on the first night of Chanukah", _next_hebrew(9, 24), "ordinal"),
            ("on the third night of Chanukah", _next_hebrew(9, 26), "ordinal"),
            ("on the first day of Pesach", pesach, "ordinal"),
            ("on the last day of Chanukah", _next_hebrew(9, 25) + 7 * one, "ordinal"),
            ("on Rosh Chodesh Kislev", _next_hebrew(8, 30), "rosh-chodesh"),
            ("on Rosh Chodesh Sivan", _next_hebrew(3, 1), "rosh-chodesh"),
            ("on Rosh Chodesh Elul", _next_hebrew(5, 30), "rosh-chodesh"),
            ("on erev shabbat", datetime.date(2026, 10, 2), "shabbat"),
            ("motzei shabbat", datetime.date(2026, 10, 3), "shabbat"),
            ("on Easter", datetime.date(2027, 3, 28), "christian"),
            ("on Good Friday", datetime.date(2027, 3, 26), "christian")]
    return out


_FRAMES = [
    "dinner {p} at 7pm", "book the dentist {p} at 3pm", "schedule a meeting with Avi {p} at 10am",
    "family lunch {p} at 1pm", "shiur {p} at 8pm", "set up a call with the landlord {p} at 4pm",
    "put the kids' party on my calendar {p} at 5pm", "remind me to call mom {p}",
    "book haircut {p} at 11am", "add team sync {p} at 9am", "i have a doctor appointment {p} at 2pm",
    "schedule gym {p} at 6pm", "block the afternoon {p} for packing", "coffee with Dana {p} at 10am",
    "book a table for four {p} at 8pm", "can you add the book club {p} at 7:30pm",
    "set up piano lesson {p} at 4:30pm", "reminder to pay the bills {p}",
    "hike with the kids {p} at 9am", "movie night {p} at 9pm",
]


def positive() -> dict:
    from assistant.intent.rule_parser import _extract_temporal
    from assistant.engine.segmentation.fastseg.fastseg import find_time_refs
    from assistant.engine.decompose_validate.resolve import resolve_date
    rows = [(f.format(p=p), want, shape) for p, want, shape in _phrases() for f in _FRAMES]
    score = {"fast": {}, "deep": {}}
    wrong = {"fast": [], "deep": []}
    for text, want, shape in rows:
        try:
            got = _extract_temporal(text, TODAY).get("date")
        except Exception:
            got = None
        ok = got == want.isoformat()
        score["fast"].setdefault(shape, [0, 0])
        score["fast"][shape][0] += ok
        score["fast"][shape][1] += 1
        if not ok:
            wrong["fast"].append((text, got, want.isoformat()))
        # an item's time is ALL its time words, as segmentation hands them on
        when = " ".join(r.text for r in find_time_refs(text))
        got = resolve_date(when, TODAY) if when else None
        ok = got == want.isoformat()
        score["deep"].setdefault(shape, [0, 0])
        score["deep"][shape][0] += ok
        score["deep"][shape][1] += 1
        if not ok:
            wrong["deep"].append((text, got, want.isoformat()))
    return {"n": len(rows), "phrases": len(_phrases()), "frames": len(_FRAMES),
            "score": score, "wrong": wrong}


def _corpora() -> "dict[str, list[str]]":
    out = {}
    rows = [json.loads(l) for l in open(
        ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl")]
    out["FastRule 7,200 TRAIN"] = [r["text"] for r in rows if r.get("split") == "train"]
    pool = json.load(open(ROOT / "dataset/inputs/history_3000.json"))["rows"]
    sealed = {r[0] for r in json.load(open(ROOT / "dataset/inputs/test_split.json"))["rows"]}
    out["verification pool TRAIN"] = [r["text"] for r in pool if r["text"] not in sealed]
    return out


def negative() -> dict:
    from assistant import named_days
    fired = {}
    for name, texts in _corpora().items():
        hits = [(t, [n.name for n in named_days.find_all(t, TODAY)]) for t in texts]
        fired[name] = {"n": len(texts), "fired": [(t, n) for t, n in hits if n]}
    return fired


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--negative", action="store_true")
    a = ap.parse_args()
    print(f"# named-day bench · anchor {TODAY} · run {datetime.datetime.now():%Y-%m-%d %H:%M}")
    if not a.negative:
        pos = positive()
        print(f"\nPOSITIVE (generated): {pos['n']} rows = {pos['phrases']} phrases x "
              f"{pos['frames']} frames")
        for road in ("fast", "deep"):
            tot = sum(v[0] for v in pos["score"][road].values())
            print(f"  {road}: date-correct {tot}/{pos['n']} = {100 * tot / pos['n']:.1f}%")
            for shape, (ok, n) in sorted(pos["score"][road].items()):
                print(f"      {shape:13} {ok:4}/{n:<4}")
            for w in pos["wrong"][road][:8]:
                print(f"      wrong: {w}")
    try:
        neg = negative()
    except ImportError:
        print("\nNEGATIVE: skipped (no assistant.named_days at this commit)")
        return
    print("\nNEGATIVE (observed): rows where a named day is read")
    for name, v in neg.items():
        print(f"  {name}: {len(v['fired'])}/{v['n']}")
        for t, n in v["fired"][:20]:
            print(f"      {n} <- {t}")


if __name__ == "__main__":
    sys.exit(main())

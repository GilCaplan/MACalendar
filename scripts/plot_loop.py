"""Plot the improvement trajectory from dataset/loop_log.csv.

    python -m scripts.plot_loop            # writes dataset/loop_trajectory.png

One figure, two panels: count-correctness (overall + the compound slices +
complex tier) over the runs, and the newer metrics (F1, field quality) once
they exist.

A LINE MEANS ONE THING: these points are comparable to each other (2026-09-11).
Runs are grouped by `(era, slice)` and each group gets its own connected
segment, so the line never crosses a boundary the project has declared
uncrossable. That rule replaced a chart which drew ONE line through
everything and downgraded the disclaimers to marker styles — a connected line
is the strongest claim a time series makes ("the same thing, measured again"),
and a hollow marker is a footnote, so the old chart made the strong claim and
denied it in the weak channel. Four false deltas were visible on it:

    run  3 -> 4   76.8 -> 76.0   slice swap to dev-full-600, read as a dip
    run  6 -> 7   77.6 -> 78.0   same swap, read as a gain
    run 12 -> 13  80.0 -> 78.5   same swap — the biggest apparent drop in
                                 era 1, and not a regression at all
    run 15 -> 16  78.0 -> 77.0   the era-1/era-2 boundary, which the chart
                                 did not even draw. RESULTS.md on run 16:
                                 "headline flat within noise ... the real move
                                 is ROUTING SAFETY: fast correct 79->90"

(A fifth, run 20 -> 21 into the sealed 300, was fixed first and is what
exposed the rest.)

COMPARABILITY NOW LIVES IN THE DATA. `loop_log.csv` carries an `era` column;
this script no longer hardcodes where the boundaries are. It used to hold the
only machine-readable record of comparability in the repo — a single
`EPOCH_BOUNDARY_RUN = 8` — while the era-2 boundary existed solely as prose in
STATUS.md and so was never drawn at all. Declaring a new era is now a cell in
the log, next to the measurements it governs, rather than an edit to a
renderer someone has to remember to make.

Marker shapes still carry the slice, because which dataset a point measures is
worth seeing at a glance:

    filled circle   the tuning slice (dev-fast-250)
    hollow circle   a dev-full confirm — wider, harder, its own segment
    star            a sealed-set milestone — never joined to anything

A row with an EMPTY era forms its own group and is therefore drawn detached.
That is deliberate: an unstated comparability claim is not a claim, and
failing to a detached point is the safe direction.
"""
from __future__ import annotations

import csv
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG = pathlib.Path(__file__).resolve().parents[1] / "dataset" / "loop_log.csv"
OUT = LOG.parent / "loop_trajectory.png"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _style(slice_name: str) -> str:
    """Which dataset this point measures — "sealed", "devfull" or "tuning"."""
    if slice_name.startswith("sealed"):
        return "sealed"
    if slice_name.startswith("dev-full"):
        return "devfull"
    return "tuning"


def _segments(rows) -> "list[list[int]]":
    """Row indices grouped into runs that may be JOINED BY A LINE.

    Same era and same slice, in run order. Anything else is a different
    measurement and gets its own segment — which is also why the dev-full
    confirms finally read as a trajectory of their own (76.0 -> 78.0 -> 78.5)
    instead of as three interruptions in someone else's line.
    """
    groups: "dict[tuple, list[int]]" = {}
    for i, r in enumerate(rows):
        groups.setdefault((r.get("era", ""), r["slice"]), []).append(i)
    return list(groups.values())


def _boundaries(rows) -> "list[float]":
    """x positions where the era changes — read from the data, not hardcoded."""
    out = []
    for prev, cur in zip(rows, rows[1:]):
        if prev.get("era", "") != cur.get("era", ""):
            out.append((int(prev["run"]) + int(cur["run"])) / 2)
    return out


def _draw(ax, rows, x, series, marker_every: bool) -> None:
    segments = _segments(rows)
    for key, label, color in series:
        ys = [_f(r.get(key)) for r in rows]
        if not any(y is not None for y in ys):
            continue
        labelled = False
        for seg in segments:
            xs = [x[i] for i in seg]
            vals = [ys[i] for i in seg]
            if not any(v is not None for v in vals):
                continue
            # One legend entry per SERIES, not per segment.
            ax.plot(xs, vals, "-", color=color, alpha=.8,
                    label=None if labelled else label)
            labelled = True
        if not marker_every:
            continue
        for i, (xi, yi) in enumerate(zip(x, ys)):
            if yi is None:
                continue
            kind = _style(rows[i]["slice"])
            if kind == "sealed":
                ax.plot(xi, yi, "*", ms=13, mfc=color, mec="black", mew=.6)
            else:
                ax.plot(xi, yi, "o",
                        mfc="none" if kind == "devfull" else color, mec=color)


def main() -> int:
    rows = list(csv.DictReader(LOG.open()))
    if not rows:
        print("loop_log.csv is empty")
        return 1
    rows.sort(key=lambda r: int(r["run"]))
    x = [int(r["run"]) for r in rows]

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    _draw(a1, rows, x,
          [("overall_pct", "overall", "black"),
           ("complex_pct", "complex tier", "tab:red"),
           ("event_event_pct", "event+event", "tab:blue"),
           ("event_task_pct", "event+task", "tab:orange"),
           ("task_task_pct", "task+task", "tab:green")],
          marker_every=True)
    a1.set_ylabel("count-correct %")
    a1.legend(loc="lower right", fontsize=8)
    a1.grid(alpha=.3)

    _draw(a2, rows, x,
          [("f1_pct", "F1 (miss vs invent)", "tab:purple"),
           ("fieldq_pct", "field quality", "tab:brown"),
           ("when_ok_pct", "when-correct", "tab:red"),
           ("precision_pct", "precision", "tab:gray"),
           ("recall_pct", "recall", "tab:cyan")],
          marker_every=True)
    a2.set_ylabel("newer metrics %")
    a2.set_xlabel("run #  ·  a line joins only COMPARABLE runs (same era, same "
                  "slice)  ·  hollow = dev-full confirm, ★ = sealed set  ·  "
                  "dashed = era boundary")
    a2.legend(loc="lower right", fontsize=8)
    a2.grid(alpha=.3)

    bounds = _boundaries(rows)
    for ax in (a1, a2):
        for b in bounds:
            ax.axvline(b, ls="--", color="gray", alpha=.6)

    labels = {int(r["run"]): r["label"] for r in rows}
    a1.set_title("MACalendar engine — improvement loop trajectory\n"
                 + " · ".join(f"{k}:{v}" for k, v in list(labels.items())[:8]),
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT, dpi=140)
    eras = sorted({r.get("era", "") for r in rows})
    print(f"wrote {OUT} ({len(rows)} runs, {len(_segments(rows))} comparable "
          f"segments, eras {'/'.join(e or '?' for e in eras)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

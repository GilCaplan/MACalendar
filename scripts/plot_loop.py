"""Plot the improvement trajectory from dataset/loop_log.csv.

    python -m scripts.plot_loop            # writes dataset/loop_trajectory.png

One figure, two panels: count-correctness (overall + the compound slices +
complex tier) over the runs, and the newer metrics (F1, field quality) once
they exist. Epoch boundaries (harness changes that reset comparability) are
drawn as vertical lines — points across them are not comparable. Dev-full
confirm runs are hollow markers so the tuning slice and the wider slice are
never visually conflated.

SEALED runs are drawn as detached stars and the trend line BREAKS at them
(2026-09-11). They are a different dataset, not a later point on the tuning
slice: run 21 is the sealed 300 and every run around it is dev-fast-250, so
joining them draws a 79→83 "gain" that is really just a change of subject —
which is the same conflation the hollow dev-full markers already exist to
prevent, and the reason this file knows about slices at all.
"""
from __future__ import annotations

import csv
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG = pathlib.Path(__file__).resolve().parents[1] / "dataset" / "loop_log.csv"
OUT = LOG.parent / "loop_trajectory.png"

# runs at/after this run number are the frozen-clock epoch (2026-09-05)
EPOCH_BOUNDARY_RUN = 8


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    rows = list(csv.DictReader(LOG.open()))
    if not rows:
        print("loop_log.csv is empty")
        return 1
    x = [int(r["run"]) for r in rows]
    devfull = [r["slice"].startswith("dev-full") for r in rows]
    # A sealed run measures a DIFFERENT DATASET; it never joins the trend line.
    sealed = [r["slice"].startswith("sealed") for r in rows]

    def _line(ys):
        """The series with sealed points punched out, so the line breaks
        rather than implying continuity across a change of dataset."""
        return [None if s else y for y, s in zip(ys, sealed)]

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    series1 = [("overall_pct", "overall", "black"),
               ("complex_pct", "complex tier", "tab:red"),
               ("event_event_pct", "event+event", "tab:blue"),
               ("event_task_pct", "event+task", "tab:orange"),
               ("task_task_pct", "task+task", "tab:green")]
    for key, label, color in series1:
        ys = [_f(r.get(key)) for r in rows]
        a1.plot(x, _line(ys), "-", color=color, alpha=.8, label=label)
        for xi, yi, full, seal in zip(x, ys, devfull, sealed):
            if yi is None:
                continue
            if seal:
                a1.plot(xi, yi, "*", ms=13, mfc=color, mec="black", mew=.6)
            else:
                a1.plot(xi, yi, "o", mfc="none" if full else color, mec=color)
    a1.set_ylabel("count-correct %")
    a1.legend(loc="lower right", fontsize=8)
    a1.grid(alpha=.3)

    series2 = [("f1_pct", "F1 (miss vs invent)", "tab:purple"),
               ("fieldq_pct", "field quality", "tab:brown"),
               ("when_ok_pct", "when-correct", "tab:red"),
               ("precision_pct", "precision", "tab:gray"),
               ("recall_pct", "recall", "tab:cyan")]
    for key, label, color in series2:
        ys = [_f(r.get(key)) for r in rows]
        if not any(y is not None for y in ys):
            continue
        a2.plot(x, _line(ys), "o-", color=color, alpha=.8, label=label)
        for xi, yi, seal in zip(x, ys, sealed):
            if yi is not None and seal:
                a2.plot(xi, yi, "*", ms=13, mfc=color, mec="black", mew=.6)
    a2.set_ylabel("newer metrics %")
    a2.set_xlabel("run # (hollow = dev-full confirm; ★ = sealed set, a different "
                  "dataset — the line breaks there; dashed line = epoch reset)")
    a2.legend(loc="lower right", fontsize=8)
    a2.grid(alpha=.3)

    for ax in (a1, a2):
        ax.axvline(EPOCH_BOUNDARY_RUN - 0.5, ls="--", color="gray", alpha=.6)

    labels = {int(r["run"]): r["label"] for r in rows}
    a1.set_title("MACalendar engine — improvement loop trajectory\n"
                 + " · ".join(f"{k}:{v}" for k, v in list(labels.items())[:8]),
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT, dpi=140)
    print(f"wrote {OUT} ({len(rows)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

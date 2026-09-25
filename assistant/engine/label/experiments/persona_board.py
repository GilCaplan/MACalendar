"""Do the labellers work for people who are not the author?

    python -m assistant.engine.label.experiments.persona_board

## TEST-ONLY, AND THAT IS BINDING

`dataset/personas/PERSONAS.md` states the rule this file obeys:

> **TEST-ONLY. FOREVER.** No persona row is ever used to fit a model, select a
> feature, sweep a threshold, or seed a few-shot prompt — not the ones scored,
> not the ones that fail, not the banks they came from. A persona number may be
> **reported**; it may not **direct** a change.

So nothing here trains, tunes or selects. It reads, it scores, it prints. If a
spread here looks bad, the response is a QUESTION for DEVQA.md, not a change
fitted against these rows — a set you have optimised against cannot answer the
question it exists to answer.

## What it measures, and why it needs no category gold

The persona rows carry no category or tag labels, so accuracy is not available.
It is also not the interesting number. The interesting number is the **SPREAD**:
whether the labellers serve six different speakers equally, or whether they have
quietly been fitted to one.

Two label-free instruments do that:

    ABSTENTION   how often the model declines. It should decline at a similar
                 rate for everyone. Declining twice as often for the ESL
                 speaker means the model has learned one dialect.
    CATCH-ALL    how often the RULES fall through to Personal / no tag. Same
                 question asked of the incumbent, which is what makes the two
                 columns comparable.

The project already has a persona finding to check this against: *swapping
content nouns moves the classifiers 0-3 pt, swapping PHRASING moves them 7-29
pt*. Labelling is fed a TITLE rather than a whole utterance, so the prediction
is that phrasing barely reaches it and the spread should be small. That is a
falsifiable claim, which is the point of running it.
"""
from __future__ import annotations

import collections
import json
import pathlib

from assistant.common.scratch_env import scratch_env

_S = pathlib.Path(scratch_env(
    "persona_label_", keep=("LOCATION", "MODELS", "LABEL_FEEDBACK",
                            "HEARTBEATS", "HUD_STATE", "DEVICE_SECRET",
                            "DEVICES")))

REPO = pathlib.Path(__file__).resolve().parents[4]
PERSONAS = REPO / "dataset" / "personas" / "personas.jsonl"


def _titles():
    """`{persona: [(title, kind), …]}` from the persona rows' gold slots.

    The TITLE is used, not the whole utterance, because that is what the
    labellers are served in production (`db.auto_category_and_color` passes
    `intent.title`). Scoring them on full commands would measure a path that
    does not exist.
    """
    out: dict = collections.defaultdict(list)
    for line in PERSONAS.open():
        if not line.strip():
            continue
        r = json.loads(line)
        title = ((r.get("expect") or {}).get("slots") or {}).get("title")
        kind = (r.get("gold") or {}).get("kind")
        if title and kind in ("event", "task"):
            out[r["persona"]].append((str(title), kind))
    return out


def main() -> int:
    from assistant.actions.calendar import categories as _cat
    from assistant.actions.todo import tagging as _tag
    from assistant.engine.label.model import LabelModel

    by_persona = _titles()
    if not by_persona:
        print("no persona titles found — is dataset/personas/personas.jsonl present?")
        return 1

    ev_model = LabelModel.load("event")
    tk_model = LabelModel.load("task")
    tier = (ev_model.meta.get("tier") if ev_model else None) or "none"

    print("\n" + "=" * 78)
    print("PERSONA SPREAD — do the labellers serve everyone equally?")
    print("=" * 78)
    print(f"  model tier: {tier}   ·   TEST-ONLY: these rows may report, "
          f"never direct a change")
    print()
    print(f"  {'persona':<22}{'titles':>8}{'rules catch-all':>18}"
          f"{'model abstains':>17}")

    ev_rates, tk_rates = {}, {}
    for persona in sorted(by_persona):
        rows = by_persona[persona]
        ev = [t for t, k in rows if k == "event"]
        tk = [t for t, k in rows if k == "task"]

        catch = sum(1 for t in ev if _cat.classify(t) == "Personal")
        catch += sum(1 for t in tk if not _tag.suggest_tags(t, sorted(_tag.KEYWORDS)))
        abst = 0
        if ev_model:
            abst += sum(1 for t in ev if ev_model.predict(t) is None)
        if tk_model:
            abst += sum(1 for t in tk if tk_model.predict_tags(t) is None)
        n = len(rows)
        ev_rates[persona] = 100.0 * catch / n
        tk_rates[persona] = 100.0 * abst / n
        print(f"  {persona:<22}{n:>8}{ev_rates[persona]:>17.1f}%"
              f"{tk_rates[persona]:>16.1f}%")

    def spread(d):
        return max(d.values()) - min(d.values())

    print()
    print(f"  SPREAD  rules {spread(ev_rates):.1f} pt   ·   "
          f"model {spread(tk_rates):.1f} pt")
    print(f"          worst-served by the rules: "
          f"{max(ev_rates, key=ev_rates.get)}")
    print(f"          worst-served by the model: "
          f"{max(tk_rates, key=tk_rates.get)}")
    print()
    print("  A small spread means the labeller is not fitted to one dialect.")
    print("  A large one is a QUESTION for DEVQA.md, not a change to fit here.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

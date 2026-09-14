"""Stream a synthetic command to the thinking card, so you can watch it build.

Why this exists: the HUD is invisible until a command arrives, and a real
command needs the mic, the API and the model. This publishes a run to the real
`trace_bus.jsonl` the card is tailing, one step at a time, at roughly the pace
the engine produces them — so the live chain rail can be seen without saying
anything.

It publishes with `source: "test"`, which the card's History filters out by
default. That is deliberate: the card must ANIMATE (the live view reads every
kind), but the durable record of "what you actually asked the assistant" must
not gain commands you never gave.

    ./.venv/bin/python -m scripts.hud_demo            # the deep track
    ./.venv/bin/python -m scripts.hud_demo --fast     # the fast-path answer
"""

from __future__ import annotations

import argparse
import time

from assistant import trace_bus
from assistant.trace import BRAIN_VERSION

# (stage, title, detail, ms, data) — the engine-v3 chain, with the pauses a
# real deep-track run actually spends in each box.
DEEP: list[tuple] = [
    ("vocab", "Vocabulary", "1 correction: 'hakzaga' → 'Haxaga'", 12,
     {"transcript": "book gym tomorrow at 7 and remind me to buy milk"}),
    ("rule", "Rule parser", "Deferred (STRUCTURE) — more than one item", 41,
     {"confidence": 0.44, "reason_class": "STRUCTURE"}),
    ("rule", "Segmentation", "2 asks: 'book gym tomorrow at 7' · 'buy milk'", 380,
     {"segments": ["book gym tomorrow at 7", "buy milk"]}),
    ("validate", "Atomise · repair", "Both atomic — no further splitting", 95,
     {"atomic": True, "items": 2}),
    ("rule", "Build objects", "event: Gym · task: buy milk", 1120,
     {"items": [{"kind": "event", "title": "Gym"}, {"kind": "todo", "title": "buy milk"}]}),
    ("execute", "Write · label", "Gym → Fitness · buy milk → Groceries", 34,
     {"labels": {"Gym": "Fitness", "buy milk": "Groceries"}}),
    ("verify", "Judge", "Agrees: 2 items, both correct", 860,
     {"verdict": "agree"}),
    ("done", "Done", "2 items in 2.5 s · deep track", 0, {"path": "deep"}),
]

FAST: list[tuple] = [
    ("vocab", "Vocabulary", "No corrections needed", 9,
     {"transcript": "what do I have today"}),
    ("rule", "Rule parser", "Confident (0.95) — instant: query_schedule", 31,
     {"confidence": 0.95, "actions": ["query_schedule"]}),
    ("execute", "Query Schedule", "Gym at 07:00, NLP lecture at 10:00.", 3, None),
    ("done", "Fast answer", "rules answered in 0.0 s · reviewing in the background", 0,
     {"path": "fast"}),
]


def run(steps: list[tuple], transcript: str, message: str, speed: float) -> None:
    run_id = trace_bus.publish_begin("test")
    print(f"run {run_id} — watch the card")
    at = 0
    published = []
    for stage, title, detail, ms, data in steps:
        # The card animates because each step lands separately; sleeping the
        # step's own duration is what makes the rail advance at engine pace
        # rather than all at once.
        time.sleep(min(ms, 1500) / 1000.0 * speed)
        at += ms
        step = {"stage": stage, "title": title, "detail": detail,
                "ms": ms, "at_ms": at, "ok": True}
        if data:
            step["data"] = data
        trace_bus.publish_step(run_id, step)
        published.append(step)
        print(f"  → {stage:9} {title}")

    result = {"transcript": transcript, "message": message,
              "actions": [], "corrections": [], "brain": BRAIN_VERSION}
    trace_bus.publish_result(run_id, result)
    # The durable whole-run line the History view reads back, sharing the same
    # run id so the card does not draw the command twice.
    trace_bus.publish("test", published, result, run=run_id)
    print(f"  ✓ finished in {at} ms")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fast", action="store_true", help="the fast-path answer instead of the deep track")
    ap.add_argument("--speed", type=float, default=1.0, help="1.0 = engine pace, 2.0 = half speed")
    a = ap.parse_args(argv)
    print(f"publishing to {trace_bus.BUS_PATH}")
    if a.fast:
        run(FAST, "what do I have today", "Gym at 07:00, NLP lecture at 10:00.", a.speed)
    else:
        run(DEEP, "book gym tomorrow at 7 and remind me to buy milk",
            "Booked Gym tomorrow at 07:00 and added 'buy milk' to Today.", a.speed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

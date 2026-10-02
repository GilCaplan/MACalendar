"""PHONE ENGINE BOARD — how well does the phone read a command with no Mac?

    python -m scripts.phone_engine_board                 # TRAIN, base size
    python -m scripts.phone_engine_board --split test    # aggregates only
    python -m scripts.phone_engine_board --size 40k      # the bigger FastRule set
    python -m scripts.phone_engine_board --show 30       # print TRAIN misses
    python -m scripts.phone_engine_board --source hwu     # REAL speech: the 2,700 HWU-64 commands
                                                          # outside the sealed 300 (actions only)
    python -m scripts.phone_engine_board --board-d --split test   # Board D's rows, Board D's scorer:
                                                          # head to head with the Mac (llama3.1:8b)

**Component: the phone's `LocalEngine`** (MACalendar-iOS/Engine/LocalEngine.swift,
DEVQA Q85) — the reader a phone with no Mac uses. Scored on the FastRule set's
SINGLE-ASK rows (`expect.atomic`), the same gold the Mac's fast path is held
to, so the two can be read side by side.

Metrics (each over the rows it applies to, n printed beside it):

    action     op + kind match the gold action (create_event, create_todo,
               delete_event, update_event, complete_todo, query, …)
    title      a create's title equals the gold title (lower-cased, punctuation
               and a leading article ignored)
    target     an update/delete/complete names the gold row: the same content
               words once generic ones go ("vet appointment" = "vet"); a gold
               that names no row ("this reminder") wants an empty target —
               the phone then asks which, it never guesses
    repeat     the series cadence equals the gold `recurrence_rounded`
    clock      a stated time was read as a time (gold has a time_phrase and the
               action is create_event) — the reading's value is not checked:
               the gold carries phrases, not resolved clocks

`propose` rows ("find me a time …") are counted apart: the phone has no
proposer and reads them as creates.

TEST is the held-out half: its rows are never printed (CLAUDE.md).
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
IOS = ROOT / "MACalendar-iOS"
NOW = "2026-10-02T10:00:00"          # a Friday — fixed so a run is repeatable

GOLD_ACTION = {
    "create_event": ("create", "event"), "create_todo": ("create", "todo"),
    "delete_event": ("delete", "event"), "delete_todo": ("delete", "todo"),
    "update_event": ("update", "event"), "update_todo": ("update", "todo"),
    "complete_todo": ("complete", "todo"), "query": ("query", None),
}


def build(out: pathlib.Path) -> pathlib.Path:
    exe = out / "local_engine_cli"
    subprocess.run(["swiftc", "-O", "-parse-as-library",
                    str(IOS / "MACalendar-iOS/Engine/LocalEngine.swift"),
                    str(IOS / "Tools/local_engine_cli.swift"), "-o", str(exe)],
                   check=True, capture_output=True)
    return exe


def read_all(exe: pathlib.Path, texts: list[str]) -> list[dict]:
    payload = "".join(json.dumps({"text": t, "now": NOW}) + "\n" for t in texts)
    out = subprocess.run([str(exe)], input=payload, capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines()]


def norm(s: str | None) -> str:
    s = re.sub(r"[^\w\s']", " ", (s or "").lower())
    s = re.sub(r"^(?:the|a|an|my)\s+", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


GENERIC = {"the", "a", "an", "my", "that", "this", "it", "one", "appointment", "event", "reminder", "task",
           "todo", "to-do", "item", "entry", "thing"}


def words(s: str | None) -> set[str]:
    """Content words: what names a row once the generic ones are gone."""
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in norm(s).split() if w not in GENERIC}


def rows(size: str) -> list[dict]:
    if size == "base":
        path = ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl"
    else:
        from assistant.engine.fastrule.datasets import tiers
        path = tiers.ensure(size)
    return [json.loads(line) for line in open(path) if line.strip()]


HWU_EXPECT = {("calendar", "set"): [("create", None)], ("calendar", "query"): [("query", None)],
              ("lists", "query"): [("query", None)], ("calendar", "remove"): [("delete", None)],
              ("lists", "remove"): [("delete", None)], ("lists", "createoradd"): [("create", "todo")],
              ("compound", "event+event"): [("create", "event"), ("create", "event")],
              ("compound", "event+task"): [("create", "event"), ("create", "todo")],
              ("compound", "task+task"): [("create", "todo"), ("create", "todo")]}


def hwu_board(show: int) -> int:
    """Real speech (HWU-64, CC BY 4.0): does the phone take the right ACTION?

    Gold is the corpus's own intent; a compound must come out as exactly its
    two creates, of the right kinds. The sealed 300 (`test_split.json`) are
    removed by text and never read here. Titles are not scored — the corpus
    has no title gold."""
    sealed = {r[0] for r in json.load(open(ROOT / "dataset/inputs/test_split.json"))["rows"]}
    rows = [r for r in json.load(open(ROOT / "dataset/inputs/hwu64_sample.json"))["rows"] if r["text"] not in sealed]
    with tempfile.TemporaryDirectory() as tmp:
        got = read_all(build(pathlib.Path(tmp)), [r["text"] for r in rows])
    score = collections.defaultdict(lambda: [0, 0])
    miss = collections.defaultdict(list)
    for r, g in zip(rows, got):
        want = HWU_EXPECT.get((r["scenario"], r["intent"]))
        if not want:
            continue
        acts = g.get("actions") or []
        have = sorted((a.get("op"), a.get("kind")) for a in acts)
        if len(want) == 1:
            op, kind = want[0]
            ok = len(acts) == 1 and acts[0].get("op") == op and (kind is None or acts[0].get("kind") == kind)
        else:
            # a compound: TWO creates is the act; their kinds are scored apart,
            # because the corpus calls every "set a reminder" an event and the
            # rulings (Q25/Q26) do not
            ok = len(acts) == 2 and all(a.get("op") == "create" for a in acts)
            score["compound kinds exact"][1] += 1
            score["compound kinds exact"][0] += have == sorted(want)
        key = f'{r["scenario"]}/{r["intent"]}'
        score[key][1] += 1; score[key][0] += ok
        score["ALL"][1] += 1; score["ALL"][0] += ok
        if not ok:
            miss[key].append((r["text"], have))
    print(f"\nPHONE ENGINE BOARD — LocalEngine on REAL speech (HWU-64 outside the sealed 300, n={len(rows)})\n")
    for k, (hit, n) in sorted(score.items(), key=lambda kv: (kv[0] != "ALL", -kv[1][1])):
        print(f"  {k:<26} {100 * hit / n:5.1f}%  ({hit}/{n})")
    if show:
        for k, items in miss.items():
            print(f"\n  -- {k} misses ({len(items)}), first {show}:")
            for t, h in items[:show]:
                print(f"     {t!r}\n        got {h}")
    return 0


def board_d(split: str, n: int) -> int:
    """The phone on EXACTLY Board D's rows, scored by Board D's own `_correct`
    (right action AND the gold title's words) — so its headline sits beside
    the Mac's `--product` reading (llama3.1:8b, STATUS.md) on one yardstick.
    The rows: the FastRule set's `split`, actions create/update/delete/
    complete, shuffled with seed 31, first `n` — as `board_d.main` picks them."""
    import random
    from assistant.engine.llmjudge.experiments import board_d as bd
    rows = [json.loads(line) for line in bd.DATA.open()]
    rows = [r for r in rows if r["split"] == split
            and r["expect"].get("action", "").startswith(("create", "update", "delete", "complete"))]
    random.Random(31).shuffle(rows)
    rows = rows[:n]
    with tempfile.TemporaryDirectory() as tmp:
        got = read_all(build(pathlib.Path(tmp)), [r["text"] for r in rows])
    hit = 0
    by = collections.defaultdict(lambda: [0, 0])
    for r, g in zip(rows, got):
        outcome = []
        for a in g.get("actions") or []:
            if a.get("op") in ("create", "update", "delete", "complete"):
                title = a.get("title") if a["op"] == "create" else (a.get("new_title") or a.get("target") or "")
                outcome.append((f'{a["op"]}_{a.get("kind", "event")}', " ".join(str(title).lower().split())))
        ok = bd._correct(tuple(sorted(outcome)), r)
        hit += ok
        key = r["expect"]["action"]
        by[key][1] += 1; by[key][0] += ok
    print(f"\nPHONE ENGINE on BOARD D's rows ({split.upper()}, n={len(rows)}), Board D's scorer (action + title)\n")
    print(f"  headline correct          {100 * hit / len(rows):5.1f}%  ({hit}/{len(rows)})")
    for k, (h, m) in sorted(by.items(), key=lambda kv: -kv[1][1]):
        print(f"    {k:<16} {100 * h / m:5.1f}%  ({h}/{m})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", choices=("fastrule", "hwu"), default="fastrule")
    ap.add_argument("--board-d", action="store_true", help="Board D's rows and scorer (the Mac comparison)")
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--split", choices=("train", "test"), default="train")
    ap.add_argument("--size", default="base")
    ap.add_argument("--show", type=int, default=0, help="print this many TRAIN misses per metric")
    a = ap.parse_args(argv)
    if a.source == "hwu":
        return hwu_board(a.show)
    if a.board_d:
        return board_d(a.split, a.n)
    data = [r for r in rows(a.size) if r["split"] == a.split and r["expect"].get("atomic")]
    with tempfile.TemporaryDirectory() as tmp:
        exe = build(pathlib.Path(tmp))
        got = read_all(exe, [r["text"] for r in data])

    score = collections.defaultdict(lambda: [0, 0])          # metric -> [hit, n]
    by_action = collections.defaultdict(lambda: [0, 0])
    misses = collections.defaultdict(list)
    for r, g in zip(data, got):
        exp = r["expect"]
        act = exp["action"]
        acts = g.get("actions") or [{}]
        first = acts[0]
        slots = exp.get("slots", {})
        if act == "propose":
            score["propose read as create"][1] += 1
            score["propose read as create"][0] += first.get("op") == "create"
            continue
        if act not in GOLD_ACTION:
            continue
        op, kind = GOLD_ACTION[act]
        ok = first.get("op") == op and (kind is None or first.get("kind") == kind) and len(acts) == 1
        score["action"][1] += 1; score["action"][0] += ok
        by_action[act][1] += 1; by_action[act][0] += ok
        if not ok:
            misses["action"].append((r["text"], act, f'{first.get("op")}/{first.get("kind")} x{len(acts)}'))
        if op == "create" and slots.get("title"):
            hit = norm(first.get("title")) == norm(slots["title"])
            score["title"][1] += 1; score["title"][0] += hit
            if not hit:
                misses["title"].append((r["text"], slots["title"], first.get("title")))
        if op in ("update", "delete", "complete") and slots.get("title"):
            want = words(slots["title"])
            # "delete this reminder" names no row: the right answer is to ask
            hit = (want == words(first.get("target"))) if want else not words(first.get("target"))
            score["target"][1] += 1; score["target"][0] += hit
            if not hit:
                misses["target"].append((r["text"], slots["title"], first.get("target")))
        if slots.get("recurrence_rounded") or (op == "create" and first.get("recurrence")):
            hit = first.get("recurrence") == slots.get("recurrence_rounded")
            score["repeat"][1] += 1; score["repeat"][0] += hit
            if not hit:
                misses["repeat"].append((r["text"], slots.get("recurrence_rounded"), first.get("recurrence")))
        if act == "create_event" and slots.get("time_phrase"):
            hit = bool(first.get("start"))
            score["clock"][1] += 1; score["clock"][0] += hit
            if not hit:
                misses["clock"].append((r["text"], slots["time_phrase"], first.get("start")))

    print(f"\nPHONE ENGINE BOARD — LocalEngine on the FastRule set ({a.size}), "
          f"{a.split.upper()}, single-ask rows (n={len(data)})\n")
    for k in ("action", "title", "target", "repeat", "clock", "propose read as create"):
        hit, n = score[k]
        if n:
            print(f"  {k:<24} {100 * hit / n:5.1f}%  ({hit}/{n})")
    print("\n  action, per gold action:")
    for act, (hit, n) in sorted(by_action.items(), key=lambda kv: -kv[1][1]):
        print(f"    {act:<16} {100 * hit / n:5.1f}%  ({hit}/{n})")
    if a.show and a.split == "train":
        for k, items in misses.items():
            print(f"\n  -- {k} misses ({len(items)}), first {a.show}:")
            for t, want, have in items[:a.show]:
                print(f"     {t!r}\n        want {want!r}  got {have!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

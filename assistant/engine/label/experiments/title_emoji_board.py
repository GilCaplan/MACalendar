"""TITLE EMOJI BOARD — where does `title_emoji` fire, and is it the right sense?

    python -m assistant.engine.label.experiments.title_emoji_board [--dump PATH]

**Stage: label · `title_emoji` (a Component, TASKS 51).** A wrong emoji shows on
every screen a row is drawn on, so the NEGATIVE surface is read first: every
corpus of titles this project has, decorated at count 2, and what fired — by
word, with the distinct titles behind it. `--dump` writes every fired title
(and every title holding an ambiguous word that did NOT fire) for a read by eye.

    real titles         the user's own calendar and to-dos (read-only), and
                        `real_event_gold.jsonl`
    real commands       the 3,000-row verification pool's raw speech — not
                        titles, so a STRESS set: "update the date", "book a
                        table", "run the numbers" all live there
    generated titles    the FastRule 7,200 gold titles, the label datasets
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sqlite3

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
AMBIGUOUS = {"date", "book", "run", "running", "train", "call", "party", "apple", "drive", "car",
             "pool", "clean", "tea", "vet", "package", "delivery", "rent", "cookies", "study", "reading"}


def _real_titles() -> list[str]:
    from assistant.users.paths import personal_store
    out = []
    db = personal_store("calendar.db")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        out += [r[0] for r in con.execute("SELECT title FROM events") if r[0]]
        out += [r[0] for r in con.execute("SELECT title FROM todos") if r[0]]
        con.close()
    except sqlite3.Error:
        pass
    gold = HERE.parent / "datasets" / "real_event_gold.jsonl"
    out += [json.loads(l)["text"] for l in gold.open() if l.strip()]
    return out


def _commands() -> list[str]:
    d = json.loads((ROOT / "dataset/inputs/history_3000.json").read_text())
    return [r["text"] for r in d["rows"] if r.get("text")]


def _generated(data_tier: str = "base") -> list[str]:
    out = []
    for l in (ROOT / "assistant/engine/fastrule/datasets/fastrule_7200.jsonl").open():
        if not l.strip():
            continue
        t = (json.loads(l).get("expect", {}).get("slots") or {}).get("title")
        if t:
            out.append(t)
    from assistant.engine.label.datasets.generate import load_rows
    for kind, key in (("event", "subject"), ("task", "subject")):
        for r in load_rows(kind, data_tier):
            if r.get(key) or r.get("text"):
                out.append(r.get(key) or r["text"])
    return out


def main() -> int:
    from assistant.engine.label import title_emoji as te
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default="")
    ap.add_argument("--data-tier", default="base", choices=("base", "20k", "40k"),
                    help="which size of the label sets feeds 'generated titles'")
    a = ap.parse_args()
    corpora = {"real titles": _real_titles(), "real commands (stress)": _commands(),
               "generated titles": _generated(a.data_tier)}
    print("\nTITLE EMOJI BOARD — label stage, title_emoji at count 2\n")
    dump = []
    record = {}
    for name, rows in corpora.items():
        distinct = sorted(set(r.strip() for r in rows if r and r.strip()))
        fired = collections.Counter()
        fired_titles = collections.defaultdict(list)
        silent_ambiguous = []
        n_fired = 0
        for t in distinct:
            got = te.matches(t)[:2] if not te.has_emoji(t) else []
            if got:
                n_fired += 1
                for _end, emoji, w in got:
                    fired[(w.lower(), emoji)] += 1
                    fired_titles[(w.lower(), emoji)].append(t)
                dump.append({"corpus": name, "title": t, "out": te.decorate(t, 2)})
            words = set(w.lower() for w in __import__("re").findall(r"[\w']+", t))
            if words & AMBIGUOUS and not any(w.lower() in AMBIGUOUS for _e, _m, w in got):
                silent_ambiguous.append(t)
        print(f"{name}: {len(distinct)} distinct titles, {n_fired} decorated "
              f"({100 * n_fired / max(len(distinct), 1):.1f}%), {len(fired)} distinct (word, emoji) pairs")
        for (w, emoji), c in fired.most_common(12):
            print(f"    {c:>5}  {w} {emoji}")
        record[name] = {"distinct": len(distinct), "decorated": n_fired,
                        "pairs": {f"{w} {e}": c for (w, e), c in fired.items()},
                        "silent_ambiguous": len(silent_ambiguous)}
        dump += [{"corpus": name, "title": t, "out": t, "silent_ambiguous": True} for t in silent_ambiguous]
        print()
    if a.dump:
        pathlib.Path(a.dump).write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dump) + "\n")
        print(f"dump: {a.dump} ({len(dump)} rows)")
    import time
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M")
    (runs / f"title_emoji_board_{stamp}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
    print(f"record: runs/title_emoji_board_{stamp}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""A BIG bench for multi-word vocabulary repair.

    python -m scripts.vocab_repair_bench --stats
    python -m scripts.vocab_repair_bench --dump out.jsonl

WHY IT EXISTS. `dataset/realspeech/realspeech_1200.jsonl` carries REAL damaged
titles with their intended form — `expect.slots.title` against
`expect.slots.intended_title` — and that is the honest bench. But its bank has
only 26 damageable terms, so it yields **62 distinct pairs**. Gil, 2026-09-19:
*"I think you need more than 60 examples, like a thousand examples would
probably be more adequate."* He is right: a rewrite rule that changes words the
speaker actually said, invisibly, cannot be trusted on 62 cases.

WHAT IS REAL HERE AND WHAT IS NOT — read this before quoting a number.

  * The DAMAGE OPERATIONS are taken from the observed set, not invented. Every
    one of them is a shape that appears in `banks/speech.json`:
        boundary shift   'barista course'  -> 'bar rista course'
        syllable split   'kombucha order'  -> 'kom bootcha order'
        compound join    'ice cream'       -> 'icecream'
        letter corrupt   'cold brew'       -> 'Colbrew'   'book club' -> 'Book Lub'
  * The TERMS are invented — generic loanwords and compounds crossed with
    ordinary activity nouns. No word of Gil's real vocabulary appears, which is
    the same privacy constraint `gen_realspeech.py` enforces with `--leak-check`.

So this is a STRESS bench, not a real-usage one. The 62 real pairs stay the
PRIMARY number and are reported separately by `--real`; this one says whether a
rule generalises past them. Never sum the two.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REALSPEECH = ROOT / "dataset" / "realspeech" / "realspeech_1200.jsonl"

#: Words a speaker says that Whisper mangles — loanwords, and compounds whose
#: halves are ordinary. Generic on purpose (see the privacy note above).
HEADS = [
    "pilates", "espresso", "karate", "origami", "quinoa", "physiotherapy",
    "kombucha", "falafel", "croissant", "sudoku", "barista", "tempura",
    "acupuncture", "calligraphy", "capoeira", "ceviche", "chiropractor",
    "empanada", "flamenco", "gnocchi", "halloumi", "jiujitsu", "kayaking",
    "linguine", "macrame", "mahjong", "matcha", "meringue", "obstetrics",
    "orchestra", "paella", "parkour", "phlebotomy", "pierogi", "podiatry",
    "ramen", "risotto", "sauna", "shawarma", "sourdough", "taekwondo",
    "tahini", "tiramisu", "ukulele", "vinyasa", "wasabi", "yakitori", "zumba",
]
COMPOUNDS = [
    "cold brew", "ice cream", "dry cleaning", "book club", "car wash",
    "bike ride", "grocery store", "dog walk", "hair cut", "eye exam",
    "board game", "note book", "sun screen", "tool box", "rain coat",
]
#: What the term is FOR. These stay intact — the damage lands on the head,
#: which is what the real corpus shows.
TAILS = ["session", "class", "order", "run", "club", "practice", "delivery",
         "workshop", "appointment", "lesson", "night", "meetup"]

_VOWEL_RUN = re.compile(r"[aeiouy]+", re.I)


def _syllables(word: str) -> "list[str]":
    """Rough syllable chunks — a split after each vowel run, which is where a
    listener's ear puts a boundary and where the real damaged forms break
    ("kom | boot | cha", "pill | lattes")."""
    cuts, last = [], 0
    for m in _VOWEL_RUN.finditer(word):
        end = m.end()
        if end < len(word) and end - last >= 2:
            cuts.append(word[last:end])
            last = end
    cuts.append(word[last:])
    return [c for c in cuts if c] or [word]


def _boundary_shift(head: str) -> "str | None":
    """'barista' -> 'bar ista'. One space inserted at a syllable edge."""
    parts = _syllables(head)
    if len(parts) < 2:
        return None
    return parts[0] + " " + "".join(parts[1:])


def _syllable_split(head: str) -> "str | None":
    """'kombucha' -> 'kom boo cha'. Every syllable spaced."""
    parts = _syllables(head)
    return " ".join(parts) if len(parts) >= 3 else None


def _join(term: str) -> "str | None":
    """'ice cream' -> 'icecream'. Only meaningful for a compound."""
    return term.replace(" ", "") if " " in term else None


def _corrupt(word: str) -> "str | None":
    """'club' -> 'lub', 'group' -> 'grip'. One letter dropped, never the last
    and never from a word short enough for the loss to erase it."""
    if len(word) < 4:
        return None
    return word[0] + word[2:]


def pairs() -> "list[tuple[str, str]]":
    """[(damaged, intended)] — distinct, deterministic, no randomness."""
    out: "list[tuple[str, str]]" = []
    seen = set()

    def add(damaged, intended):
        damaged, intended = damaged.strip(), intended.strip()
        if not damaged or damaged.lower() == intended.lower():
            return
        if (damaged.lower(), intended.lower()) in seen:
            return
        seen.add((damaged.lower(), intended.lower()))
        out.append((damaged, intended))

    for i, head in enumerate(HEADS):
        for tail in TAILS[(i % 3):(i % 3) + 4]:      # 4 tails each, rotated
            clean = f"{head} {tail}"
            for damaged_head in (_boundary_shift(head), _syllable_split(head),
                                 _corrupt(head)):
                if damaged_head:
                    add(f"{damaged_head} {tail}", clean)
    for i, comp in enumerate(COMPOUNDS):
        for tail in ([""] + TAILS[(i % 4):(i % 4) + 3]):
            clean = f"{comp} {tail}".strip()
            a, b = comp.split(" ", 1)
            for damaged_comp in (_join(comp), _corrupt(a) and f"{_corrupt(a)} {b}",
                                 _corrupt(b) and f"{a} {_corrupt(b)}"):
                if damaged_comp:
                    add(f"{damaged_comp} {tail}".strip(), clean)
    return out


def real_pairs() -> "list[tuple[str, str]]":
    """The 62 REAL ones from the realspeech corpus. The primary number."""
    seen, out = set(), []
    for line in REALSPEECH.open():
        slots = (json.loads(line)["expect"].get("slots") or {})
        got = (slots.get("title") or "").strip()
        want = (slots.get("intended_title") or "").strip()
        if want and got and want.lower() != got.lower():
            if (got.lower(), want.lower()) not in seen:
                seen.add((got.lower(), want.lower()))
                out.append((got, want))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--dump")
    a = ap.parse_args()
    synth, real = pairs(), real_pairs()
    if a.dump:
        with open(a.dump, "w") as fh:
            for d, i in (real if a.real else synth):
                fh.write(json.dumps({"damaged": d, "intended": i}) + "\n")
        print(f"wrote {a.dump}")
        return 0
    print(f"REAL (realspeech gold, the primary number): {len(real)} distinct pairs")
    print(f"SYNTHETIC stress bench:                     {len(synth)} distinct pairs")
    print(f"   heads {len(HEADS)} · compounds {len(COMPOUNDS)} · tails {len(TAILS)}")
    if a.stats:
        for d, i in synth[:10]:
            print(f"   {d!r:34} -> {i!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

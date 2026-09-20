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

#: SOUND-PRESERVING LETTER SWAPS — the half of real damage that a boundary
#: move cannot imitate. The real corpus's pairs change LETTERS while keeping
#: the sound: 'quinoa' -> 'keen wah', 'karate' -> 'carrot day', 'falafel' ->
#: 'fell awful'. A bench that only moves boundaries is far too easy, and
#: calibration proved it — boundary-only damage repaired at 62% against 23%
#: for the real pairs, so tuning on it would have over-estimated everything.
#:
#: Each pair is reversible and phonetically neutral in English orthography.
_SOUND_SWAPS = [
    ("qu", "kw"), ("ph", "f"), ("c", "k"), ("ck", "k"), ("x", "ks"),
    ("oo", "ou"), ("ee", "ea"), ("ai", "ay"), ("oa", "oh"), ("ou", "oo"),
    ("y", "i"), ("s", "z"), ("tion", "shun"), ("ght", "t"), ("wh", "w"),
    ("ea", "ee"), ("au", "aw"), ("er", "ah"), ("ar", "ah"),
]


def _sound_swap(word: str, which: int) -> "str | None":
    """Apply ONE sound-preserving letter swap, chosen deterministically."""
    tried = 0
    for a, b in _SOUND_SWAPS:
        if a in word:
            if tried == which % max(1, sum(1 for x, _ in _SOUND_SWAPS if x in word)):
                out = word.replace(a, b, 1)
                return out if out != word else None
            tried += 1
    return None


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
            swapped = [_sound_swap(head, k) for k in range(3)]
            hard = []
            for sw in swapped:
                if not sw:
                    continue
                hard.append(sw)                          # letters changed
                bs = _boundary_shift(sw)                 # ...and the boundary
                if bs:
                    hard.append(bs)
                ss = _syllable_split(sw)                 # ...and fully spaced
                if ss:
                    hard.append(ss)
            for damaged_head in ([_boundary_shift(head), _syllable_split(head),
                                  _corrupt(head)] + hard):
                if damaged_head:
                    add(f"{damaged_head} {tail}", clean)
    # ...and Gil's own construction on top: mash the term's two words so the
    # letters survive and only the boundary moves, which still reads aloud as
    # what was said. Applied to the DISTINCTIVE terms, so the vocabulary entry
    # being matched against is the kind a person actually keeps.
    for i, head in enumerate(HEADS):
        for tail in TAILS[(i % 3):(i % 3) + 4]:
            for damaged in mash(head, tail):
                add(damaged, f"{head} {tail}")
    for i, comp in enumerate(COMPOUNDS):
        for tail in ([""] + TAILS[(i % 4):(i % 4) + 3]):
            clean = f"{comp} {tail}".strip()
            a, b = comp.split(" ", 1)
            for damaged_comp in (_join(comp), _corrupt(a) and f"{_corrupt(a)} {b}",
                                 _corrupt(b) and f"{a} {_corrupt(b)}"):
                if damaged_comp:
                    add(f"{damaged_comp} {tail}".strip(), clean)
    return out


#: How far the re-split boundary may move from the true one. Beyond two the
#: string stops sounding like the words — "icecream" split at 1 is "i cecream",
#: which nobody would hear.
_SHIFTS = (-2, -1, 1, 2)


def mash(a: str, b: str) -> "list[str]":
    """Two adjacent words, re-segmented so they SOUND the same and READ wrong.

    Gil's construction, 2026-09-19: *"take clean sentences, then every so often
    take two words and mash them up in a way that messes it up, but it sounds
    exactly the same as the original two words."*

    The letters are preserved exactly and only the boundary moves, so the
    string still reads aloud as what was said — which is precisely the damage
    Whisper produces, and why the real corpus contains "icecream" for "ice
    cream" and "Book Lub" for "book club". Joining is the zero-shift case.
    """
    joined = a + b
    out = [joined]
    for shift in _SHIFTS:
        k = len(a) + shift
        if 2 <= k <= len(joined) - 2:
            out.append(f"{joined[:k]} {joined[k:]}")
    return out


_WORD = re.compile(r"^[a-z]+$")


def in_sentence(limit: int = 0) -> "list[dict]":
    """[{damaged, clean, term, heard}] — a DISTINCTIVE term in a real sentence
    template, mashed.

    The first version of this drew its terms from adjacent word pairs in corpus
    sentences, which produced "vocabulary entries" like 'feed the' and 'book
    haircut'. Nobody's personal vocabulary contains those, so the corrector had
    absurd things to match against and the false-rewrite rate came out inflated
    — 15% at the shipped threshold, which said more about the bench than the
    code. A real vocabulary holds DISTINCTIVE terms: loanwords, compounds,
    names, personal shorthand.

    So the terms are the distinctive ones (`pairs()`), and the sentences are
    the realspeech corpus's own `clean` templates — the same templates the
    corpus was generated from, with their title slot filled. Both halves are
    then real: a real sentence shape carrying a real kind of term.
    """
    templates = []
    seen_t = set()
    for line in REALSPEECH.open():
        obj = json.loads(line)
        clean = (obj.get("clean") or "").strip()
        if "{event_title}" in clean or "{task_title}" in clean:
            if clean not in seen_t:
                seen_t.add(clean)
                templates.append(clean)
    if not templates:
        return []

    filled = {"{date}": "friday", "{time}": "9am", "{person}": "Dana",
              "{list}": "today", "{duration}": "an hour", "{place}": "the office"}

    def render(tpl: str, title: str) -> str:
        out = tpl.replace("{event_title}", title).replace("{task_title}", title)
        for slot, value in filled.items():
            out = out.replace(slot, value)
        return re.sub(r"\{[a-z_]+\}", "thing", out).strip()

    rows: "list[dict]" = []
    every = pairs()
    for i, (damaged, intended) in enumerate(every):
        tpl = templates[i % len(templates)]
        rows.append({"damaged": render(tpl, damaged), "clean": render(tpl, intended),
                     "term": intended, "heard": damaged})
        if limit and len(rows) >= limit:
            break
    return rows


def local_aliases() -> "list[tuple[str, str]]":
    """Mishearings the USER has confirmed, read from their vocabulary.

    These are the realest pairs that exist — each one is a wrong form the
    speaker personally corrected. Read at RUNTIME from outside the repo and
    never written into it, which is the same constraint `gen_realspeech.py`
    enforces with `--leak-check`: nothing personal is committed.
    """
    import os
    # DELIBERATELY the real file, not `MACALENDAR_VOCAB`. That override points
    # at the SCRATCH store under test — a sweep sets it before importing
    # anything — so honouring it here would read an empty vocabulary and
    # silently drop every real pair. Read-only, and never written back, which
    # is exactly what `gen_realspeech.py --leak-check` already does.
    path = os.path.expanduser("~/.assistant_tools/vocab.json")
    if os.environ.get("MACALENDAR_NO_LOCAL_ALIASES"):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    out = []
    for entry in (data.get("words") or data.get("entries") or []):
        word = (entry.get("word") or "").strip()
        for alias in (entry.get("aliases") or []):
            alias = (alias or "").strip()
            if word and alias and alias.lower() != word.lower():
                out.append((alias, word))
    return out


def real_pairs() -> "list[tuple[str, str]]":
    """The REAL ones: the realspeech corpus gold, plus the user's confirmed
    aliases when this machine has them. The primary number, and it is SMALL —
    about a hundred. It can never be the tuning signal; it is the check that
    the synthetic bench has not drifted away from reality."""
    seen, out = set(), []
    for line in REALSPEECH.open():
        slots = (json.loads(line)["expect"].get("slots") or {})
        got = (slots.get("title") or "").strip()
        want = (slots.get("intended_title") or "").strip()
        if want and got and want.lower() != got.lower():
            if (got.lower(), want.lower()) not in seen:
                seen.add((got.lower(), want.lower()))
                out.append((got, want))
    for got, want in local_aliases():
        if (got.lower(), want.lower()) not in seen:
            seen.add((got.lower(), want.lower()))
            out.append((got, want))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--dump")
    ap.add_argument("--context", action="store_true",
                    help="dump the in-sentence bench instead")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    synth, real = pairs(), real_pairs()
    if a.dump:
        with open(a.dump, "w") as fh:
            if a.context:
                for row in in_sentence(a.limit):
                    fh.write(json.dumps(row) + "\n")
            else:
                for d, i in (real if a.real else synth):
                    fh.write(json.dumps({"damaged": d, "intended": i}) + "\n")
        print(f"wrote {a.dump}")
        return 0
    ctx = in_sentence(a.limit)
    print(f"REAL (realspeech gold, the primary number): {len(real)} distinct pairs")
    print(f"SYNTHETIC term bench:                       {len(synth)} distinct pairs")
    print(f"IN-SENTENCE bench (clean corpus, one pair mashed): {len(ctx)} cases")
    print(f"   distinct terms {len({r['term'] for r in ctx})}"
          f" · distinct damaged forms {len({r['heard'] for r in ctx})}")
    print(f"   heads {len(HEADS)} · compounds {len(COMPOUNDS)} · tails {len(TAILS)}")
    if a.stats:
        for d, i in synth[:6]:
            print(f"   term  {d!r:30} -> {i!r}")
        for r in ctx[:6]:
            print(f"   ctx   {r['heard']!r:20} in {r['damaged'][:58]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

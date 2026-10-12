"""Give the flashcards that lack it an English translation (`en`), keeping progress.

    python scripts/flashcards_english.py export            # -> ~/Desktop/flashcards-english.json
    python scripts/flashcards_english.py export --out F    # anywhere OUTSIDE the repo
    python scripts/flashcards_english.py apply F           # -> the inbox, imported on next open

Gil, 2026-10-12, studying a Hebrew set: *"an additional English explanation to
the Hebrew … you're gonna have to translate for the card"*. A card's English
lives in its `en` field (FORMAT.md), which is not part of the card's identity,
so a set exported, given `en`, and imported again keeps every review.

1. `export` writes every set that has a card without `en` (skipping sets
   already in English) to ONE file, with the instructions for the translator
   at its top. The cards are the user's own study material: the file goes to
   the Desktop by default and is refused inside this checkout.
2. Someone translates: a Claude session given the file adds `en` to each
   card, mirroring its fields (`front`/`back`, `question`/`choices`/`answer`,
   `text` with the same `{{gaps}}`, `prompt`/`steps`, one string per occlusion
   label, and `explain` / `note`). Nothing else may change — a changed field
   would make a NEW card and drop that card's progress.
3. `apply` checks every card (the same `cardformat.normalise` the import
   uses), refuses a file whose cards were changed rather than translated, and
   writes each set into the flashcards inbox. The running assistant imports
   it the next time the tab opens; pictures already in a set stay where they
   are.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.features.flashcards import cardformat  # noqa: E402
from assistant.features.flashcards.store import FlashcardStore  # noqa: E402

INSTRUCTIONS = (
    "Add an English translation to every card as an `en` mapping that mirrors the card's own "
    "fields: text for text (front, back, text, question, answer, prompt, explain, note) and a "
    "list item for item (choices, steps, and `labels` as one string per label). A cloze's "
    "English `text` marks the same {{gaps}}. Translate the meaning naturally, keep technical "
    "terms accurate, and change NOTHING else in the file — a changed field makes a new card and "
    "loses its review progress. Leave cards that already have `en` as they are."
)

_LATIN_ONLY = re.compile(r"^[\x00-\x7FÀ-ɏ\s\W\d]*$")


def _store(path: "str | None") -> FlashcardStore:
    if path:
        return FlashcardStore(path)
    if os.environ.get("MACALENDAR_FLASHCARDS"):
        return FlashcardStore()
    from assistant.users.paths import personal_store
    return FlashcardStore(personal_store("flashcards.db"))


def _needs_english(card: dict) -> bool:
    if card.get("en"):
        return False
    words = " ".join(str(v) for k, v in card.items() if isinstance(v, str) and k not in ("type", "image", "ask"))
    return bool(words.strip()) and not _LATIN_ONLY.match(words)


def _outside_repo(path: pathlib.Path) -> None:
    try:
        path.resolve().relative_to(ROOT)
    except ValueError:
        return
    raise SystemExit(f"{path} is inside the repository, which is public. Write it somewhere else.")


def export(store: FlashcardStore, out: pathlib.Path) -> dict:
    _outside_repo(out)
    sets = []
    for sub in store.library():
        for s in sub.get("sets", []):
            doc = store.export_doc(s["id"])
            if any(_needs_english(c) for c in doc["cards"]):
                sets.append(doc)
    payload = {"instructions": INSTRUCTIONS, "sets": sets}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"sets": len(sets), "cards": sum(len(d["cards"]) for d in sets),
            "to_translate": sum(_needs_english(c) for d in sets for c in d["cards"])}


def apply(store: FlashcardStore, path: pathlib.Path) -> "list[str]":
    """Check the translated file and drop each set into the inbox. Returns the files written."""
    data = json.loads(path.read_text(encoding="utf-8"))
    written = []
    os.makedirs(store.inbox_dir, exist_ok=True)
    for doc in data.get("sets", []):
        name = f"{doc.get('subject')} / {doc.get('set')}"
        before = None
        for sub in store.library():
            for s in sub.get("sets", []):
                cur = store.export_doc(s["id"])
                if (cur["subject"], cur["set_id"]) == (doc.get("subject"), doc.get("set_id")):
                    before = cur
        if before is None:
            raise SystemExit(f"{name}: no such set on this Mac — was it renamed since the export?")
        old = {cardformat.key(cardformat.normalise(c)) for c in before["cards"]}
        changed = []
        for i, card in enumerate(doc["cards"]):
            clean = cardformat.normalise(card, where=f"{name}, card {i + 1}")
            if cardformat.key(clean) not in old:
                changed.append(i + 1)
        if changed:
            raise SystemExit(f"{name}: card(s) {changed[:10]} were changed, not only translated — "
                             "importing would reset their progress. Fix the file and run again.")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{doc.get('subject')}-{doc.get('set_id')}").strip("-")
        target = pathlib.Path(store.inbox_dir) / f"english-{slug or 'set'}.json"
        target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        written.append(str(target))
    return written


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", help="a flashcards.db other than your own (for trying it out)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--out", default=os.path.expanduser("~/Desktop/flashcards-english.json"))
    a = sub.add_parser("apply")
    a.add_argument("file")
    args = ap.parse_args(argv)
    store = _store(args.db)
    if args.cmd == "export":
        n = export(store, pathlib.Path(args.out))
        print(f"{n['to_translate']} cards need English, in {n['sets']} sets -> {args.out}")
        print("Translate it (add `en` to each card), then: "
              f"python scripts/flashcards_english.py apply {args.out}")
    else:
        for f in apply(store, pathlib.Path(args.file)):
            print("queued for import:", f)
        print("Open the Flashcards tab (Mac or phone) and they import; progress is kept.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

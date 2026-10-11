"""What a card is: the format a set file, an agent and the editor all write.

`FORMAT.md` beside this file is the human/agent-facing version of the same
rules, and `GET /flashcards/format` serves it — so an agent asked to "make me
flashcards for X" can read the contract from the running app rather than from
a stale copy. Every way a card gets in (import, the Mac editor, the phone's
editor, `POST /flashcards/sets/<id>/cards`) goes through `normalise()`, so
there is one definition of a valid card, not one per door.

A card can hold several STUDY ITEMS: each `{{blank}}` of a cloze, each label of
a one-at-a-time picture, and the reverse side of a `both_ways` card are
scheduled separately, because remembering one blank says nothing about the
next. `items()` names them; the review store keys progress on (card, item).
"""

from __future__ import annotations

import hashlib
import json
import re

TYPES = ("basic", "image", "cloze", "mc", "order", "typed", "occlusion")

#: Fields a card may carry whatever its type. None of them is part of the
#: card's IDENTITY (`key()`), so fixing a typo in an explanation or retagging
#: keeps your progress on it.
COMMON = ("tags", "page", "explain", "note")

REQUIRED = {
    "basic": ("front", "back"),
    "image": ("image", "back"),
    "cloze": ("text",),
    "mc": ("question", "choices", "answer"),
    "order": ("prompt", "steps"),
    "typed": ("front", "answer"),
    "occlusion": ("image", "labels"),
}
OPTIONAL = {
    "basic": ("both_ways",),
    "image": ("front", "both_ways"),
    "cloze": (),
    "mc": (),
    "order": (),
    "typed": (),
    "occlusion": ("ask", "prompt"),
}
CLOZE = re.compile(r"\{\{(.+?)\}\}", re.S)


class CardError(ValueError):
    """A card that cannot be stored, with a sentence saying which field and why."""


def _text(card: dict, field: str, where: str) -> str:
    v = card.get(field)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str) or not v.strip():
        raise CardError(f"{where}: '{field}' must be non-empty text.")
    return v.strip()


def normalise(card: dict, where: str = "card") -> dict:
    """A clean copy of `card`, or CardError naming what is wrong."""
    if not isinstance(card, dict):
        raise CardError(f"{where}: a card is a mapping, got {type(card).__name__}.")
    kind = str(card.get("type") or "basic").strip().lower()
    if kind not in TYPES:
        raise CardError(f"{where}: unknown type {kind!r} (one of {', '.join(TYPES)}).")
    allowed = set(REQUIRED[kind]) | set(OPTIONAL[kind]) | set(COMMON) | {"type"}
    extra = sorted(set(card) - allowed)
    if extra:
        raise CardError(f"{where}: {kind} card has unknown field(s) {', '.join(extra)}.")
    out: dict = {"type": kind}

    if kind in ("basic", "typed"):
        out["front"] = _text(card, "front", where)
        out["back" if kind == "basic" else "answer"] = _text(
            card, "back" if kind == "basic" else "answer", where)
    elif kind == "image":
        out["image"] = _text(card, "image", where)
        out["back"] = _text(card, "back", where)
        if card.get("front"):
            out["front"] = _text(card, "front", where)
    elif kind == "cloze":
        out["text"] = _text(card, "text", where)
        if not CLOZE.search(out["text"]):
            raise CardError(f"{where}: a cloze needs at least one {{{{blank}}}} in 'text'.")
    elif kind == "mc":
        out["question"] = _text(card, "question", where)
        choices = card.get("choices")
        if not isinstance(choices, list) or not 2 <= len(choices) <= 8:
            raise CardError(f"{where}: 'choices' must be a list of 2 to 8 answers.")
        out["choices"] = [str(c).strip() for c in choices]
        if len(set(out["choices"])) != len(out["choices"]) or not all(out["choices"]):
            raise CardError(f"{where}: 'choices' must be distinct and non-empty.")
        out["answer"] = _text(card, "answer", where)
        if out["answer"] not in out["choices"]:
            raise CardError(f"{where}: 'answer' {out['answer']!r} is not one of the choices "
                            "(it must match one character for character).")
    elif kind == "order":
        out["prompt"] = _text(card, "prompt", where)
        steps = card.get("steps")
        if not isinstance(steps, list) or not 2 <= len(steps) <= 20:
            raise CardError(f"{where}: 'steps' must be a list of 2 to 20 items, in the right order.")
        out["steps"] = [str(s).strip() for s in steps]
        if not all(out["steps"]):
            raise CardError(f"{where}: an order step is empty.")
    elif kind == "occlusion":
        out["image"] = _text(card, "image", where)
        labels = card.get("labels")
        if not isinstance(labels, list) or not labels:
            raise CardError(f"{where}: 'labels' must be a non-empty list of {{text, box}}.")
        clean = []
        for i, lab in enumerate(labels):
            lw = f"{where} label {i + 1}"
            if not isinstance(lab, dict):
                raise CardError(f"{lw}: must be a mapping with 'text' and 'box'.")
            box = lab.get("box")
            if (not isinstance(box, list) or len(box) != 4
                    or not all(isinstance(v, (int, float)) for v in box)):
                raise CardError(f"{lw}: 'box' must be [x, y, width, height] in percent of the picture.")
            x, y, w, h = (float(v) for v in box)
            if not (0 <= x <= 100 and 0 <= y <= 100 and 0 < w <= 100 and 0 < h <= 100
                    and x + w <= 100.5 and y + h <= 100.5):
                raise CardError(f"{lw}: 'box' {box} falls outside the picture (0-100%).")
            item = {"text": _text(lab, "text", lw), "box": [x, y, w, h]}
            if lab.get("tag"):
                item["tag"] = str(lab["tag"])
            clean.append(item)
        out["labels"] = clean
        ask = str(card.get("ask") or "one_at_a_time")
        if ask not in ("one_at_a_time", "all_at_once"):
            raise CardError(f"{where}: 'ask' is one_at_a_time or all_at_once, not {ask!r}.")
        out["ask"] = ask
        if card.get("prompt"):
            out["prompt"] = _text(card, "prompt", where)

    if card.get("both_ways") and kind in ("basic", "image"):
        out["both_ways"] = True
    tags = card.get("tags")
    if tags:
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list):
            raise CardError(f"{where}: 'tags' must be a list of words.")
        out["tags"] = [str(t).strip() for t in tags if str(t).strip()]
    if card.get("page") not in (None, ""):
        out["page"] = card["page"]
    for f in ("explain", "note"):
        if card.get(f):
            out[f] = str(card[f]).strip()
    return out


def items(card: dict) -> "list[str]":
    """The study items one card schedules separately ('' is the card itself)."""
    kind = card["type"]
    if kind == "cloze":
        return [f"c{i}" for i in range(len(CLOZE.findall(card["text"])))]
    if kind == "occlusion" and card.get("ask", "one_at_a_time") == "one_at_a_time":
        return [f"l{i}" for i in range(len(card["labels"]))]
    if card.get("both_ways"):
        return ["", "rev"]
    return [""]


def key(card: dict) -> str:
    """The card's identity across re-imports: its content minus the COMMON
    fields. Re-importing a corrected file keeps progress on every card whose
    substance did not change."""
    core = {k: v for k, v in card.items() if k not in COMMON}
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def images(card: dict) -> "list[str]":
    return [card["image"]] if card.get("image") else []

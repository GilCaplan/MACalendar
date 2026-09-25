"""Segmentation — the engine's step 2.

    text  ->  [Item(kind=tag, text=action, time=time, source=span), ...]

One implementation: FastSeg, deterministic, no model, with LLMSeg wired
behind it and OFF by default. The LLM-assisted `old_seg` that preceded it was
retired on 2026-09-20 — `retired/segmentation-old-seg/` holds it with a README,
and the tag `segmentation-old-seg` is the last commit that could run it.

THE SHAPE IT RETURNS
--------------------
`Item` carries `time` separately (added 2026-09-08 — a deliberate contract
change), so an item is `(kind=tag, text=action, time=time)` and the time is no
longer buried in the text.

Anything that PARSES an item for a date calls `Item.spoken()`, which is the
action with its time reattached. That matters: `FastRule` and the LLM parser both
extract the time from the string they are handed, so passing `text` alone
produced events with no time.

HOW A COMMAND GETS THROUGH
--------------------------
    1  envelope   transport delimiters (coalesced / batched / separator) — the
                  ingest queue wraps batches as ("a")and("b"), which is not
                  English and which FastSeg's cutter would return as ONE piece
    2  FastSeg    deterministic cut + tag, ~10ms, no model
    3  LLMSeg     the model half — OFF by default, so tier 2's answer stands
    4  ACCEPT     the invariant guard; a model answer that loses or invents a
                  word is reverted to FastSeg's

Tiers 2-4 are one call into `llmseg.segment`, which owns the flag, so there is
no second code path to keep in step.
"""
from __future__ import annotations

import re

from assistant.engine.state import Item

#: The transport envelopes opened before any segmenter runs: the ingest
#: queue's `("…")and("…")` coalescing wrapper (parentheses + quotes, because a
#: bare "and" very much can occur inside one command) and the phone's
#: `[…][…]` batches. The stage's own step, so the stage's own readers.
_COALESCE_RE = re.compile(r"\(\s*[\"“]([^\"“”]+)[\"”]\s*\)")
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")


def _envelope_split(text: str, cfg):
    """Transport delimiters, before any language is looked at.

    The ingest queue coalesces several commands into `("a")and("b")`, the phone
    sends bracket batches, and a user can configure a spoken separator. None of
    those are English, and FastSeg's cutter has never seen them — it returns the
    whole wrapper as ONE piece, which would collapse a batch of queued commands
    into a single item. So the envelope is opened first, with the stage's own
    reader, and FastSeg runs per envelope.
    """
    hits = _COALESCE_RE.findall(text)
    if len(hits) > 1:
        return [s.strip() for s in hits if s.strip()], "coalesced"
    hits = _BRACKET_RE.findall(text)
    if len(hits) > 1:
        return [s.strip() for s in hits if s.strip()], "batched"
    separator = (getattr(getattr(cfg, "audio", None), "event_separator", "") or "").strip()
    if separator:
        import re
        parts = [s.strip() for s in
                 re.split(re.escape(separator), text, flags=re.IGNORECASE)
                 if s.strip()]
        if len(parts) > 1:
            return parts, "separator"
    return [text.strip()], None


def _segment_items(text: str):
    """One envelope -> [(action, time, tag)] — the component, both halves.

    `llmseg.segment` IS the component: it runs FastSeg, then LLMSeg, then the
    deterministic ACCEPT guard, and it honours `llmseg.ENABLED` itself. With the
    flag off it returns FastSeg's answer and makes no model call, so this one
    call is the whole chain either way and there is no second code path to keep
    in step.
    """
    from assistant.engine.segmentation.llmseg.llmseg import segment

    out = segment(text)
    # The fourth value is the VERBATIM span the item was cut from — see
    # `fastseg._source_piece`. It falls back to the action so a component that
    # does not supply one still satisfies the contract.
    return [(i["action"], i["time"], i["tag"], i.get("source") or i["action"])
            for i in out["items"]]


#: HOW TWO NEIGHBOURING ITEMS RELATE — the reason segmentation cut there
#: (DEVQA Q51, Gil 2026-09-25: *"if we decide to segment, at least we know the
#: reason why. Then if we need to fix it … we know what the relationship is"*).
#: Read off the words BETWEEN the two items' verbatim spans, so it describes
#: whatever cut them — FastSeg, LLMSeg, or the ingest envelope.
#:
#:   sequence     one after the other: "followed by", "then", "after that"
#:   list         side by side: "and", a comma, "also", "plus"
#:   sentence     a new sentence: ". ", "; ", "? "
#:   envelope     separate utterances the ingest queue joined ("a")and("b")
#:   same_span    cut from one span: an enumeration ("the dog at 9 and 2:30")
#:   adjacent     nothing between them at all
_SEQUENCE_WORDS = re.compile(
    r"\b(?:followed\s+by|then|after\s+that|afterwards|after\s+which|next)\b", re.I)
_SENTENCE_MARK = re.compile(r"[.;!?]")
_LIST_WORDS = re.compile(r"\band\b|,|\balso\b|\bplus\b|\bas\s+well\s+as\b", re.I)


def relate(text: str, items: list, envelope_of: "dict | None" = None) -> None:
    """Write `item.relation` on every item after the first:
    `{"to": <the item before>, "kind": <above>, "words": <what was between>}`.
    The first item has none. Never raises: a span it cannot find is `unknown`."""
    low = (text or "").lower()
    cursor = 0
    prev = None
    prev_end = 0
    for it in items:
        src = (it.source or it.text or "").lower().strip()
        at = low.find(src, cursor) if src else -1
        if at < 0 and src:
            at = low.find(src)
        if prev is not None:
            if envelope_of and envelope_of.get(it.id) != envelope_of.get(prev.id):
                kind, words = "envelope", ""
            elif src and (prev.source or prev.text or "").lower().strip() == src:
                kind, words = "same_span", ""
            elif at < 0:
                kind, words = "unknown", ""
            else:
                words = (text or "")[prev_end:at].strip() if at >= prev_end else ""
                from assistant.intent.sequence import is_sequence_words
                # a verb-led seam ends in its seam word: "…and after", "…when finished"
                verb_led = re.search(r"\b(?:after|when\s+(?:finished|done)|once\s+finished)\s*$",
                                     words, re.I)
                kind = ("sequence" if (verb_led or is_sequence_words(words))
                        else "sentence" if _SENTENCE_MARK.search(words)
                        else "list" if _LIST_WORDS.search(words)
                        else "adjacent" if not words else "unknown")
            # A POSTPOSED marker ("…, product demo after that") orders the item
            # from its own end; the comma before it is only the seam.
            from assistant.intent.sequence import trailing_marker
            tail = trailing_marker(it.text or "")
            if tail and kind in ("list", "adjacent", "unknown", "sentence"):
                kind, words = "sequence", tail.group(0).strip()
            if tail and tail.group("m"):
                it.text = (it.text or "")[:tail.start()].rstrip(" ,") or it.text
            if kind == "sequence":
                # "…then FINALLY gym": the word orders the sequence, not the title.
                it.text = re.sub(r"^\s*(?:finally|lastly)\b,?\s*", "", it.text or "",
                                 flags=re.I) or it.text
                if prev is items[0]:
                    # "FIRST walk the dog, then lunch": the same, on the first item.
                    prev.text = re.sub(r"^\s*first(?:\s+of\s+all)?,?\s+", "", prev.text or "",
                                       flags=re.I) or prev.text
            it.relation = {"to": prev.id, "kind": kind, "words": words}
        if at >= 0:
            cursor = at
            prev_end = at + len(src)
        prev = it


def run(state, cfg):
    """Step 2. Envelope split, then the component, then Items."""
    from assistant.engine.segmentation.fastseg.kind import kind_of
    from assistant.trace import RULE

    envelopes, how = _envelope_split(state.text, cfg)
    # A transport delimiter must not survive into a title, so the working
    # transcript becomes the joined envelopes. Nothing to strip when none fired.
    if how:
        state.text = " ".join(envelopes)

    items: "list[Item]" = []
    envelope_of: "dict[str, int]" = {}
    for e_i, envelope in enumerate(envelopes):
        for action, when, tag, source in _segment_items(envelope):
            # `other` is one of ITEM_KINDS and is passed THROUGH. It used to fall
            # to the else branch and be re-read as an event, which threw away the
            # one verdict that says "this is not a calendar ask at all" — so the
            # tag existed in the contract and nothing could ever produce it.
            kind = tag if tag in ("event", "task", "review", "other") else kind_of(action)
            items.append(Item(id=f"item_{len(items) + 1}", kind=kind,
                              text=action, time=when, source=source))
            envelope_of[items[-1].id] = e_i
            if kind == "other":
                # WHY it was thrown out, so the trace and the review can say
                # (Gil, 2026-09-25: "just mark so we can see why").
                from assistant.intent.junk import junk_reason
                why = junk_reason(action)
                if why:
                    items[-1].slots["junk"] = why

    if not items:                      # never hand on an empty decomposition
        items = [Item(id="item_1", text=state.text, source=state.text,
                      kind=kind_of(state.text))]
    relate(state.text, items, envelope_of)
    state.items = items

    if state.trace:
        state.trace.step(RULE, "Split into commands",
                         f"{len(items)} item(s)" + (f" ({how})" if how else "")
                         + ": " + " · ".join(it.spoken()[:40] for it in items))
    return state

"""Ingest, half two: several queued commands become ONE input.

Extracted from the orchestrator so that both halves of ingest — the queue and
the word repair — live together. `test_engine_flow.py` pins the budget, the
overflow and the single-input case.

## Coalescing is scoped to ONE SOURCE, and that is a correctness rule

Gil, 2026-09-10: *"each device / test sandbox should be treated as a different
prompt and should never be concatenated — this concatenation is only for
multiple prompts queued from the same device."*

The functions here take a list of texts and know nothing about where they came
from, so **the caller must not hand them a mixed list.** The pending-retry loop
groups by `pending.source` first. Three things go wrong if it does not, and all
three are silent:

    a TEST prompt merges with a REAL one   the sandbox's words execute as the
                                           user's command, on the real calendar
    the Mac's merges with the phone's      two devices, two intents, one parse
    the batch is attributed to one source  which defeats `weekly_review.py`'s
                                           test-traffic filter — the thing that
                                           was inflating real-usage accuracy to
                                           83% until it was added

`coalesce_groups` exists so the caller can map a batch back to the exact rows
that went into it. The previous mapping counted `")and("` occurrences in the
rendered string to re-derive the group size, which desynchronises the moment a
transcript contains that literal — a wrong row then gets marked done.
"""
from __future__ import annotations


def coalesce_groups(texts: "list[str]", max_tokens: int = 300) -> "list[list[str]]":
    """The batches, still as lists — so a caller can tie each one back to its
    rows without parsing the rendered string."""
    groups: "list[list[str]]" = []
    current: "list[str]" = []
    used = 0
    for text in texts:
        t = (text or "").strip()
        if not t:
            continue
        cost = max(1, len(t) // 4)
        if current and used + cost > max_tokens:
            groups.append(current)
            current, used = [], 0
        current.append(t)
        used += cost
    if current:
        groups.append(current)
    return groups


def coalesce(texts: "list[str]", max_tokens: int = 300) -> "list[str]":
    """Queued inputs combined into ("…")and("…") batches up to a token budget
    (≈4 chars/token), so several short queued commands cost one parse instead
    of several; overflow runs in later batches. The wrapper is deterministic
    for segmentation to split — each command's logic stays independent.

    **All of `texts` must come from the SAME source.** See the module docstring.
    """
    return [wrap(g) for g in coalesce_groups(texts, max_tokens)]


def wrap(parts: "list[str]") -> str:
    if len(parts) == 1:
        return parts[0]
    return "and".join(f'("{p}")' for p in parts)


#: The old private name, kept because tests and the orchestrator import it.
_wrap = wrap

"""Ingest, half two: several queued commands become ONE input.

Extracted from the orchestrator so that both halves of ingest — the queue and
the word repair — live together. Behaviour is unchanged; `test_engine_flow.py`
pins the budget, the overflow and the single-input case.
"""
from __future__ import annotations


def coalesce(*args, **kwargs):
    """Logged wrapper — see `_coalesce_impl` for the batching itself.

    This is the ONE place in the system where several transcripts really are
    concatenated into `("a")and("b")`, and its single production caller is the
    pending-retry loop. Worth seeing in the console precisely because it is
    rare and surprising: a reader watching a batch appear wants to know what
    went in, what came out, and against what budget.
    """
    from assistant import llm_bus as _bus
    out = _coalesce_impl(*args, **kwargs)
    try:
        texts = args[0] if args else kwargs.get("texts") or []
        if len(out) != len(texts):
            _bus.note("coalesce",
                      f"{len(texts)} transcript(s) batched into {len(out)}",
                      n_in=len(texts), n_out=len(out),
                      batches=[b[:200] for b in out][:5])
    except Exception:
        pass
    return out


def _coalesce_impl(texts: "list[str]", max_tokens: int = 300) -> "list[str]":
    """Queued inputs combined into ("…")and("…") batches up to a token budget
    (≈4 chars/token), so several short queued commands cost one parse instead
    of several; overflow runs in later batches. The wrapper is deterministic
    for segmentation to split — each command's logic stays independent."""
    batches: list[str] = []
    current: list[str] = []
    used = 0
    for text in texts:
        t = (text or "").strip()
        if not t:
            continue
        cost = max(1, len(t) // 4)
        if current and used + cost > max_tokens:
            batches.append(_wrap(current))
            current, used = [], 0
        current.append(t)
        used += cost
    if current:
        batches.append(_wrap(current))
    return batches


def _wrap(parts: "list[str]") -> str:
    if len(parts) == 1:
        return parts[0]
    return "and".join(f'("{p}")' for p in parts)

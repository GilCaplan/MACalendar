# segmentation-old-seg — the LLM-assisted segmenter, retired 2026-09-20

`old_seg/segment.py` was the engine's step 2 until FastSeg was promoted on
2026-09-08, and stayed wired behind `MACALENDAR_SEGMENTATION=old_seg` as a
rollback path until today. Gil: *"we are talking just about fastseg, the
oldseg is retired."*

What is here:

- `old_seg/` — the module as it last ran, verbatim. It imports its kind
  vocabulary from `assistant/engine/segmentation/fastseg/kind.py`, where that
  block moved on 2026-09-20 (the live tagger had been importing it from here).
  Its interrogative-create reader moved to
  `assistant/engine/decompose_validate/object_rules.py`, its one caller.
- `old_vs_new.py` — the board that compared it with FastSeg (measured 86.1%
  exact-set against FastSeg's, `segmentation/ARCHITECTURE.md` §6).
- `tests/test_old_seg_segment.py` — its unit tests as they were, kept as a
  record; the live stage's tests stayed in `tests/unit/test_engine_segment.py`.

**The tag `segmentation-old-seg` is the last commit that could run it** —
check that out to revert or compare. This folder is the quick reference.

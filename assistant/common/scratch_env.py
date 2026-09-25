"""The one scratch-environment preamble every board, experiment and generator
needs before it may import anything from `assistant`.

An audit (2026-09-25) found ~56 scripts under `scripts/` and
`assistant/engine/*/experiments/` (some under `datasets/`) that each hand-roll
the same block: `tempfile.mkdtemp(...)`, a loop pointing the personal stores at
files inside it, `MACALENDAR_NO_WARMUP=1`, `MACALENDAR_LLM_PRIORITY=background`,
sometimes a BLAS thread pin, sometimes a seed or the observance flag. Fifty-six
independent copies is fifty-six chances for one of them to quietly miss a store
CLAUDE.md added later (`MACALENDAR_HEARTBEATS` and `MACALENDAR_HUD_STATE`
joined the list 2026-09-25, and most of the existing boards predate them) — and
`scripts/persona_board.py` was getting its whole environment as an IMPORT-TIME
SIDE EFFECT of importing `fastrule_shape`, which worked only as long as nobody
reordered the imports.

This module is the one place that preamble lives now. Its only imports are
`os` and `tempfile` — it must never import anything from `assistant`, because
half its callers exist to redirect `assistant`'s store paths BEFORE any of
`assistant` is imported, and importing this module is the first line of that.
"""

from __future__ import annotations

import os
import tempfile

#: Every personal store this project honours as an environment override, short
#: name -> (env var, default filename inside the scratch dir). Mirrors
#: tests/conftest.py (CLAUDE.md "Personal data lives outside the repo").
#: `MODEL_LOCK` and `CHECKPOINTS` are deliberately NOT here — see `scratch_env`.
STORES: "dict[str, tuple[str, str]]" = {
    "DB": ("MACALENDAR_DB", "calendar.db"),
    "MEMORY_DB": ("MACALENDAR_MEMORY_DB", "nlu_memory.db"),
    "VOCAB": ("MACALENDAR_VOCAB", "vocab.json"),
    "CATEGORIES": ("MACALENDAR_CATEGORIES", "categories.json"),
    "TRACE_BUS": ("MACALENDAR_TRACE_BUS", "trace_bus.jsonl"),
    "LOCATION": ("MACALENDAR_LOCATION", "location.json"),
    "MODELS": ("MACALENDAR_MODELS", "models"),
    "LABEL_FEEDBACK": ("MACALENDAR_LABEL_FEEDBACK", "label_feedback.jsonl"),
    "HEARTBEATS": ("MACALENDAR_HEARTBEATS", "heartbeats"),
    "HUD_STATE": ("MACALENDAR_HUD_STATE", "hud_state.json"),
    "DEVICE_SECRET": ("MACALENDAR_DEVICE_SECRET", "device_secret"),
    "DEVICES": ("MACALENDAR_DEVICES", "devices.json"),
}

#: setdefault, not set — a board pins threads without stomping a caller's own
#: choice, the same as tests/conftest.py's list.
BLAS_THREAD_VARS = (
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
)


def scratch_env(prefix: str, *, seed: "int | None" = None,
                observance: "bool | None" = None,
                keep: "tuple[str, ...]" = (),
                extra: "dict[str, str] | None" = None,
                dir: "str | None" = None) -> str:
    """Point every personal store at a fresh scratch dir; return its path.

    Call this BEFORE importing anything from `assistant` — every store path is
    read at import time (default arguments, module constants), so setting the
    environment after the fact is too late (tests/conftest.py's rule;
    CLAUDE.md "Personal data lives outside the repo").

    `keep` names short store keys (as spelled in `STORES`, e.g. "MEMORY_DB")
    this call must NOT redirect — the caller points that one somewhere else on
    purpose (a persistent pool db, a fixture file) and sets it itself, before
    or after this call.

    `extra` is applied last, straight into `os.environ`, for a script's own
    oddities: `MACALENDAR_LLM_DISABLED`, a per-script store this function
    doesn't know about (`MACALENDAR_LEXICON`, `MACALENDAR_UI_STATE`,
    `MACALENDAR_LLM_BUS`), or `MACALENDAR_CHECKPOINTS` for the one board that
    wants it scratched too.

    `dir` reuses an existing directory instead of making a new one — for the
    handful of boards that read their scratch root from their own env var
    (`B1_SCRATCH`, `BOARD_D_SCRATCH`, ...) so a resumed run keeps its rows.
    When given, the directory is created if missing; nothing inside it is
    cleared.

    Never touches `MACALENDAR_MODEL_LOCK`: boards must share the real lock
    with the running assistant so live traffic can still make one yield
    (CLAUDE.md "One ollama, many callers"; `tests/unit/test_model_protocol.py
    ::test_no_script_gives_itself_a_private_model_lock`). Never touches
    `MACALENDAR_CHECKPOINTS` either — a board that resumes a real measurement
    run needs that store to survive BETWEEN runs, so scratching it here by
    default would silently break resume for every board built on this helper;
    a board that wants it scratched passes it through `extra`.
    """
    scratch = dir or tempfile.mkdtemp(prefix=prefix)
    if dir is not None:
        os.makedirs(scratch, exist_ok=True)

    for key, (var, filename) in STORES.items():
        if key in keep:
            continue
        os.environ[var] = os.path.join(scratch, filename)

    os.environ["MACALENDAR_NO_WARMUP"] = "1"
    # BACKGROUND traffic: yields the model to the live assistant between calls
    # (assistant/model_protocol.py) — without this a board and a voice command
    # are indistinguishable to ollama, and a trivial live call once measured
    # 2.0s -> 42.5s -> 43.9s behind a running board (2026-09-10).
    os.environ.setdefault("MACALENDAR_LLM_PRIORITY", "background")
    for var in BLAS_THREAD_VARS:
        os.environ.setdefault(var, "1")

    if seed is not None:
        os.environ.setdefault("MACALENDAR_LLM_SEED", str(seed))
    if observance is not None:
        os.environ["MACALENDAR_OBSERVANCE"] = "1" if observance else "0"

    for var, value in (extra or {}).items():
        os.environ[var] = str(value)

    return scratch

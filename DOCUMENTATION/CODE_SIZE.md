# Code size, by category

<!-- code-stats: {"total_files": 367, "total_lines": 99113} -->
**Generated — do not edit by hand.** `python -m scripts.code_stats --write`
(last run 2026-09-11). `tests/unit/test_code_size.py` fails when this drifts more than 2% from the real tree.

**99,113 lines of source across 367 files.** Of that, **60,509 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 110 | 18,144 |
| Mac application (calendar GUI) | 28 | 17,196 |
| iOS application | 43 | 13,500 |
| Engine (the brain, shipped path) | 42 | 11,070 |
| Dataset & measurement tooling | 39 | 9,507 |
| Actions, storage & domain (DB, config, observance, .ics) | 41 | 9,493 |
| Engine experiments & boards (not in the answer path) | 23 | 6,224 |
| Retired (old brain, kept on purpose) | 5 | 4,729 |
| Review panel (Mac card + iOS timeline) | 6 | 3,352 |
| Microphone / speech (record, STT, TTS) | 17 | 2,625 |
| API server (the front door) | 4 | 2,125 |
| Model / Ollama code | 7 | 944 |
| Launch scripts | 2 | 204 |
| **TOTAL** | **367** | **99,113** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 317 | 83,997 |
| Swift | 47 | 14,895 |
| launch script | 1 | 126 |
| shell | 2 | 95 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 163,771 lines across 104 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 27,943 lines across 99 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

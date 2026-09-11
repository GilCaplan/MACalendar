# Code size, by category

<!-- code-stats: {"total_files": 367, "total_lines": 99176} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**99,176 lines of source across 367 files.** Of that, **60,509 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 110 | 18,158 |
| Mac application (calendar GUI) | 28 | 17,196 |
| iOS application | 43 | 13,500 |
| Engine (the brain, shipped path) | 42 | 11,070 |
| Dataset & measurement tooling | 39 | 9,556 |
| Actions, storage & domain (DB, config, observance, .ics) | 41 | 9,493 |
| Engine experiments & boards (not in the answer path) | 23 | 6,224 |
| Retired (old brain, kept on purpose) | 5 | 4,729 |
| Review panel (Mac card + iOS timeline) | 6 | 3,352 |
| Microphone / speech (record, STT, TTS) | 17 | 2,625 |
| API server (the front door) | 4 | 2,125 |
| Model / Ollama code | 7 | 944 |
| Launch scripts | 2 | 204 |
| **TOTAL** | **367** | **99,176** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 317 | 84,060 |
| Swift | 47 | 14,895 |
| launch script | 1 | 126 |
| shell | 2 | 95 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 163,771 lines across 104 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 27,948 lines across 99 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

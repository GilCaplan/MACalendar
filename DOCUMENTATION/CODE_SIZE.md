# Code size, by category

<!-- code-stats: {"total_files": 376, "total_lines": 103127} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**103,127 lines of source across 376 files.** Of that, **61,967 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 113 | 19,485 |
| Mac application (calendar GUI) | 28 | 17,196 |
| iOS application | 43 | 13,533 |
| Engine (the brain, shipped path) | 43 | 11,718 |
| Dataset & measurement tooling | 40 | 10,536 |
| Actions, storage & domain (DB, config, observance, .ics) | 42 | 9,765 |
| Engine experiments & boards (not in the answer path) | 23 | 6,242 |
| Retired (old brain, kept on purpose) | 7 | 4,897 |
| Review panel (Mac card + iOS timeline) | 6 | 3,729 |
| Microphone / speech (record, STT, TTS) | 17 | 2,652 |
| API server (the front door) | 4 | 2,125 |
| Model / Ollama code | 7 | 969 |
| Launch scripts | 3 | 280 |
| **TOTAL** | **376** | **103,127** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 324 | 87,877 |
| Swift | 47 | 14,928 |
| shell | 4 | 196 |
| launch script | 1 | 126 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 163,802 lines across 105 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 29,245 lines across 101 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

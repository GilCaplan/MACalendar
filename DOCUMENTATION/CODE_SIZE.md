# Code size, by category

<!-- code-stats: {"total_files": 371, "total_lines": 102429} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**102,429 lines of source across 371 files.** Of that, **62,258 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 113 | 19,639 |
| Mac application (calendar GUI) | 28 | 17,357 |
| iOS application | 44 | 14,158 |
| Engine (the brain, shipped path) | 42 | 11,380 |
| Actions, storage & domain (DB, config, observance, .ics) | 41 | 9,689 |
| Dataset & measurement tooling | 37 | 9,393 |
| Engine experiments & boards (not in the answer path) | 23 | 6,242 |
| Retired (old brain, kept on purpose) | 7 | 4,897 |
| Review panel (Mac card + iOS timeline) | 6 | 3,398 |
| Microphone / speech (record, STT, TTS) | 17 | 2,712 |
| API server (the front door) | 4 | 2,389 |
| Model / Ollama code | 7 | 944 |
| Launch scripts | 2 | 231 |
| **TOTAL** | **371** | **102,429** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 320 | 86,568 |
| Swift | 48 | 15,613 |
| launch script | 1 | 153 |
| shell | 2 | 95 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 163,771 lines across 104 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 28,312 lines across 100 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

# Code size, by category

<!-- code-stats: {"total_files": 504, "total_lines": 132585} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**132,585 lines of source across 504 files.** Of that, **77,268 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 137 | 26,478 |
| Mac application (calendar GUI) | 30 | 17,719 |
| iOS application | 54 | 17,208 |
| Actions, storage & domain (DB, config, observance, .ics) | 94 | 16,626 |
| Engine (the brain, shipped path) | 48 | 14,482 |
| Engine experiments & boards (not in the answer path) | 47 | 12,437 |
| Dataset & measurement tooling | 40 | 10,063 |
| Retired (old brain, kept on purpose) | 12 | 6,339 |
| Review panel (Mac card + iOS timeline) | 6 | 4,078 |
| Microphone / speech (record, STT, TTS) | 17 | 2,716 |
| Model / Ollama code | 12 | 2,563 |
| API server (the front door) | 4 | 1,569 |
| Launch scripts | 3 | 307 |
| **TOTAL** | **504** | **132,585** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 438 | 113,024 |
| Swift | 59 | 19,028 |
| shell | 6 | 380 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 184,941 lines across 115 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 36,815 lines across 109 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

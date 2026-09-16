# Code size, by category

<!-- code-stats: {"total_files": 427, "total_lines": 119617} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**119,617 lines of source across 427 files.** Of that, **68,235 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 129 | 24,370 |
| Mac application (calendar GUI) | 28 | 17,349 |
| iOS application | 44 | 14,244 |
| Engine (the brain, shipped path) | 48 | 13,939 |
| Engine experiments & boards (not in the answer path) | 43 | 11,516 |
| Actions, storage & domain (DB, config, observance, .ics) | 44 | 10,759 |
| Dataset & measurement tooling | 40 | 10,014 |
| Retired (old brain, kept on purpose) | 9 | 5,482 |
| Review panel (Mac card + iOS timeline) | 6 | 4,032 |
| Microphone / speech (record, STT, TTS) | 17 | 2,656 |
| Model / Ollama code | 12 | 2,563 |
| API server (the front door) | 4 | 2,413 |
| Launch scripts | 3 | 280 |
| **TOTAL** | **427** | **119,617** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 374 | 103,511 |
| Swift | 48 | 15,738 |
| shell | 4 | 242 |
| launch script | 1 | 126 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 184,941 lines across 115 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 35,582 lines across 104 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

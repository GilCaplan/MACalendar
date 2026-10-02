# Code size, by category

<!-- code-stats: {"total_files": 839, "total_lines": 219015} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**219,015 lines of source across 839 files.** Of that, **127,517 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 245 | 47,677 |
| iOS application | 130 | 37,423 |
| Actions, storage & domain (DB, config, observance, .ics) | 165 | 28,413 |
| Mac application (calendar GUI) | 44 | 24,496 |
| Engine experiments & boards (not in the answer path) | 70 | 22,234 |
| Engine (the brain, shipped path) | 62 | 21,933 |
| Dataset & measurement tooling | 55 | 13,969 |
| Retired (old brain, kept on purpose) | 17 | 7,618 |
| Review panel (Mac card + iOS timeline) | 6 | 4,288 |
| Microphone / speech (record, STT, TTS) | 20 | 4,193 |
| Model / Ollama code | 12 | 3,281 |
| API server (the front door) | 6 | 2,201 |
| Launch scripts | 7 | 1,289 |
| **TOTAL** | **839** | **219,015** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 689 | 177,579 |
| Swift | 138 | 40,307 |
| shell | 10 | 930 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 342,116 lines across 381 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 52,676 lines across 125 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

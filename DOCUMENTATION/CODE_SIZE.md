# Code size, by category

<!-- code-stats: {"total_files": 870, "total_lines": 229214} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**229,214 lines of source across 870 files.** Of that, **132,427 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 255 | 49,422 |
| iOS application | 142 | 41,216 |
| Actions, storage & domain (DB, config, observance, .ics) | 165 | 28,461 |
| Mac application (calendar GUI) | 45 | 24,923 |
| Engine experiments & boards (not in the answer path) | 73 | 24,614 |
| Engine (the brain, shipped path) | 62 | 21,956 |
| Dataset & measurement tooling | 60 | 15,133 |
| Retired (old brain, kept on purpose) | 17 | 7,618 |
| Microphone / speech (record, STT, TTS) | 20 | 4,790 |
| Review panel (Mac card + iOS timeline) | 6 | 4,298 |
| Model / Ollama code | 12 | 3,281 |
| API server (the front door) | 6 | 2,213 |
| Launch scripts | 7 | 1,289 |
| **TOTAL** | **870** | **229,214** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 707 | 183,342 |
| Swift | 150 | 44,697 |
| shell | 11 | 976 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 344,414 lines across 399 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 53,420 lines across 126 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

# Code size, by category

<!-- code-stats: {"total_files": 741, "total_lines": 199100} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**199,100 lines of source across 741 files.** Of that, **113,580 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 225 | 44,016 |
| Actions, storage & domain (DB, config, observance, .ics) | 161 | 27,331 |
| iOS application | 70 | 26,944 |
| Mac application (calendar GUI) | 45 | 23,681 |
| Engine (the brain, shipped path) | 57 | 20,774 |
| Engine experiments & boards (not in the answer path) | 65 | 20,386 |
| Dataset & measurement tooling | 52 | 13,585 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,288 |
| Microphone / speech (record, STT, TTS) | 20 | 3,863 |
| Model / Ollama code | 12 | 3,252 |
| API server (the front door) | 6 | 2,174 |
| Launch scripts | 6 | 1,273 |
| **TOTAL** | **741** | **199,100** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 652 | 168,481 |
| Swift | 78 | 29,506 |
| shell | 9 | 914 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 327,277 lines across 207 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 51,313 lines across 124 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

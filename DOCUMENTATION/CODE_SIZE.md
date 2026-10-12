# Code size, by category

<!-- code-stats: {"total_files": 914, "total_lines": 244611} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**244,611 lines of source across 914 files.** Of that, **144,669 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 264 | 51,966 |
| iOS application | 159 | 46,808 |
| Actions, storage & domain (DB, config, observance, .ics) | 179 | 30,840 |
| Mac application (calendar GUI) | 47 | 29,017 |
| Engine experiments & boards (not in the answer path) | 73 | 24,614 |
| Engine (the brain, shipped path) | 62 | 21,971 |
| Dataset & measurement tooling | 62 | 15,744 |
| Retired (old brain, kept on purpose) | 17 | 7,618 |
| Microphone / speech (record, STT, TTS) | 20 | 4,923 |
| Review panel (Mac card + iOS timeline) | 6 | 4,298 |
| Model / Ollama code | 12 | 3,282 |
| API server (the front door) | 6 | 2,241 |
| Launch scripts | 7 | 1,289 |
| **TOTAL** | **914** | **244,611** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 734 | 193,014 |
| Swift | 167 | 50,422 |
| shell | 11 | 976 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 344,446 lines across 401 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 54,494 lines across 128 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

# Code size, by category

<!-- code-stats: {"total_files": 937, "total_lines": 251059} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**251,059 lines of source across 937 files.** Of that, **149,493 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 276 | 53,442 |
| iOS application | 161 | 49,363 |
| Actions, storage & domain (DB, config, observance, .ics) | 187 | 32,647 |
| Mac application (calendar GUI) | 47 | 29,459 |
| Engine experiments & boards (not in the answer path) | 73 | 24,614 |
| Engine (the brain, shipped path) | 62 | 21,971 |
| Dataset & measurement tooling | 63 | 15,892 |
| Retired (old brain, kept on purpose) | 17 | 7,618 |
| Microphone / speech (record, STT, TTS) | 20 | 4,928 |
| Review panel (Mac card + iOS timeline) | 6 | 4,298 |
| Model / Ollama code | 12 | 3,282 |
| API server (the front door) | 6 | 2,256 |
| Launch scripts | 7 | 1,289 |
| **TOTAL** | **937** | **251,059** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 755 | 196,902 |
| Swift | 169 | 52,982 |
| shell | 11 | 976 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 344,446 lines across 401 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 54,147 lines across 129 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

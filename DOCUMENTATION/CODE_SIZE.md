# Code size, by category

<!-- code-stats: {"total_files": 969, "total_lines": 254554} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**254,554 lines of source across 969 files.** Of that, **151,469 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 292 | 54,917 |
| iOS application | 162 | 50,041 |
| Actions, storage & domain (DB, config, observance, .ics) | 202 | 33,422 |
| Mac application (calendar GUI) | 47 | 29,609 |
| Engine experiments & boards (not in the answer path) | 73 | 24,648 |
| Engine (the brain, shipped path) | 62 | 22,068 |
| Dataset & measurement tooling | 63 | 15,902 |
| Retired (old brain, kept on purpose) | 17 | 7,618 |
| Microphone / speech (record, STT, TTS) | 20 | 5,019 |
| Review panel (Mac card + iOS timeline) | 6 | 4,468 |
| Model / Ollama code | 12 | 3,265 |
| API server (the front door) | 6 | 2,272 |
| Launch scripts | 7 | 1,305 |
| **TOTAL** | **969** | **254,554** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 786 | 199,675 |
| Swift | 170 | 53,704 |
| shell | 11 | 976 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 346,072 lines across 402 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 54,314 lines across 129 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

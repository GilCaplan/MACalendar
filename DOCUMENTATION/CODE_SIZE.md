# Code size, by category

<!-- code-stats: {"total_files": 973, "total_lines": 255333} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**255,333 lines of source across 973 files.** Of that, **151,785 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 295 | 55,380 |
| iOS application | 162 | 50,101 |
| Actions, storage & domain (DB, config, observance, .ics) | 202 | 33,622 |
| Mac application (calendar GUI) | 48 | 29,659 |
| Engine experiments & boards (not in the answer path) | 73 | 24,648 |
| Engine (the brain, shipped path) | 62 | 22,068 |
| Dataset & measurement tooling | 63 | 15,902 |
| Retired (old brain, kept on purpose) | 17 | 7,618 |
| Microphone / speech (record, STT, TTS) | 20 | 5,019 |
| Review panel (Mac card + iOS timeline) | 6 | 4,474 |
| Model / Ollama code | 12 | 3,265 |
| API server (the front door) | 6 | 2,272 |
| Launch scripts | 7 | 1,305 |
| **TOTAL** | **973** | **255,333** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 790 | 200,394 |
| Swift | 170 | 53,764 |
| shell | 11 | 976 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 346,072 lines across 402 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 54,337 lines across 129 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

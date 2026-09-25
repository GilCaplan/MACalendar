# Code size, by category

<!-- code-stats: {"total_files": 591, "total_lines": 164487} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**164,487 lines of source across 591 files.** Of that, **91,402 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 173 | 34,454 |
| iOS application | 61 | 22,083 |
| Actions, storage & domain (DB, config, observance, .ics) | 103 | 19,230 |
| Engine (the brain, shipped path) | 53 | 18,841 |
| Mac application (calendar GUI) | 34 | 18,770 |
| Engine experiments & boards (not in the answer path) | 59 | 17,862 |
| Dataset & measurement tooling | 50 | 13,236 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,128 |
| Model / Ollama code | 12 | 3,168 |
| Microphone / speech (record, STT, TTS) | 17 | 3,151 |
| API server (the front door) | 4 | 1,715 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **591** | **164,487** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 516 | 139,661 |
| Swift | 66 | 23,977 |
| shell | 8 | 696 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 230,491 lines across 170 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 47,260 lines across 117 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

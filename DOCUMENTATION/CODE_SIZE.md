# Code size, by category

<!-- code-stats: {"total_files": 750, "total_lines": 201623} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**201,623 lines of source across 750 files.** Of that, **114,708 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 230 | 45,209 |
| Actions, storage & domain (DB, config, observance, .ics) | 162 | 27,929 |
| iOS application | 71 | 27,081 |
| Mac application (calendar GUI) | 45 | 23,875 |
| Engine (the brain, shipped path) | 58 | 20,936 |
| Engine experiments & boards (not in the answer path) | 65 | 20,386 |
| Dataset & measurement tooling | 53 | 13,787 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,288 |
| Microphone / speech (record, STT, TTS) | 20 | 3,871 |
| Model / Ollama code | 12 | 3,281 |
| API server (the front door) | 6 | 2,174 |
| Launch scripts | 6 | 1,273 |
| **TOTAL** | **750** | **201,623** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 660 | 170,867 |
| Swift | 79 | 29,643 |
| shell | 9 | 914 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 327,277 lines across 207 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 51,482 lines across 124 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

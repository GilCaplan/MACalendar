# Code size, by category

<!-- code-stats: {"total_files": 570, "total_lines": 158245} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**158,245 lines of source across 570 files.** Of that, **87,024 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 165 | 33,168 |
| iOS application | 60 | 20,777 |
| Mac application (calendar GUI) | 33 | 18,306 |
| Engine (the brain, shipped path) | 51 | 17,886 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,554 |
| Engine experiments & boards (not in the answer path) | 58 | 17,432 |
| Dataset & measurement tooling | 49 | 13,088 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,128 |
| Model / Ollama code | 12 | 3,168 |
| Microphone / speech (record, STT, TTS) | 17 | 3,151 |
| API server (the front door) | 4 | 1,738 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **570** | **158,245** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 496 | 134,725 |
| Swift | 65 | 22,671 |
| shell | 8 | 696 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 225,701 lines across 166 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 46,580 lines across 115 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

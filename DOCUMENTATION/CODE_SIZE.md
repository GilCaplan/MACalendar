# Code size, by category

<!-- code-stats: {"total_files": 558, "total_lines": 154020} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**154,020 lines of source across 558 files.** Of that, **85,809 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 159 | 32,389 |
| iOS application | 60 | 20,562 |
| Mac application (calendar GUI) | 33 | 18,245 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,436 |
| Engine (the brain, shipped path) | 49 | 17,065 |
| Engine experiments & boards (not in the answer path) | 54 | 15,203 |
| Dataset & measurement tooling | 49 | 13,086 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,128 |
| Model / Ollama code | 12 | 3,168 |
| Microphone / speech (record, STT, TTS) | 17 | 3,151 |
| API server (the front door) | 4 | 1,738 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **558** | **154,020** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 484 | 130,715 |
| Swift | 65 | 22,456 |
| shell | 8 | 696 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 215,769 lines across 161 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 45,536 lines across 114 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

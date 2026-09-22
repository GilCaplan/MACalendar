# Code size, by category

<!-- code-stats: {"total_files": 545, "total_lines": 150123} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**150,123 lines of source across 545 files.** Of that, **85,629 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 155 | 31,611 |
| iOS application | 60 | 20,562 |
| Mac application (calendar GUI) | 33 | 18,245 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,385 |
| Engine (the brain, shipped path) | 49 | 16,998 |
| Dataset & measurement tooling | 48 | 12,847 |
| Engine experiments & boards (not in the answer path) | 46 | 12,503 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,116 |
| Microphone / speech (record, STT, TTS) | 17 | 3,151 |
| Model / Ollama code | 12 | 3,118 |
| API server (the front door) | 4 | 1,738 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **545** | **150,123** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 471 | 126,818 |
| Swift | 65 | 22,456 |
| shell | 8 | 696 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 188,508 lines across 143 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 43,165 lines across 113 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

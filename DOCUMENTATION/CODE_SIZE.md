# Code size, by category

<!-- code-stats: {"total_files": 494, "total_lines": 131442} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**131,442 lines of source across 494 files.** Of that, **76,278 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 136 | 26,333 |
| Mac application (calendar GUI) | 29 | 17,568 |
| iOS application | 52 | 16,819 |
| Actions, storage & domain (DB, config, observance, .ics) | 88 | 15,145 |
| Engine (the brain, shipped path) | 48 | 14,482 |
| Engine experiments & boards (not in the answer path) | 47 | 12,437 |
| Dataset & measurement tooling | 40 | 10,055 |
| Retired (old brain, kept on purpose) | 12 | 6,339 |
| Review panel (Mac card + iOS timeline) | 6 | 4,078 |
| Microphone / speech (record, STT, TTS) | 17 | 2,716 |
| API server (the front door) | 4 | 2,600 |
| Model / Ollama code | 12 | 2,563 |
| Launch scripts | 3 | 307 |
| **TOTAL** | **494** | **131,442** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 430 | 112,270 |
| Swift | 57 | 18,639 |
| shell | 6 | 380 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 184,941 lines across 115 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 36,770 lines across 109 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

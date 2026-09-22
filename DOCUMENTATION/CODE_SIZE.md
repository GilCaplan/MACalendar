# Code size, by category

<!-- code-stats: {"total_files": 554, "total_lines": 153045} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**153,045 lines of source across 554 files.** Of that, **85,686 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 157 | 32,029 |
| iOS application | 60 | 20,562 |
| Mac application (calendar GUI) | 33 | 18,245 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,394 |
| Engine (the brain, shipped path) | 49 | 17,034 |
| Engine experiments & boards (not in the answer path) | 53 | 14,950 |
| Dataset & measurement tooling | 48 | 12,847 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,128 |
| Microphone / speech (record, STT, TTS) | 17 | 3,151 |
| Model / Ollama code | 12 | 3,118 |
| API server (the front door) | 4 | 1,738 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **554** | **153,045** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 480 | 129,740 |
| Swift | 65 | 22,456 |
| shell | 8 | 696 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 206,890 lines across 148 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 43,577 lines across 114 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

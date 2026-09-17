# Code size, by category

<!-- code-stats: {"total_files": 513, "total_lines": 135151} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**135,151 lines of source across 513 files.** Of that, **78,838 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 141 | 27,291 |
| iOS application | 55 | 18,128 |
| Mac application (calendar GUI) | 31 | 17,872 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,088 |
| Engine (the brain, shipped path) | 48 | 14,482 |
| Engine experiments & boards (not in the answer path) | 47 | 12,437 |
| Dataset & measurement tooling | 41 | 10,246 |
| Retired (old brain, kept on purpose) | 12 | 6,339 |
| Review panel (Mac card + iOS timeline) | 6 | 4,078 |
| Microphone / speech (record, STT, TTS) | 17 | 2,716 |
| Model / Ollama code | 12 | 2,563 |
| API server (the front door) | 4 | 1,595 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **513** | **135,151** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 445 | 114,467 |
| Swift | 60 | 19,948 |
| shell | 7 | 583 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 184,941 lines across 115 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 36,912 lines across 109 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

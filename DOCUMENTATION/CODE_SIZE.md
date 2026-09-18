# Code size, by category

<!-- code-stats: {"total_files": 518, "total_lines": 139488} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**139,488 lines of source across 518 files.** Of that, **81,271 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 142 | 28,338 |
| iOS application | 58 | 19,707 |
| Mac application (calendar GUI) | 31 | 17,967 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,099 |
| Engine (the brain, shipped path) | 48 | 15,120 |
| Engine experiments & boards (not in the answer path) | 47 | 12,515 |
| Dataset & measurement tooling | 42 | 11,025 |
| Retired (old brain, kept on purpose) | 12 | 6,339 |
| Review panel (Mac card + iOS timeline) | 6 | 4,078 |
| Microphone / speech (record, STT, TTS) | 17 | 2,716 |
| Model / Ollama code | 12 | 2,563 |
| API server (the front door) | 4 | 1,705 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **518** | **139,488** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 447 | 117,225 |
| Swift | 63 | 21,527 |
| shell | 7 | 583 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 187,354 lines across 117 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 38,273 lines across 111 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

# Code size, by category

<!-- code-stats: {"total_files": 672, "total_lines": 185651} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**185,651 lines of source across 672 files.** Of that, **103,211 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 212 | 40,973 |
| iOS application | 64 | 25,071 |
| Actions, storage & domain (DB, config, observance, .ics) | 123 | 22,798 |
| Mac application (calendar GUI) | 40 | 21,491 |
| Engine (the brain, shipped path) | 57 | 20,735 |
| Engine experiments & boards (not in the answer path) | 65 | 20,376 |
| Dataset & measurement tooling | 52 | 13,558 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,245 |
| Model / Ollama code | 12 | 3,251 |
| Microphone / speech (record, STT, TTS) | 17 | 3,195 |
| API server (the front door) | 5 | 2,073 |
| Launch scripts | 3 | 352 |
| **TOTAL** | **672** | **185,651** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 594 | 157,756 |
| Swift | 69 | 26,965 |
| shell | 8 | 741 |
| launch script | 1 | 189 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 327,277 lines across 207 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 49,989 lines across 120 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

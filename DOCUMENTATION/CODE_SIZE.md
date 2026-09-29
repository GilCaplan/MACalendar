# Code size, by category

<!-- code-stats: {"total_files": 707, "total_lines": 191497} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**191,497 lines of source across 707 files.** Of that, **107,616 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 219 | 42,393 |
| iOS application | 68 | 25,911 |
| Actions, storage & domain (DB, config, observance, .ics) | 143 | 24,781 |
| Mac application (calendar GUI) | 41 | 22,441 |
| Engine (the brain, shipped path) | 57 | 20,740 |
| Engine experiments & boards (not in the answer path) | 65 | 20,386 |
| Dataset & measurement tooling | 52 | 13,569 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,245 |
| Microphone / speech (record, STT, TTS) | 20 | 3,824 |
| Model / Ollama code | 12 | 3,251 |
| API server (the front door) | 5 | 2,091 |
| Launch scripts | 3 | 332 |
| **TOTAL** | **707** | **191,497** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 622 | 162,142 |
| Swift | 76 | 28,434 |
| shell | 8 | 752 |
| launch script | 1 | 169 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 327,277 lines across 207 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 50,722 lines across 122 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

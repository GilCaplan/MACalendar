# Code size, by category

<!-- code-stats: {"total_files": 654, "total_lines": 181563} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**181,563 lines of source across 654 files.** Of that, **100,085 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 207 | 40,063 |
| iOS application | 62 | 24,079 |
| Actions, storage & domain (DB, config, observance, .ics) | 116 | 21,685 |
| Engine (the brain, shipped path) | 57 | 20,735 |
| Mac application (calendar GUI) | 37 | 20,585 |
| Engine experiments & boards (not in the answer path) | 65 | 20,373 |
| Dataset & measurement tooling | 51 | 13,509 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,217 |
| Model / Ollama code | 12 | 3,251 |
| Microphone / speech (record, STT, TTS) | 17 | 3,169 |
| API server (the front door) | 5 | 2,012 |
| Launch scripts | 3 | 352 |
| **TOTAL** | **654** | **181,563** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 578 | 154,660 |
| Swift | 67 | 25,973 |
| shell | 8 | 741 |
| launch script | 1 | 189 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 327,185 lines across 206 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 49,902 lines across 120 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

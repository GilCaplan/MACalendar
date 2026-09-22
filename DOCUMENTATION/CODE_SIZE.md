# Code size, by category

<!-- code-stats: {"total_files": 540, "total_lines": 149384} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**149,384 lines of source across 540 files.** Of that, **85,397 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 150 | 31,210 |
| iOS application | 60 | 20,545 |
| Mac application (calendar GUI) | 33 | 18,297 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,323 |
| Engine (the brain, shipped path) | 49 | 16,837 |
| Dataset & measurement tooling | 48 | 12,832 |
| Engine experiments & boards (not in the answer path) | 46 | 12,412 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,110 |
| Microphone / speech (record, STT, TTS) | 17 | 3,151 |
| Model / Ollama code | 12 | 3,080 |
| API server (the front door) | 4 | 1,738 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **540** | **149,384** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 466 | 126,097 |
| Swift | 65 | 22,438 |
| shell | 8 | 696 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 188,275 lines across 137 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 42,289 lines across 113 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

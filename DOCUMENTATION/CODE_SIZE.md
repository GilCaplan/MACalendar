# Code size, by category

<!-- code-stats: {"total_files": 836, "total_lines": 218188} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**218,188 lines of source across 836 files.** Of that, **127,512 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 244 | 47,495 |
| iOS application | 130 | 37,418 |
| Actions, storage & domain (DB, config, observance, .ics) | 165 | 28,413 |
| Mac application (calendar GUI) | 44 | 24,496 |
| Engine (the brain, shipped path) | 62 | 21,933 |
| Engine experiments & boards (not in the answer path) | 68 | 21,609 |
| Dataset & measurement tooling | 55 | 13,954 |
| Retired (old brain, kept on purpose) | 17 | 7,618 |
| Review panel (Mac card + iOS timeline) | 6 | 4,288 |
| Microphone / speech (record, STT, TTS) | 20 | 4,193 |
| Model / Ollama code | 12 | 3,281 |
| API server (the front door) | 6 | 2,201 |
| Launch scripts | 7 | 1,289 |
| **TOTAL** | **836** | **218,188** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 686 | 176,757 |
| Swift | 138 | 40,302 |
| shell | 10 | 930 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 341,693 lines across 380 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 52,503 lines across 125 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

# Code size, by category

<!-- code-stats: {"total_files": 812, "total_lines": 211608} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**211,608 lines of source across 812 files.** Of that, **123,695 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 236 | 46,160 |
| iOS application | 120 | 35,250 |
| Actions, storage & domain (DB, config, observance, .ics) | 165 | 28,255 |
| Mac application (calendar GUI) | 45 | 23,980 |
| Engine (the brain, shipped path) | 60 | 21,265 |
| Engine experiments & boards (not in the answer path) | 65 | 20,386 |
| Dataset & measurement tooling | 54 | 13,834 |
| Retired (old brain, kept on purpose) | 16 | 7,533 |
| Review panel (Mac card + iOS timeline) | 6 | 4,288 |
| Microphone / speech (record, STT, TTS) | 20 | 3,909 |
| Model / Ollama code | 12 | 3,281 |
| API server (the front door) | 6 | 2,178 |
| Launch scripts | 7 | 1,289 |
| **TOTAL** | **812** | **211,608** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 672 | 172,629 |
| Swift | 128 | 37,850 |
| shell | 10 | 930 |
| launch script | 2 | 199 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 327,347 lines across 212 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 51,929 lines across 124 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

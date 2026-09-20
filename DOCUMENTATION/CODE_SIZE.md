# Code size, by category

<!-- code-stats: {"total_files": 530, "total_lines": 144829} -->
**Generated — do not edit by hand.** The pre-commit hook (`python -m scripts.code_stats --install-hook`) rewrites this whenever the numbers move, so it describes the commit it ships in. By hand: `python -m scripts.code_stats --write`; `--check` says whether it is current, and `tests/unit/test_code_size.py` fails once it is more than 2% out.

**144,829 lines of source across 530 files.** Of that, **83,782 lines are the live product** — the rest is tests, the retired brain, the measurement boards and the dataset tooling.

| category | files | lines |
|---|---:|---:|
| Test code | 144 | 29,658 |
| iOS application | 59 | 20,445 |
| Mac application (calendar GUI) | 33 | 18,297 |
| Actions, storage & domain (DB, config, observance, .ics) | 96 | 17,222 |
| Engine (the brain, shipped path) | 49 | 16,003 |
| Dataset & measurement tooling | 48 | 12,535 |
| Engine experiments & boards (not in the answer path) | 47 | 12,515 |
| Retired (old brain, kept on purpose) | 12 | 6,339 |
| Review panel (Mac card + iOS timeline) | 6 | 4,110 |
| Microphone / speech (record, STT, TTS) | 17 | 3,094 |
| Model / Ollama code | 12 | 2,563 |
| API server (the front door) | 4 | 1,732 |
| Launch scripts | 3 | 316 |
| **TOTAL** | **530** | **144,829** |

### By language

| | files | lines |
|---|---:|---:|
| Python | 457 | 121,699 |
| Swift | 64 | 22,281 |
| shell | 8 | 696 |
| launch script | 1 | 153 |

Not counted above, and deliberately so:

- **Data** — the utterance corpus, fitted weights and fixtures: 187,371 lines across 117 files. Bigger than the code, and not written by hand.
- **Prose** — markdown and the published HTML explainers: 39,763 lines across 112 files.

### How the categories are drawn

Every tracked source file lands in exactly one category, so the rows sum to the total and nothing is double counted. The rules live in `scripts/code_stats.py`'s `category()`; the arguable ones:

- `llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages that exist to call the model.
- `intent/` (rule parser, classifiers, command memory) counts as **Engine**.
- iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.
- `trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.
- A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are **boards**, not the shipped engine.

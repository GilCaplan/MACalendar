# MACalendar — Mac App

A **voice-controlled, privacy-first calendar and task assistant** for macOS built with PyQt6.

> **Read this first: the Mac app no longer parses anything.** Since the engine
> rewire, `assistant/pipeline.py` records audio, transcribes it and POSTs the
> transcript to the API (`pipeline.py:469`, `POST 127.0.0.1:<port>/voice/text`);
> parsing and execution happen in `assistant.api` → `assistant.engine`. The
> file says so itself at `pipeline.py:74` — *"Kept only for health_check(); this
> process does not parse any more."* Anything below that describes a decision
> being made **is describing the engine**, reached over HTTP. What stays here is
> real and this app's own: audio, STT, the two dialogs, the views, the DB.

---

## Log Prefix
All Mac app log lines are prefixed with `🖥️` to distinguish from iPhone API logs (`📱`).

---

## Recent Core Features

- **Hybrid NLU Fast-Path**: `RuleBasedParser` (spaCy + Microsoft Recognizers-Text) answers common commands in <10 ms without any LLM call. 7-phase algorithm: preprocess → multi-intent split → temporal extraction → intent routing → slot filling → anaphora → confidence scoring. It is no longer called from this process: it is the parsing half of the engine's **FastRule** stage (`assistant/engine/fastrule/`), which imports it at `fastrule/objects.py:106`. The bar is `RULE_THRESHOLD = 0.80` (`assistant/intent/rule_parser.py:102`, tuned 2026-09-07 — a whole-command sweep bought +2 pp coverage at flat 87% precision); sub-items inside a split command use `SUBITEM_RULE_THRESHOLD = 0.60` (`fastrule/objects.py:46`).
- **Recurrence Logic**: Support for series-wide updates and intelligent rescheduling.
- **Theme Support**: Persistent dark/light toggle in the Gear settings menu.
- **Dynamic Settings UI**: Resizable settings window with vertical "stretching" spacers and a dedicated **Compact Layout** toggle for high-density setups.
- **Font Controls**: Separate font size adjustments for Month, Week, Day, and Tasks in the Gear settings menu.
- **Background review behind a fast commit**: after the fast track answers, the engine runs the cross-check on a daemon thread (`assistant/engine/__init__.py:565 _start_background_verify`). A placeholder title is renamed in place; a missing ask or an extra row is **advisory only** ("Worth a look: …") unless `self_check_apply` is on, and it is `false` by default (`assistant/config.py:286`, `config.example.yaml:95`). The old always-on verifier is what that default is guarding against — it proposed far more than it fixed. The result reaches this app as a late trace step and the phone as a `verify_token` poll.
- **Structured Partial Handoff**: when rule confidence is below the bar or slots are missing, pre-analysis context (filled/empty slots, transcript, confidence) is prepended to the LLM prompt so the LLM only fills gaps. Still live, now inside the engine: `parse_with_context` is called at `assistant/engine/fastrule/objects.py:321`. The deferral never wastes the work — `state.fastrule_verdict` carries the reason, its class and the confidence forward.
- **iPhone Companion App**: SwiftUI app with full offline support — local JSON cache + pending write queue that auto-syncs when Mac is reachable. See [SYSTEM_IPHONE.md](SYSTEM_IPHONE.md).
- **iPhone API auto-start**: `Launch Calendar.command` starts the Flask API (`--tailscale --port 8080`) in the background alongside the Mac app. Tailscale IP is printed to terminal.
- **Todo Integration (Tasks View)**: Apple Reminders-style Tasks panel (Today + General). Voice CRUD, inline editing, calendar sync, anaphoric memory ("delete it").
- **Day View & Morning Briefing**: Hourly timeline with live current-time indicator and 🌅 Brief Me button.
- **Real-Time Streaming STT**: Incremental transcription every 2.5s with stop-keyword early termination ("done", "execute", "go").
- **Voice Session Queuing**: Press mic while busy → queues a new session or combine mode (appends to previous transcript). Cycles: queue → combine → cancel.
- **Event Resize by Drag**: Top/bottom 8px handles on event blocks change start/end time live, snapping to 15-min grid.
- **Universal LLM Intent Parser**: Ollama (local), OpenAI, Gemini, Anthropic Claude — routed via `config.llm_engine`.
- **Audio Device Probe**: `assistant/audio/probe.py` runs once at startup, detects native sample rate, permissions, dtype. Resamples to 16 kHz for Whisper if needed.
- **Integrated Settings UI**: ⚙️ gear popup for Auto-Approve, voice selection, talking speed, mute, startup theme choice, live audio test.
- **Series-Wide Editing**: When editing recurring events, chooses between "This instance" or "Entire series" with automatic recurrence-end re-generation.
- **Context Memory (Anaphora)**: `ContextMemory` Borg singleton (`assistant/intent/context.py`) retains last event/todo ID/title for pronoun resolution ("move it", "delete that").
- **Prompt Injection Defense**: Sanitizes transcripts before LLM submission.

---

## Data Flow

Everything above the dashed line runs in this process; everything below it runs
in `assistant.api`. The boundary is one HTTP POST.

```
Hotkey (Ctrl+J) or Mic Button
  → AudioCapture (records at native rate, resamples to 16kHz)
  → stream_checker() (detects stop keywords → stop_recording())
  → Redo / Add more / Send bar   (audio.review_before_send; a stop word skips it)
  → WhisperSTT / MlxWhisperSTT.transcribe()  [reuses stream-checker result if fresh]
- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
  → POST 127.0.0.1:<port>/voice/text     pipeline.py:469
        {transcript, source:"mac", current_view, supports_edit, supports_confirm}
  →   THE ENGINE  (see SYSTEM.md "NLU Parse Path")
        ingest·transcript → fast track? → segment → decompose_validate
                                        → fastrule → llmjudge → commit(+label)
- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
  ← {message, actions, refresh, parse, trace, corrections, verify_token?}
  → two gates this client opts into, both answered by a dialog on this thread:
        parse="needs_edit"      → "check the transcription" box, resubmit
        parse="confirm_create"  → Add / No box → POST /voice/confirm  (:728)
  → TTS Speaker (macOS 'say')
  → UI refresh from `refresh`   (the DB was written by the API process)
  → the trace goes to the HUD over assistant/trace_bus.py, not to this window
```

`supports_edit` / `supports_confirm` are how the engine knows it may stop and
ask: a client that cannot show a dialog never gets the gate.

---

## Key Components

| File | Role |
|------|------|
| `assistant/pipeline.py` | Orchestrates full voice flow. Session queuing (`_queued`: None/new/combine), per-phase timing logs. |
| `assistant/audio/capture.py` | Records at device-native rate, resamples to 16kHz. Reuses stream-checker transcript when fresh (<3s). |
| `assistant/audio/probe.py` | One-time startup probe: finds working sample rate, checks mic permissions, caches as `AudioDeviceProfile`. |
| `assistant/stt/whisper_stt.py` | `faster-whisper` base model, int8, beam_size=1 (greedy). Selected by `stt_engine: "whisper"`. |
| `assistant/stt/mlx_whisper_stt.py` | Whisper `base` on the Apple GPU via `mlx-whisper` — `stt_engine: "mlx"`, which is what this machine's `config.yaml` uses. Both are built by `pipeline._build_stt` (`pipeline.py:47-57`). |
| `assistant/intent/rule_parser.py` | `RuleBasedParser` — 7-phase hybrid NLU. spaCy + Microsoft Recognizers-Text. `RULE_THRESHOLD = 0.80` (`:102`). Raises `RuleParserSkip` for complex commands. **Called by the engine, not by this app** — `assistant/engine/fastrule/`. |
| `assistant/intent/context.py` | `ContextMemory` Borg singleton — thread-safe last event/todo ID+title for anaphora resolution across actions and rule parser. |
| `assistant/intent/parser.py` | Multi-backend LLM transport (Ollama / OpenAI / Gemini / Claude) plus the old brain's parser. System prompt cached daily. `parse_with_context()` (partial handoff) and `call_llm_json` are live, called from the engine. `verify_fast_path_async()` and `verify_actions_async()` are **not** — grep finds no caller outside this file; the engine's judge (`llmjudge/`) replaced them. Worth knowing before tuning "the verifier" and tuning the wrong one. Every call is logged to the LLM console (`:519-595`). |
| `assistant/actions/calendar/action.py` | Create/update/delete/query calendar events. Fuzzy token matching, anaphoric memory. |
| `assistant/actions/todo/action.py` | 5 todo actions (create/complete/delete/update/query). Multi-task create via `titles: List[str]`. |
| `assistant/actions/__init__.py` | `ActionRegistry` Borg singleton. Builds system prompt for LLM. |
| `assistant/db.py` | Thread-safe SQLite. `get_db()` singleton. Indexes on `events(date)`, `events(series_id)`, `todos(list, completed)`. |
| `assistant/calendar_ui/window.py` | Main PyQt6 window. **Eight**-view stack (`:470-486`): Month · Week · Day · **Agenda** · Tasks · Timer · Coursework · **Workout** — Agenda and Workout were added after this row was first written, and Coursework/Timer/Workout are each behind a `ui.show_*` flag. Polls the DB's mtime every 5 s (`:418`) and the status queue every 100 ms (`:397`). Draws **no** assistant trace: that moved out to `assistant/thinking_hud.py`. |
| `assistant/thinking_hud.py` | The assistant's thinking card, as its own process — always on top, never focused, translucent until you hover it. It is separate on purpose: a command given from the phone arrives while you are working in something else, and the calendar app may not even be open. Started by `Launch Calendar.command`; tails `assistant/trace_bus.py`. Settings › Assistant (`ui.show_thinking`, `ui.thinking_corner`) still control it — it re-reads `config.yaml` when the mtime changes. **Not `Qt.Tool`**: macOS hides tool windows whenever their app is inactive, and this one never is. |
| `assistant/calendar_ui/thinking_panel.py` | The card itself (step rows, result card, tap-a-word fix, 👍/👎, `_RevertBar` for one-tap revert). Three views, toggled by the two header buttons: the live **timeline**, **History** (read back from the trace bus), and the **LLM console** (`_set_view` at `:1643`; `_LLMRow` at `:1131`). Just a widget; the HUD is what hosts it. |
| `assistant/llm_bus.py` | The LLM call log the console reads: one line per Ollama call with caller, transport and ms. Its own file (`~/.assistant_tools/llm_calls.jsonl`) and its own 400-line budget, deliberately not the trace bus — the HUD holds one current run and one file offset, so interleaved model calls in the same file would tear the timeline. |
| `assistant/calendar_ui/agenda_view.py` | Flat chronological list across a date range. Mac-only; no iPhone equivalent. |
| `assistant/calendar_ui/workout_view.py` | Training blocks, templates and session logs, incl. distance/pace sets. |
| `assistant/calendar_ui/day_view.py` | Hourly timeline, resize handles (8px top/bottom), drag-to-move. |
| `assistant/calendar_ui/week_view.py` | 7-column week grid, resize handles, drag-to-move. |
| `assistant/calendar_ui/month_view.py` | Month grid, shades Sun/Tue/Thu/Sat columns. |
| `assistant/calendar_ui/todo_view.py` | Tasks panel. All signals deferred via `QTimer.singleShot(0)` to prevent re-entrant crashes. `TodoItemWidget` (L700) has inline `▸` expand button → `TodoDetailPanel` (L160) with notes/subtasks/attachments/tags/due-date/priority. `_TagBar` = filter chips (All/tags/Untagged/+) plus the "tag mode" combo (`config.todo.auto_tag`: every new task — UI, voice, or API without explicit tags — gets that tag). With tag mode off, a task created with no tag gets one inferred from its title by `assistant/actions/todo/tagging.py` ("buy chicken" → Groceries; nothing when unsure; `config.todo.auto_tag_infer: false` turns it off). Tags live in `todos.tags` (JSON list) + `todo_tags` palette table. |
| `assistant/calendar_ui/coursework_view.py` | Coursework panel. Two-pane: course list (left) + assignment panel (right). Stores courses + assignments in SQLite. Calendar sync writes a `📚` event via `db.create_event_from_dict()`. |

---

## Configuration (`config.yaml`)

| Section | Key Settings |
|---------|--------------|
| `llm_engine` | `ollama` (default), `openai`, `gemini`, `claude` |
| `ollama.timeout_seconds` | `60` default; scales dynamically +15s per extra detected action |
| `verify_fast_path` | **Dead key.** It gated the old brain's `verify_fast_path_async`, turned off 2026-08-28 after four audit runs in which it proposed a correction on ~96% of commands and fixed none while adding ~14 s to every command. Nothing reads it today — `grep -rn verify_fast_path assistant/` returns only the dataclass field (`assistant/config.py:282`) and the unrelated method name. Note `config.example.yaml:73` still sets it `true`, which is harmless only because it is inert. The live equivalent is the engine's own review, gated by `self_check_apply`. |
| `audio.silence_duration_sec` | `6.0` — stops 6s after speech ends (or on keyword) |
| `whisper.beam_size` | `1` — greedy decode, ~4× faster than beam_size=5 |
| `tts` | `voice`, `rate`, `mute` |
| `confirmation_level` | `0` (Auto-Approve) or `1` (Manual). **Has no effect any more** — the dialog belonged between parse and execute, and both now happen in the API process, which cannot put a window on this screen. `pipeline.py:81-88` logs a warning at startup if it is above 0. The settings dialog still shows the checkbox (`settings_dialog.py:418-427`). |
| `stt_engine` | `"whisper"` (faster-whisper, CPU) or `"mlx"` (Apple GPU). This machine's `config.yaml` uses `mlx`. |
| `self_check_apply` | `false` — the background review only *says* a missing ask or an extra row; it does not add or remove rows. |
| `engine.fast_track` | `true` — `false` sends every command down the foreground deep track. |
| `todo.sync.mode` | `"off"` / `"today"` / `"general"` |

---

## Architecture Notes

### Adding New Actions
1. Add intent model to `assistant/actions/<domain>/intent.py`
2. Add `@register` class to `assistant/actions/<domain>/action.py`
3. Re-export from `assistant/actions/<domain>/__init__.py`
4. Optionally set `view_switch: ClassVar[str]` to auto-switch UI view post-execution

### View-Switching Actions
Set `view_switch = "switch_today"` / `"switch_todo"` on a `BaseAction` subclass. Pipeline sends it to the UI after execution. Handle in `window.py`'s `_handle_status()`.

### Crash Prevention Pattern
All signals that trigger widget rebuild (`todo_changed`, `resized`) are deferred with `QTimer.singleShot(0, signal.emit)` to prevent use-after-free from re-entrant `deleteLater()` calls.

### Code Map
For precise file + line pointers across all subsystems see **[CODE_MAP.md](CODE_MAP.md)**.

---

## Repo & Running

- **GitHub**: `https://github.com/GilCaplan/MACalendar`
- **Launch**: Double-click `Launch Calendar.command` or `python -m assistant.main`
- **DB**: `~/.assistant_tools/calendar.db` (SQLite)
- **Logs**: `~/.assistant_tools/assistant.log`
- **Tests**: `./.venv/bin/python -m pytest tests/unit` (fast, no model), `tests/integration` (skips without Ollama), `tests/` for what CI runs. Use the project venv — a bare `python` may be a pyenv shim without `astral`/`pytest`/spaCy, which reports collection errors that look like real regressions. The two loose files at the top of `tests/` (`test_ollama_parser.py`, `test_todo_parser.py`) predate that layout.
- **Health check**: `./.venv/bin/python -m assistant.cli doctor` — see [CLI.md](CLI.md)

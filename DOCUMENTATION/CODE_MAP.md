# MACalendar — Code Map

> **Purpose**: where to look first for common bug-fixing and feature work.
> Read this before searching the codebase.

> **No line numbers, on purpose** (2026-09-11). This file used to carry a line
> number per row, and every single one had rotted: `analyze()` was listed at
> L1003 and lives at 1753, `create_app` at L134 and lives at 252, `CalendarDB`
> at L93 and lives at 655. Worse, the numbers made the *dead* rows look alive —
> three files and a script listed here no longer existed. A line number is
> stale the first time anyone edits above it and nothing tests it, so rows now
> name a **file and a symbol**, which `grep` finds and which survives an edit.
> If you add a row, name the symbol, not the line.

---

## The Engine — `assistant/engine/` (THE BRAIN)

**Start at `assistant/engine/ARCHITECTURE.md`** — the chain as a diagram, each
stage as a black box, and a status table saying which parts are wired today
versus planned in `ENGINE_REWIRE.md`.

> Contracts frozen — read `DOCUMENTATION/ENGINE.md` before touching a stage.
> FastRule is mid-restructure; `assistant/engine/fastrule/PLAN.md` §3 is the
> phase plan, and the module rows below change when phase B lands.

| What | Location |
|------|----------|
| Orchestrator `run_transcript` (response contract, track selection) | `engine/__init__.py` |
| `Engine.judge` — the crosscheck loop and its re-entry budget | `engine/__init__.py` |
| Commit (only DB touchpoint; TargetNotFound recheck `_recheck_not_found`) | `engine/__init__.py` |
| `EngineState` / `Item` / `Fix` dataclasses (the inter-stage contract) | `engine/state.py` |
| The authoritative ordered stage list | `engine/state.py` → `STAGES` |
| Ingest: stop words, trivial filter, vocab, `needs_edit` gate | `engine/ingest/repair.py` |
| Ingest: queue coalescing | `engine/ingest/coalesce.py` |
| Segmentation entry + envelope split (FastSeg is the DEFAULT) | `engine/segmentation/__init__.py` |
| decompose_validate — the stage entry, both passes | `engine/decompose_validate/stage.py` |
| …its value resolver and checks (authoritative since 2026-09-08) | `decompose_validate/resolve.py`, `checks.py` |
| …targeting, object rules, observance gate | `decompose_validate/targeting.py`, `object_rules.py`, `observance_gate.py` |
| FastRule the component (Atomicity / Scorer, the DEFER reason classes) | `engine/fastrule/fastrule.py` |
| FastRule the stage: items → intents, `fast_propose`, `_parse_item` | `engine/fastrule/stage.py`, `engine/fastrule/objects.py` |
| LLMJudge: extract-and-compare, BLAME router, `MAX_REENTRIES` | `engine/llmjudge/llmjudge.py` |
| …Gatekeeper and the LLM fallback (ported here 2026-09-09) | `llmjudge/gatekeeper.py`, `llmjudge/llm_fallback.py` |
| Label read-back (runs inside commit) | `engine/label/label.py` |
| Contract pins | `tests/unit/test_engine_contracts.py` |
| **Per-stage docs** — what it is, its datasets, its metrics, its results | `engine/<stage>/ARCHITECTURE.md` |
| Segmentation's two halves | `engine/segmentation/fastseg/`, `engine/segmentation/llmseg/` (LLMSeg **off** by default) |
| Segmentation's datasets and boards | `engine/segmentation/datasets/`, `engine/segmentation/experiments/` |
| FastRule's dataset (7,200 rows) and boards | `engine/fastrule/datasets/`, `engine/fastrule/experiments/` |
| Shared LLM transport (`call_json`, `MACALENDAR_LLM_DISABLED` guard) | `engine/llm.py` |
| The three routing classifiers + one shared `LogisticModel` | `intent/classifier.py` |
| Spoken-noise cleanup — filler, courtesy, hedges, self-corrections | `intent/cleanup.py` |
| Lead-time reader (shared by FastRule AND decompose — one copy) | `intent/lead_time.py` |
| Recurrence as a SLOT (cadence, rounding, series anchor) | `intent/recurrence.py` |
| NP- vs clause-coordination — a feature, a gate, AND the split boundary | `intent/coordination.py` |
| Is this fragment an ASK? (segment's clause tier and decompose's list tier) | `intent/asks.py` |
| Product-shape board / atomicity board / persona board / kind board | `engine/fastrule/experiments/fastrule_shape.py`, `scripts/atomicity_board.py`, `scripts/persona_board.py`, `scripts/kind_board.py` |
| Fit the routing models (train halves only, deterministic) | `scripts/fit_route_models.py` |
| Per-stage live gates | `scripts/engine_stage_check.py` |
| Mac gate dialog (`ask_transcript_edit`, `STATUS_EDIT`) | `calendar_ui/window.py`, `pipeline.py` |

**Two things are wired but deliberately INERT** — do not read their presence as
behaviour: LLMSeg (`MACALENDAR_LLMSEG`), and the judge's loop-back, which is
gated on `llmjudge.rewrite_for_retry` — a stub returning `None`, so no loop
fires.

---

## Database — `assistant/db.py`

One class, `CalendarDB`, plus a `get_db()` singleton. Find a method by name.

| What | Symbol |
|------|--------|
| Table creation, migrations | `CalendarDB.__init__`, `_migrate_todos`, `_TODO_MIGRATIONS`, `_CREATE_SUBTASKS_TABLE` |
| Connection context manager | `CalendarDB._conn` |
| **Events** | `create_event`, `create_event_from_dict`, `update_event`, `delete_event` |
| Series | `update_series`, `delete_series_from` |
| **Todos** | `create_todo`, `get_todos`, `update_todo` (allowed-fields set), `toggle_todo_complete` |
| | `delete_completed_todos`, `reorder_todos`, `sync_calendar_to_todos` |
| **Subtasks** | `get_subtasks`, `create_subtask`, `update_subtask`, `delete_subtask`, `reorder_subtasks` |
| | `delete_subtasks_for_todo` — **call before `delete_todo`** |
| **Timers** | `create_timer`, `get_timers`, `update_timer`, `delete_timer` |
| Timer sessions | `create_timer_session`, `get_timer_sessions`, `get_running_session` |
| | `update_timer_session`, `stop_timer_session`, `delete_timer_session`, `split_timer_session` |

**Schema — `todos`:** `id, title, list, completed, priority, due_date, notes,
source, source_event_id, created_at, completed_at, position, attachments`
**Schema — `subtasks`:** `id, todo_id, title, completed, position, created_at`
**Schema — `timers`:** `id, title, hourly_rate, color, created_at, archived`
**Schema — `timer_sessions`:** `id, timer_id, title, start_time, end_time
(NULL = running), notes, created_at`

---

## GUI voice client — `assistant/pipeline.py` (records + posts; NEVER parses)

The GUI records audio and POSTs the transcript to `127.0.0.1:8080/voice/text`.
**All parsing and execution happen in `assistant.api` → the engine.** Rows about
a rule-parser decision point, `parse_with_context`, `_background_verify`,
`_detect_user_change` or `_parse_segment` used to live here and are gone with
the code — if you are looking for any of those, you want `assistant/engine/`.
(`Pipeline._parser` survives for `health_check()` only.)

| What | Symbol |
|------|--------|
| `Pipeline` class, status callback | `Pipeline.__init__` |
| Mic button handler, session queuing | `Pipeline.trigger` |
| The record → STT → POST flow | `Pipeline._run_pipeline`, `_process_transcript` |
| Review / edit / confirm gates the engine can ask for | `_await_review`, `_await_transcript_edit`, `_await_create_confirm` |
| Status → `CalendarWindow` | `Pipeline._set_status` |
| Opens the Mac's streaming trace-bus run | `Pipeline._trace_begin` |
| Writes `DOCUMENTATION/SCENARIO_BUG.md` / `NLU_TRACKING.md` | `_append_scenario_bug`, `_append_nlu_log` |

**Status values** (`pipeline.py`): `STATUS_IDLE`, `STATUS_LISTENING`,
`STATUS_PROCESSING`, `STATUS_DONE`, `STATUS_ERROR`, `STATUS_REVIEW`,
`STATUS_EDIT`, `STATUS_CONFIRM`. The view-switch ones (`STATUS_REFRESH`,
`STATUS_SWITCH_TODAY`, `STATUS_SWITCH_TODO`) are in `calendar_ui/window.py`.

---

## Rule-Based NLU — `assistant/intent/rule_parser.py`

| What | Symbol |
|------|--------|
| `RULE_THRESHOLD = 0.80` (whole command; tuned 2026-09-07) | module constant |
| `RuleParseResult` dataclass | `RuleParseResult` |
| `RuleParserSkip` exception (raised → LLM fallback) | `RuleParserSkip` |
| Phase 0 — preprocess + complexity gate | `_preprocess` |
| Phase 1 — multi-intent split | `_split_intents`, `_lexicon_split_points` |
| Phase 2 — temporal extraction | `_extract_temporal`, `_normalize_time` |
| Phase 3 — intent/domain routing | `_route_intent` |
| Phase 4 — slot filling | `_fill_slots`, `_extract_title`, `_clean_title` |
| Phase 5 — anaphora resolution | `_resolve_anaphora` |
| Phase 6 — confidence scoring | `_compute_confidence`, `_compute_missing_slots` |
| Entry point | `RuleBasedParser.analyze` |
| Raises `RuleParserSkip` if low confidence | `RuleBasedParser.parse` |

spaCy and the date recognizer are **probed at import, loaded on first parse**
(`_ensure_nlp`, `_ensure_dt`). Absent spaCy disables the rule parser entirely
and every command takes the deep track — which is what a dev box without the
`nlp` extra looks like.

---

## Assistant trace — `assistant/trace_bus.py` + `assistant/thinking_hud.py`

The card showing what the assistant did is its own process. Producers append to
a JSONL file; the HUD tails it. Two line shapes: a whole run at once
(`kind: "trace"` — what the API server publishes for the phone) or a run
streaming as it happens (`begin` / `step` … / `result` — what the Mac pipeline
publishes, so the card fills in live).

| What | Symbol |
|------|--------|
| One finished run | `trace_bus.publish` |
| A streaming run | `publish_begin`, `publish_step`, `publish_result` |
| Trims only at a run's start, so no run is cut in half | `trace_bus._trim` |
| Frameless, always-on-top, never focused | `ThinkingHUD` |
| Renders one bus line | `ThinkingHUD.apply_entry` |
| Tails the bus, notices `config.yaml` changing | `_BusReader.poll` |
| `BRAIN_VERSION` + `CHAINS` — what the panel renders from | `assistant/trace.py` |

Three ways this window has already managed to be invisible while insisting it
was fine (`isVisible()` true, right size, right place):

- It is `Qt.Window`, **not** `Qt.Tool`. macOS hides a tool window whenever its
  application is not active, and this app is never active (accessory, no Dock
  icon) — so `Qt.Tool` hid it in exactly the case it exists for.
- `_follow_every_space()` sets the Cocoa collection behaviour. Without it the
  card belongs to the Space it was created on, so switching to a full-screen app
  left it behind. It is re-applied on every show, and skipped unless
  `QApplication.platformName() == "cocoa"` — handing an offscreen-platform
  `winId()` to pyobjc **segfaults the interpreter**, which took the test suite
  down with it.
- `_park()` clamps a restored position into the current screen. A stale
  `~/.assistant_tools/hud_position.json` from a screen that no longer exists put
  it just below the usable area, drawn but off the edge.

Debugging one of these from the outside: probe the real NSWindow
(`objc.objc_object(c_void_p=...int(self.winId())).window()`) for `isVisible()`,
`collectionBehavior()`, `level()` and `alphaValue()` — Qt's own view of the
window says everything is fine in all three cases.

---

## Multi-item splitting — `assistant/intent/list_split.py`

One phrase → the several things it asks for. "buy chicken and rice" is two
tasks and the verb is shared out ("buy rice", not "rice"); an "and" after a
preposition ("a gift for mom and dad") or inside a name ("fish and chips") is
not a separator. Pure strings, no spaCy.

| What | Symbol |
|------|--------|
| Verbs a title can start with | `ACTION_VERBS`, `ACTION_PHRASES` |
| The separator-vs-internal "and" decision | `split_on_and` |
| Hands the verb to conjuncts without one | `distribute_lead_verb` |
| The whole thing; used by the rule parser and the todo actions | `split_items` |

## Task tags — `assistant/actions/todo/tagging.py`

Keyword classifier over a task title, same shape as the event categories.
Returns a tag only when the palette has it, and nothing when unsure.

| What | Symbol |
|------|--------|
| Per-tag word lists | `KEYWORDS` |
| The classifier | `infer_tag` |
| Palette-aware wrappers | `suggest_tags`, `resolve_tags` |

---

## LLM Intent Parser — `assistant/intent/parser.py`

| What | Symbol |
|------|--------|
| The class | `IntentParser` |
| Full LLM parse from scratch | `IntentParser.parse` |
| Partial handoff (fills gaps from the rules' analysis) | `IntentParser.parse_with_context` |
| Background judge thread | `IntentParser.verify_fast_path_async` |

## Context Memory — `assistant/intent/context.py`

| What | Symbol |
|------|--------|
| Borg singleton | `ContextMemory` |
| Module-level instance | `context_memory` |

Used by the rule parser (`_resolve_anaphora`) and by actions for "delete it",
"move that".

---

## Actions System

### Registry — `assistant/actions/__init__.py`
| What | Symbol |
|------|--------|
| The registry | `ActionRegistry` |
| The decorator action classes self-register with | `register` |
| Assembles the LLM system prompt | `build_system_prompt` |

### Base class — `assistant/actions/base.py`
| What | Symbol |
|------|--------|
| The ABC | `BaseAction` |
| Set on a subclass to auto-switch the UI view | `view_switch: ClassVar[Optional[str]]` |
| Abstract | `execute()` |

### Calendar actions — `assistant/actions/calendar/action.py`
| Class | view_switch |
|-------|-------------|
| `CreateEventAction` | — |
| `UpdateEventAction` | — |
| `DeleteEventAction` | — |
| `QueryScheduleAction` | `"switch_today"` |
| `_find_event()` fuzzy matcher | |

### Todo actions — `assistant/actions/todo/action.py`
| Class | view_switch |
|-------|-------------|
| `CreateTodoAction` | `"switch_todo"` |
| `CompleteTodoAction` | — |
| `DeleteTodoAction` | — |
| `UpdateTodoAction` | — |
| `QueryTodoAction` | `"switch_todo"` |
| `_find_todo()` fuzzy matcher | |

### Intent models
| File | Contents |
|------|----------|
| `assistant/actions/calendar/intent.py` | `CalendarIntent`, `UpdateEventIntent`, `DeleteEventIntent`, `QueryScheduleIntent` |
| `assistant/actions/todo/intent.py` | `CreateTodoIntent` (`titles: List[str]`), `CompleteTodoIntent`, `DeleteTodoIntent`, `UpdateTodoIntent`, `QueryTodoIntent` |

---

## Mac UI — `assistant/calendar_ui/`

### Main Window — `window.py`
| What | Symbol |
|------|--------|
| The window | `CalendarWindow` |
| View stack setup | `_build_ui` |
| Top toolbar | `_build_toolbar` |
| Receives pipeline status, triggers refresh / view-switch | `_poll_status` (100 ms timer) → `_handle_status` |
| Refreshes | `refresh_calendar`, `refresh_todos` |
| Switches Month / Week / Day / Tasks | `_set_view` |
| Opens the event detail view | `_on_event_clicked` |
| Theme and config | `_apply_theme`, `_apply_ui_config`, `_on_settings_popup` |

**Adding a new view:** add a stack page in `_build_ui()`, handle a new
`STATUS_SWITCH_XXX` in `_handle_status()`, set `view_switch = "switch_xxx"` on
the action class.

### Tasks (Todo) View — `todo_view.py`
| What | Symbol |
|------|--------|
| 2-field modal for embedded hyperlinks | `InsertLinkDialog` |
| Compact checkbox row for subtasks | `SubtaskRow` |
| Expandable inline panel | `TodoDetailPanel` (`_build`, `load`, `_switch_to_edit`, `_on_insert_link`, `_reload_subtasks`, `_on_add_attachment`) |
| Single task row | `TodoItemWidget` (`_build`, `_toggle_expand`, `_update_item_size`, `set_list_item`) |
| The list | `TodoListWidget` (`populate`, `_on_deleted`, `_make_new_task_row`) |
| Section header, the view | `SectionHeader`, `TodoView.refresh` |

**Crash prevention pattern (important):** every signal that triggers a widget
rebuild uses `QTimer.singleShot(0, signal.emit)` to prevent re-entrant
`deleteLater()` crashes — see `_on_toggled`, `_on_edited`, `_on_deleted`.

**QListWidget expand pattern:** `_toggle_expand()` → `_detail_panel.show()/hide()`
→ `_update_item_size()` → `item.setSizeHint(self.sizeHint())` +
`list_widget.setFixedHeight(recalculated)`.

### Timer View — `timer_view.py`
| What | Symbol |
|------|--------|
| Main container, 1 s `QTimer` drives all live displays | `TimerView` |
| Single timer card (header + collapsible sessions) | `TimerCard` |
| Collapsible list of `SessionRow` widgets | `SessionsPanel`, `SessionRow` |
| Create/edit dialogs | `TimerDialog`, `SessionEditDialog` |
| HH:MM:SS and $X.XX helpers | `_fmt_duration`, `_fmt_earnings` |

Timer is purely UI-local (no voice action). Data stays in local SQLite, never
synced to iOS.

### Other Views
| File | Class | Key method |
|------|-------|------------|
| `day_view.py` | `DayView` | `_build_timeline()`, resize handles (top/bottom 8px) |
| `week_view.py` | `WeekView` | 7-column grid |
| `month_view.py` | `MonthView` | `refresh()` → `_rebuild_grid()`; cells are `DayCell`, `EventPill`, `HolidayBanner` |
| `agenda_view.py` | `AgendaView` | flat upcoming list |
| `sidebar.py` | `Sidebar` | mini calendar, date selection |
| `event_dialog.py` | `EventDialog` | create/edit event form |
| `styles.py` | — | `get_app_style(dark)` — full Qt stylesheet; colour constants |

---

## Flask API — `assistant/api/server.py`

Every route is nested inside the `create_app()` factory; find one by its view
function name.

| What | Symbol |
|------|--------|
| The factory | `create_app` |
| API-key guard (`X-API-Key`; null key = no auth) | `_enforce_api_key` |
| Shared voice logic — hands text to the engine, never parses | `_run_transcript` |
| POST `/voice`, POST `/voice/text` | `voice_audio`, `voice_audio_stream`, `voice_text` |
| GET `/voice/verify/<token>` — the background-check poll | `voice_verify` |
| POST `/voice/confirm` — the Q9 confirm-create answer | `voice_confirm` |
| Events, todos, categories, timers, counters, vocab, memory, pending | `events_list`, `event_get`, `event_ics`, `categories_*`, `timers_*`, `counters_*`, `vocab_*`, `memory_*`, `pending_*` |

**`DOCUMENTATION/API_REFERENCE.md` is GENERATED** — after adding or changing an
endpoint run `python scripts/gen_api_reference.py`; never hand-edit it.

---

## Config — `assistant/config.py`

| Model | Key fields |
|-------|------------|
| `AppConfig` | `llm_engine`, `confirmation_level` (inert — see CLAUDE.md), `verify_fast_path`, `engine`, `nlu` |
| `UIConfig` | `font_month/week/day/tasks/coursework`, `compact_ui`, `accent_color`, `show_week_numbers`, `show_thinking`, `thinking_corner` |
| `TodoConfig` | `show_completed`, `sync.mode` |
| `AudioConfig` | `silence_duration_sec`, `device_index`, `event_separator` |
| `TTSConfig` | `voice`, `rate`, `mute` |
| Loader | `load_config()` — reads `config.yaml` |

`config.yaml` is gitignored; mirror any new setting into `config.example.yaml`.

---

## Adding a New Action (checklist)

1. Add the intent model to `assistant/actions/<domain>/intent.py`
2. Add a `@register` class to `assistant/actions/<domain>/action.py` (see `BaseAction`)
3. Set `view_switch: ClassVar[str]` if the action should auto-switch the UI view
4. Re-export from `assistant/actions/<domain>/__init__.py`
5. `ActionRegistry` and the LLM system prompt pick it up automatically

---

## Common Bug Areas

| Symptom | Where to look |
|---------|--------------|
| Task list doesn't update after change | the `QTimer.singleShot(0, …emit)` pattern in `TodoListWidget`; `TodoView.refresh` |
| Enter key in new task field does nothing | `_commit()` in `_make_new_task_row()` — check `blockSignals` not left True |
| Expanded task row doesn't resize | `TodoItemWidget._update_item_size` |
| Subtasks not deleted with parent task | `TodoListWidget._on_deleted` must call `delete_subtasks_for_todo()` first |
| Voice command goes to LLM instead of fast path | `RULE_THRESHOLD = 0.80` (whole) / `SUBITEM_RULE_THRESHOLD = 0.60` (fragment) — check `RuleParseResult.confidence` |
| Every command takes the deep track on a dev box | spaCy missing — `_RULE_PARSER_AVAILABLE` is False and the rule parser is disabled entirely |
| New DB field not persisting | add to `_TODO_MIGRATIONS` **and** to `update_todo`'s `allowed` set |
| View doesn't switch after voice action | set `view_switch` on the action class; handle the value in `CalendarWindow._handle_status` |
| iOS sync not seeing new field | check `Models.swift` `Todo` struct and `APIClient.swift` `updateTodo()` |
| A change to the GUI or HUD "has no effect" | only the API reloads itself; restart the calendar GUI and the HUD by hand |

# Feature catalog

Every feature of the software, one entry each: what it is, where it lives
across the codebase, and how it's implemented. **When a feature ships, its
entry lands here in the same change** — this file is the inventory the rest of
the workflow (STATUS.md, TASKS.md) assumes exists. Deeper docs are linked
rather than duplicated.

Format per entry: **What** (brief) · **Where** (all surfaces) · **How**
(technical notes).

Entries are grouped by **layer**: pure UI (client-side only — the backend
needs no knowledge of them), hybrid (coordinated frontend + backend), and
purely backend (no client code beyond displaying the effects).

## The table

| layer | feature | in one line | mainly lives in |
|---|---|---|---|
| UI | [Navigation chrome](#navigation-chrome) | sidebar, mini calendar, tabs, Today | `sidebar.py`, `window.py` |
| UI | [Design system & theming](#design-system--theming) | light/dark, live accent, fonts, toasts | `styles.py`, `Theme.swift` |
| UI | [Direct editing & undo](#direct-manipulation-editing--undo) | drag-reschedule/resize, dbl-click create, ⌘Z | views, `window.py` |
| UI | [Morning briefing](#morning-briefing) | Brief Me: today summarised + spoken | `day_view.py` |
| UI | [Tasks power features](#tasks-power-features) | rich notes, sorts, reorder, cal→tasks sync | `todo_view.py` |
| UI | [Search & jump-to-date](#search--jump-to-date) | toolbar search over events/tasks; type a date to jump | `window.py`, `SearchView.swift` |
| UI | [Small conveniences](#small-conveniences) | duplicate event, week numbers, Timer CSV export | `event_dialog.py`, `month_view.py`, `timer_view.py` |
| UI | ["How to Talk to Me" tips](#how-to-talk-to-me-tips) | 5 short, verified voice-phrasing tips (Settings → Assistant) | `tips.py`, `tips_dialog.py` |
| assistant | [Personal lexicon](#personal-lexicon) | the engine's word lists, extendable from Settings so it learns how you say things | `intent/lexicon.py`, `/lexicon` |
| UI | [Foldable settings sections](#foldable-settings-sections) | every Settings section collapses, and stays collapsed, on both apps | `settings_dialog.py`, `SettingsView.swift` |
| hybrid | [Calendar views](#calendar-views-month--week--day) | month/week/day/agenda browsing + event CRUD, drag, undo | `calendar_ui/`, iOS views, `db.py` |
| hybrid | [Tasks](#tasks--to-dos) | Today/General lists, priorities, quantities | `db.py`, `TasksView` |
| hybrid | [Tag discovery](#tag-discovery--the-class-set-grows-with-consent) | consent-based new classes + history | `actions/todo/tag_discovery.py` |
| hybrid | [Share event as .ics](#share-event-as-ics) | one event → RFC 5545 file, both platforms | `ics_export.py`, `event_dialog.py` |
| hybrid | [The day panel](#the-day-panel) | one on/off summary of today's events + tasks; server owns the wording; the phone lodges a week ahead so it arrives with the Mac asleep | `notify.py`, `notifier.py`, `GET /digest[/upcoming]`, `ReminderScheduler.swift` |
| hybrid | [Pre-event notifications (dormant)](#pre-event-notifications-dormant) | server computes policy; per-category mute — superseded by the day panel above, kept behind a flag on the MAC only (the phone's half is retired). The live "Up Next" lock-screen card is not dormant and still runs | `notify.py`, `LiveActivityManager.swift` |
| hybrid | [Home-screen widget (iOS)](#the-home-screen-widget-ios) | "Up Next" + what's left of today, advancing with nothing of ours running | `MACalendarWidgets/UpNextHomeWidget.swift` |
| hybrid | [Voice I/O & capture controls](#voice-in--voice-out--capture-controls) | hotkey/stop-phrases/review-bar; engine-selectable STT; spoken replies | `stt/`, `Voice/`, `tts/` |
| hybrid | [Edit-transcription gate](#the-edit-transcription-round-trip-needs_edit) | doubted words → editor → learned | `engine/ingest/repair.py` |
| hybrid | [Confirm-create gate](#the-confirm-create-gate-confirm_create) | "should I add yoga tomorrow?" → Add / No, never a silent guess | `decompose_validate/object_rules.py`, `/voice/confirm` |
| hybrid | [Self-check & revert](#background-self-check--one-tap-revert) | background re-reasoning, one-tap undo | `engine/__init__.py`, panels |
| hybrid | [Review panel / HUD](#the-review-panel-thinking-hud--ios-timeline) | live chain-of-thought card + history | `thinking_hud.py`, `ThinkingView` |
| hybrid | [LLM console](#the-llm-console) | the panel's third view: every model call, with its caller | `llm_bus.py`, `thinking_panel.py` |
| hybrid | [Personal vocabulary](#personal-vocabulary) | user's words fix transcripts first | `stt/vocab.py` |
| hybrid | [Command memory](#command-memory--feedback) | every command + verdicts, mined | `intent/memory.py` |
| hybrid | [Tag suggestion history](#tag-suggestion-history) | the reviewable record behind the ask | `TagHistoryView.swift` |
| hybrid | [Import & connected calendars](#calendar-import--connected-calendars) | .ics/macOS import; ICS subscribe; Outlook 2-way | `window.py`, `calendar_sync/` |
| hybrid | [Workout & training](#workout--training-scheduling) | templates, live sessions, observance-aware planning | `actions/workout*`, `Features/Workout/` |
| hybrid | [Timer](#timer-work-tracking) | per-project work + earnings | db `timers*`, `TimerView` |
| hybrid | [Counters](#counters) | tap counters + payouts | db `counters*` |
| hybrid | [Coursework](#coursework) | courses + assignments tab | db `courses*`, `CourseworkView` |
| hybrid | [Jude](#jude--the-judaic-study-assistant) | Torah/Talmud/halacha study assistant — a separate repo, hosted as an integration | `assistant/jude/`, `assistant/integrations/`, `MACalendar-iOS/.../Jude/` |
| hybrid | [iOS app & offline](#ios-app--offline-queues) | full client, 3 offline queues, Tailscale | `MACalendar-iOS/` |
| hybrid | [Health CLI & heartbeats](#heartbeats--the-health-cli) | `assistant doctor`, 6 layers | `cli.py`, `heartbeat.py` |
| backend | [The engine](#the-engine-engine-v3--the-brain) | the AI brain: a fast track and a six-box deep chain | `assistant/engine/` |
| backend | [One-shot LLM engine](#the-one-shot-llm-engine--a-measuring-instrument) | a parallel brain of one model call, off by default | `engine/LLM_one_shot/` |
| backend | [The action set](#the-action-set) | the 15 things a command can do | `assistant/actions/` |
| backend | [Task tags](#task-tags--a-finite-classification) | closed-set classification w/ healing | `actions/todo/tagging.py` |
| backend | [Categories & stacking](#events-categories-colours--binder-stacking) | auto-colour/categorise; overlaps stack | `actions/calendar/categories.py` |
| backend | [Hebrew calendar & observance](#hebrew-calendar--observance) | sundown-bounded halachic windows; series skip, one-offs flagged | `observance.py`, `hebrew_calendar.py` |
| backend | [Recurring events](#recurring-events) | daily/weekly/monthly/yearly, several weekdays, announced rounding | `db.py`, `decompose_validate/resolve.py` |
| backend | [API server](#the-api-server) | the single front door, 126 endpoints | `api/server.py` |
| backend | [Hosted calendar sync](#hosted-calendar-sync) | optional Outlook two-way / ICS read | `calendar_sync/` |
| backend | [Self-improvement loop](#the-self-improvement-loop) | the AI measures & improves itself | `dataset/`, `scripts/` |
| backend | [Diagnostics & logs](#diagnostics--self-observation-logs) | NLU tracking, LLM-judge bug log, audit, calibration | `scripts/` |
| backend | [Explainer pages](#published-explainer-pages) | public pages, build-enforced claims | `artifacts/*.html` |
| backend | [Request protocol](#request-protocol) | one ollama, many callers: enrolled devices, merge-vs-queue, live beats background | `model_protocol.py`, `api/server.py` |
| backend | [Weekly review](#weekly-review) | real-usage flag-rate report | `scripts/weekly_review.py` |

---

## UI features — client-side only

### Navigation chrome
**What:** Sidebar with one-click New Event and a mini month calendar
(wheel-scroll months, fade transitions); toolbar prev/next/Today, an eliding
title with Hebrew-date suffix, and segmented view tabs (Month / Week / Day /
Tasks / Timer / Coursework / Workout — the last three hideable in settings).
**Where:** `calendar_ui/sidebar.py`, `calendar_ui/window.py`.
**How:** Pure view-layer; tab visibility persists to config.

### Design system & theming
**What:** Light/dark theme (startup setting + one-click toolbar toggle with
toast), accent colour presets + custom picker applied live app-wide,
per-view font sizes, compact density, and centered auto-fading toasts;
theme-aware SVG icon tinting.
**Where:** `calendar_ui/styles.py` (`set_accent`, palettes),
`calendar_ui/icons.py` (rasterised per name/colour/size), settings popup in
`window.py`; iOS `Theme.swift` + `AppSettings.swift`.
**How:** One accent hex derives hover/pressed states; the whole QSS sheet
regenerates on toggle (cached per palette — the PyQt6 QSS-caching gotcha).

### Direct-manipulation editing & undo
**What:** Drag an event to another day/slot (30-min snap), drag its edges to
resize (15-min snap), double-click a cell/slot to create pre-filled; editing
or deleting a repeating event asks "this instance or the series?"; ⌘Z /
⇧⌘Z undo/redo with a toast naming what was reverted.
**Where:** month/week/day views + `calendar_ui/window.py`
(`_on_event_rescheduled`, `_on_undo/_on_redo`), `event_dialog.py`.
**How:** An undo stack of inverse operations over db writes; drag PATCHes
feed the same implicit-feedback hooks as any edit.

### Morning briefing
**What:** A "Brief Me" button on the Day view — the day's schedule
summarised as a toast and spoken aloud.
**Where:** `calendar_ui/day_view.py` + `window.py`
(`_on_briefing_requested`); TTS.
**How:** Reads the day's rows directly; honours the mute/voice settings.

### Tasks power features
**What:** Rich task notes (bold/italic, insert-link) auto-saved while
typing; Manual/Priority/Due-date sort modes; drag-to-reorder; Clear
Completed per section; priority dots and due-date picker; a Manage-tags
sheet on iOS (built-ins protected); calendar→tasks sync (pull today's or the
week's events into Today/General, with an auto mode).
**Where:** `calendar_ui/todo_view.py`; `db.sync_calendar_to_todos`; iOS
`TasksView`/`TaskRowView` + manage-tags sheet.
**How:** Synced rows carry `source='calendar_sync'` so they update rather
than duplicate; manual order is a `position` column, disabled under sorted
modes.


## Hybrid — coordinated frontend + backend

### Calendar views (month / week / day)
**What:** The Outlook-style calendar — browse, create, edit, drag-reschedule
events; undo/redo. A fourth Agenda mode (Mac only) lists the next 30 days'
events chronologically, grouped by day, with day headers skipping empty days.
**Where:** Mac `assistant/calendar_ui/` (`window.py`, `month_view` / week / day
/ `agenda_view.py` views, `styles.py`); iOS `Features/Calendar/MonthGridView.swift`,
`WeekView.swift`, `DayView.swift`, `EventDetailView.swift`; data
`assistant/db.py` (`events`).
**How:** PyQt6 on Mac, SwiftUI on iOS; both are thin clients over the same
SQLite file via the API. Optimistic concurrency via `updated_at` stamps;
drag-reschedule PATCHes and records implicit feedback on voice-created rows.
Agenda anchors on a `set_start_date` date (Today resets it, nav arrows step a
week), clicking a row opens the same edit dialog as the other views, and day
headers append the Hebrew date when `hebrew_calendar.display_mode` isn't
`english` — same rule as the Week header cells.

### Tasks / to-dos
**What:** Two lists (Today, General) with priorities, due dates, notes,
attachments, quantities ("pasta ×5") and subtasks.
**Where:** `assistant/db.py` (`todos`, `subtasks`); Mac tasks pane; iOS
`Features/Tasks/TasksView.swift`, `TaskRowView.swift`; API `/todos*`.
**How:** Quantities parse from speech or typed titles
(`assistant/intent/quantity.py`, `split_quantity`); list is a column, not a
table — the two-list design is deliberate (see tag classes for the axis that
does grow). **Creating a task is idempotent:** a client mints one
`client_token` per task the user asked for and repeats it on every attempt —
the live `POST /todos` and each replay of the same queued create — and the
server returns the row it already stored (200, `{"id": …, "duplicate": true}`)
instead of inserting a second one. `todos.client_token` carries the key with a
unique index over non-empty values; in-process creators (voice, calendar sync,
the Mac tasks pane) leave it empty because they never cross the wire. Added
2026-09-06 after 32 copies of one task accumulated in Today, one per repeated
`POST /todos`.
**A content fingerprint is the second net**, because that index only referees
*non-empty* tokens — a caller that sends none was still an unconditional
insert. A token-less `POST /todos` naming a task that is already open, spelled
the same (case- and spacing-insensitive), in the same list, created less than
`todo.duplicate_window_seconds` ago (default 120, 0 = off) returns that row
(200, `{"id": …, "duplicate": true, "reason": "recent-identical"}`).
Completed rows never match, so re-adding a task you ticked off still works, and
an explicit token always wins — two genuinely separate asks that say the same
thing are told apart by their tokens. Added 2026-09-07: the token-less caller
turned out to be the unit suite itself (see below), and by then the list held
45 copies.

### The test suite cannot write through the live API
**What:** No test may reach the `assistant.api` running on this Mac.
**Where:** `tests/conftest.py` (`_no_live_api_calls`, `LiveAPIBlocked`);
regression tests in `tests/unit/test_no_live_api_writes.py`.
**How:** The `MACALENDAR_*` scratch overrides redirect what the *test process*
opens; they cannot redirect an HTTP request, which is served by the live API
process holding the real `~/.assistant_tools` stores. An autouse session
fixture wraps both transports the codebase uses — `requests.Session.request`
and `urllib.request.urlopen` — and raises on any call to loopback at the API
port (Ollama's 11434 and the rest of loopback are untouched). Found 2026-09-07:
`test_thinking_hud.py` clicks the HUD's Revert button for real, the widget's
own `revert_requested → _on_revert` wiring is live in the fixture, and
`_on_revert` re-POSTs the captured body to `127.0.0.1:8080/todos` from a daemon
thread — so every `pytest tests/unit` run added one more "buy groceries" to the
real Today list, arriving 30 s–3 min after the run.
`cli.check_engine()`'s live probe was doing the same to the real command memory
and trace bus via `POST /voice/text`. `scripts/dedup_todos.py` cleans up rows
already made (dry-run by default; `--apply` backs the file up first).

### Tag discovery — the class set grows with consent
**What:** When ≥5 distinct untagged tasks share a theme no existing class
covers, the app asks once ("Add 'X' as a tag?") in a popup while the user is
actively there; a reviewable history allows reversing or hiding past verdicts.
**Where:** `assistant/actions/todo/tag_discovery.py`; API `/tags/suggestion`,
`/tags/suggestion/answer`, `/tags/suggestions/history`,
`/tags/suggestions/revise`; Mac popup in `calendar_ui/window.py`
(`_fetch_tag_suggestion`); iOS alert in `Views/ContentView.swift:498`, and the
history screen behind Tasks ▸ Manage tags ▸ Suggestion history —
`Views/TagHistoryView.swift`, reached from `TasksView.swift:572` (shipped
`902e8a4`).
**How:** Politeness is structural: evidence bar, ≤1 ask/7 days charged on
hand-out, refusals stored forever (`tag_suggestion_state` table), server never
pushes — clients pull only when foregrounded. Un-accepting from history
deletes the class again.

### Voice in / voice out — capture controls
**What:** Push-to-talk (mic button, ⌘J, or a global hotkey — default
⌘⇧Space) with configurable stop phrases, silence auto-stop (2–12 s), a
review-before-send Redo/Add-more/Send bar with countdown, a configurable
event-separator phrase ("next event"), instant placeholder-event keywords,
and mic multi-tap gestures (second tap within 400 ms cancels). A **trash
button discards a recording outright** — beside the mic while it is listening
and in the review bar on both platforms. Replies
optionally spoken (mute, voice picker, speaking rate, Test Audio preview).
**Where:** STT `assistant/stt/` (engine-selectable: local Whisper CPU,
Apple-GPU mlx-whisper, or opt-in Google cloud STT); Mac capture
`pipeline.py` (`cancel_recording()`) + toolbar/review-bar buttons in
`calendar_ui/window.py`; iOS `Voice/VoiceRecorder.swift` (`cancel()`,
on-device stop-word recognition), `Views/VoiceButton.swift` (`discard()`),
`SpeechPlayer.swift`; TTS `assistant/tts/speaker.py` (macOS `say`).
**How:** Audio never leaves the machine on the default engines; the phone
streams over Tailscale (`/voice/stream`, NDJSON). `test_offline.py` blocks
non-loopback sockets in the build. Discarding happens entirely client-side —
the audio is dropped before any upload, so nothing is transcribed, executed or
remembered. On the phone `cancel()` also clears the PCM buffer, which
`start(resume: true)` ("Add more") deliberately keeps.

### The edit-transcription round-trip (needs_edit)
**What:** When the vocabulary doubts words in a transcript, nothing executes —
the client shows an editor; the correction (or confirmation) is learned so the
gate fires less over time.
**Where:** gate in `assistant/engine/ingest/repair.py`; Mac dialog via
`pipeline.py` (`supports_edit: true`); iOS `EditTranscriptionSheet` in
`Views/VoiceButton.swift`; all `/voice*` routes forward `supports_edit`.
**How:** A changed word becomes a vocab alias + phonetic key immediately; an
unchanged resubmit counts toward whitelisting (2 confirmations); the resubmit
carries `edited_from` and bypasses the gate once.

### The confirm-create gate (confirm_create)
**What:** A question about creating something — "should I add yoga to my
calendar tomorrow?", "what if I booked town hall for the 3rd?" — is neither
executed nor silently dropped. The parse is finished and offered: the client
shows what it would create, Add creates it, No discards it.
**Where:** reader `is_interrogative_create` in `engine/segmentation/old_seg/segment.py:215`; rule
`_rule_interrogative_create_asks_first` in `engine/decompose_validate/object_rules.py:220`
(it lived in `validate.py` until that module was retired on 2026-09-08, `c3364df` —
the original is in `retired/decompose-validate-v1/`); short-circuit
`_confirm_proposal` / `_confirm_response` in `engine/__init__.py`; token store
and `POST /voice/confirm` in `api/server.py`; Mac `ask_create_confirm` in
`calendar_ui/window.py` (via `pipeline.py`, `supports_confirm: true`); iOS
"Add this?" alert in `Views/VoiceButton.swift`.
**How:** Gated on the client declaring `supports_confirm`, exactly like the
edit round-trip — an older client sees today's behaviour and nothing breaks.
The response carries `proposal`: ready-to-POST `/events` / `/todos` bodies,
the same trick one-tap revert uses, so accepting is a plain create through the
endpoints every client already speaks. Answering twice replays the first
answer, so a double-tapped Add creates once. A decline files the command
memory record as `rejected`, which feeds the review flows like any other bad
answer. Fires only when the question is the whole command; an interrogative
create never takes the fast track. Knob: `engine.confirm_create`.
*Ruling: Gil, 2026-09-07 (DEVQA Q9).*

### Background self-check & one-tap revert
**What:** Behind a fast answer, the deep track re-reasons: placeholder titles
renamed, missed asks added, suspected-extra rows reported (advisory by
default) — and when a destructive patch is applied, both surfaces show a
visible notice with one-tap revert.
**Where:** `_start_background_verify` in `assistant/engine/__init__.py`; poll
`GET /voice/verify/<token>`; Mac `_RevertBar` in `thinking_panel.py`; iOS
revert banner in `ThinkingView`.
**How:** Corrections carry ready-to-POST revert bodies captured before
deletion; revert is a plain re-create through the normal endpoints. Applied
changes echo to the Mac HUD as late trace steps.

### The review panel (thinking HUD) & iOS timeline
**What:** A floating always-on-top card (and the iOS sheet) showing every
step the assistant took, live, with timings — plus a searchable history of
every command ever run.
**Where:** `assistant/thinking_hud.py` + `calendar_ui/thinking_panel.py`;
trace source `assistant/trace.py` + `trace_bus.py`
(`~/.assistant_tools/trace_bus.jsonl`); iOS `ThinkingView` in
`Views/ThinkingView.swift` (moved out of `VocabularyView.swift` 2026-09-06).
**Launching it** (2026-09-14): `MACalendar HUD.app` → `launch_hud.sh` →
`python -m assistant.thinking_hud --show`, rebuilt by `scripts/build_hud_app.sh`.
Two traps live there. (1) The card is invisible until a command arrives, so
clicking the icon looked exactly like the app failing to start — `--show`
opens it, and `reopen()` re-fits so an idle card is not left at the last run's
height. (2) `osacompile` ad-hoc-signs the bundle and every PlistBuddy edit
afterwards BREAKS that seal; an unsealed bundle has no stable identity, so
macOS files it under the bare executable name "applet" in Settings ▸ Privacy ▸
Files and Folders, with no working toggle. Since the project lives under
~/Desktop, the HUD then dies with `realpath: .venv/bin/: Operation not
permitted` — which reads like a broken venv and is a missing TCC grant. The
build script re-signs last and VERIFIES, and fails the build if the seal or
the identifier is wrong. `scripts/hud_demo.py` streams a synthetic run to the
real bus (as `source: "test"`, which History filters) to watch the rail live.
**Live, from every surface** (2026-09-14, `003330b`) — and it was not, for the
bus's whole recorded history. `on_step` was hooked only when a CALLER supplied
a `trace_run`, which only the Mac GUI ever did; zero of 47 Swift files pass
one, so a phone command published nothing for its entire 4–40 seconds and then
appeared, already finished, in a single line. Not one `begin` line existed in
eight days of bus. The streaming machinery was complete, wired and dormant. The
engine now mints its own run id when the caller has none
(`engine/__init__.py:245-257`), so every command from every surface streams
`begin → step → step → result`. Two consequences to know: the durable
whole-run `trace` line is still written alongside, sharing ONE run id, because
`read_history` returns only whole-run lines and the first version of this
change silently emptied History (the HUD dedups on the id); and
`trace_bus.MAX_ENTRIES` moved 200 → 2000, since the budget counts LINES and a
streamed run occupies about ten where it used to occupy one.
**How:** The HUD talks to no process — it tails the bus file. Renders by
brain version: `CHAINS[BRAIN_VERSION]` scaffold rail with per-step ⓘ
(copy from `trace.STAGE_INFO`, mirrored in Swift, drift-pinned by
`test_stage_info_parity`). Red is reserved for fatal; review reads amber.
The rail shows every slot *while the run is in flight* — the unlit ones are
what is still ahead — and on finish folds each run of two or more unreached
slots into one "N steps not needed" line that clicks back open, so a
fast-lane answer no longer spends half a fixed-height card drawing the chain
it did not walk. An unreached slot's mark is one glyph (`SKIP_MARK`): it
shares a 14×14 box with the ✓ and the spinner, and the word that used to go
there rendered as "pp".
**The two non-object outcomes** — an item that leaves the object stage without
an object — are rendered APART, because they are not the same event: a chip
beside the step's title reads "not calendar work" (muted: the engine read the
words correctly and there is no calendar work in them) or "reached me damaged"
(amber: it *is* calendar work and something upstream handed the stage a broken
item). Engine side, `fastrule/objects.NOT_AN_ASK` / `BAD_ITEM` on the trace
step's `data["outcome"]`; panel side, `_StepRow._OUTCOMES`; tied together by
`test_panel_agreement`. Red stays reserved for the error stage.
*iOS has no equivalent badge yet — the Mac is ahead here.*
**Looking at it:** `python -m scripts.shoot_panel "<command>" out.png [light]`
renders the real panel against a real engine trace (scratch stores, no Ollama
needed, `source: "test"`), writes the card unrolled to its full content
height, and prints content-vs-card **and any step row wider than the card**.
Three panel defects shipped green because every test read a label's text back
instead of looking at the pixels.
**Ergonomics:** menu-bar tray icon (show/hide/quit), sticky hide, corner
parking, drag-to-reposition persisted across launches, idle translucency
that solidifies on hover, minimise-to-header with live step count, joins
every macOS Space including over full-screen apps, right-click menu; result
cards carry click-to-fix word chips, uncertain-word candidate chips, Retry
now, 👍/👎, and the Revert bar.

### The LLM console

**What:** the panel's THIRD view — an "LLM" button in the header beside
"History", both flipping to "Back" — showing every model call
the system made, newest last, each row saying **where in the system it came
from**, how long it took and whether it was schema-constrained — and expanding
to the actual system prompt, user prompt and response. Search over caller,
prompt and response; two filters only, "Slow (>5s)" and "Failed"; a Clear
button. Shipped 2026-09-13/14 (`9db46f6`, `b7687ea`).
**Where:** the stream is `assistant/llm_bus.py`
(`~/.assistant_tools/llm_calls.jsonl`, override `MACALENDAR_LLM_BUS`); the view
is `_LLMRow` + `toggle_llm`/`_load_llm` in `calendar_ui/thinking_panel.py:1131`
and `:1686-1730`; the HUD process drains it with a second offset in
`thinking_hud.py:545-580`; tests `tests/unit/test_llm_console.py`. Adding it
also collapsed the view switching into one place: `_set_view` (`:1643`) is now
THE truth table for which view is visible — with two views the old pair of
recomputed booleans was a duplicate, with three it is where a drift would
have shown a card with two views at once.
**How — and why it is a SECOND file, not the trace bus.** Three properties of
the HUD's own code make sharing impossible: `apply_entry` keeps a single
`_current_run` and would tear the timeline when a call interleaves with a run;
`trace_bus.read_since` closes over a module-global `BUS_PATH` with no path
parameter and one scalar offset, so two streams need two readers; and the trim
budget counts LINES, so a chatty second stream would evict finished runs from
the durable record the History view reads back. So: its own file, its own
offset, its own budget (`MAX_ENTRIES = 400`), the same shape.
`caller_label()` (`llm_bus.py:190-214`) walks the stack for the OUTERMOST
interesting frame rather than the innermost — the immediate caller of a
transport is always the transport wrapper, and what a reader wants is the stage
(`llmjudge.extract_asks`, `_recheck_not_found`, `objects._parse_item`), so
frames inside `intent/parser.py`, `engine/llm.py` and the bus itself are
skipped.
**It holds real transcripts**, verbatim prompts and responses included, so it
lives beside the other personal stores in `~/.assistant_tools/`, honours its
env override, and drops `source: "test"` traffic entirely — the same rule the
NLU log and the History view already apply. Prompts are clipped at 4,000
characters with the original length kept, so the row can say "12 KB, showing
the first 4" instead of silently lying about the prompt.
**Why it exists:** "Slow" is the filter that matters. A `_recheck_not_found`
call spending ~40 s was invisible in every latency board because that path
records no `llm_ms` (`assistant/intent/parser.py:515-518` says so itself); the
console shows it regardless of what the boards count.

### Personal vocabulary
**What:** The user's names/places/phrases; transcripts auto-correct through it
before the brain sees them.
**Where:** `assistant/stt/vocab.py`; store `~/.assistant_tools/vocab.json`;
editors: Mac panel tap-a-word + QuickFix, iOS `VocabularyView` /
`VocabImportView` / onboarding; API `/vocab*`.
**How:** Aliases + phonetic keys; learns from tap-a-word, the needs_edit
round-trip, and bulk import mining (contacts/messages candidates); iOS runs a
first-launch onboarding interview once the Mac is reachable. Doubt whitelist
counters live beside the store, never inside it.

### Command memory & feedback
**What:** Every command, what it did, and the user's verdict — explicit 👍/👎
or implicit (editing/deleting a voice-created row within 24h files as
corrected/rejected; a reformulated retry is mined as a correction pair).
**Where:** `assistant/intent/memory.py`; store
`~/.assistant_tools/nlu_memory.db`; hooks inside `db.update_/delete_*`;
review UIs: iOS `AssistantReviewView`, Mac panel feedback row.
**How:** Recorded per item (per-item attribution). Few-shot injection exists
but ships k=0 — measured to hurt the engine; the record feeds calibration
(TASKS row 57) and future fast-rule mining instead.

### Tag suggestion history
covered under **Tag discovery** above — the review/reverse/hide record.

### Calendar import & connected calendars
**What:** Import events from an `.ics` file or scan macOS Calendar.app;
subscribe read-only to any ICS/webcal link (Gmail, iCloud, Outlook.com…);
optional Outlook **two-way** sync via device-code OAuth, with Sync Now and a
15-minute background sync.
**Where:** Mac toolbar Import + Connected Calendars dialogs
(`calendar_ui/window.py`); `assistant/calendar_sync/outlook_sync.py`,
`actions/calendar/graph_client.py`; `calendar_sources` table.
**How:** Synced rows are marked by source; ICS rows render read-only with a
banner; Outlook dirty-row preservation protects local edits while two-way is
off.

### Workout & training scheduling
**What:** Workout templates, live sessions with set logging, stats, and an
observance-aware run/gym planner (fast days, motzei constraints, frequency
rules).
**Where:** `assistant/actions/workout_routine.py`, `schedule_workout.py`; db
`workout_*` tables; iOS `Features/Workout/*` (views + `WorkoutStore.swift`).
**How:** The planner reads the same observance windows as the calendar;
voice-triggered via `generate_workout_routine` / `schedule_workout` actions.

### Timer (work tracking)
**What:** Multi-project timers with earnings calculation and sub-sessions.
**Where:** db `timers`/`timer_sessions`; API `/timers*`, `/timer_sessions*`;
Mac Timer tab; iOS `Features/Timer/TimerView.swift`.
**How:** Local-only SQLite; sessions editable after the fact. **The live
counter is clock-driven on both surfaces** and must agree: the Mac ticks from
the DB every second, the phone from `running.start_epoch` (the server serves
each session's instants as numbers beside the ISO strings) plus a 1 s tick,
reloading every 3 s while anything runs. The numbers exist because the strings
were not enough — `isoformat()` writes six fractional digits and iOS's
`ISO8601DateFormatter` parses three, so the phone parsed nil for every running
session, showed 00:00 beside a Mac that was counting up, and subtracted the
running session's length from the total. `TimerFormat.isoDate` now truncates
the fraction and tolerates a naive stamp (the Mac's "Log past time…" writes
one), so old servers still work.

### Counters
**What:** Tap-counters with press history and payout tracking.
**Where:** db `counters`, `counter_presses`, `counter_payouts`; API
`/counters*`.
**How:** Same local-first pattern as timers.

### Jude — the Judaic study assistant
**What:** Ask about Torah, Talmud, halacha, midrash and machshava; a cited
answer streamed from ~289,000 Sefaria passages, every source linking back to
Sefaria. Three modes (Q&A, Study, Sources-only), halachic topic routing with
primary/secondary source grouping, a pipeline trace, clarification prompts and
topic-pivot confirmation.
**Where:** Jude itself is a **separate repository**
(github.com/GilCaplan/JudeTheJudaicChatBot) — deliberately not vendored and
never edited by us: it carries a ~1.2 GB corpus and a ~2 GB index and is worked
on separately. Everything on this side lives in `assistant/jude/`: how the
checkout is found and started (`integration.py`), the `/jude/*` blueprint
(`routes.py`), the standalone Mac app (`app.py` + `ui/`, 📖 in the calendar
toolbar, `Jude.app` built by `build_app.sh`), and the map
(`ARCHITECTURE.md`, which also carries the wire contract both clients build
against). The iOS tab is `MACalendar-iOS/MACalendar-iOS/Features/Jude/` (Settings, off
by default). Config: `jude:` in config.yaml.
**How:** It is the first **integration** — an external app this assistant
hosts, gates and proxies without absorbing it. The generic half is
`assistant/integrations/` (`CONVENTION.md` is how to add another).

Three rules make it part of this system rather than a second system beside it.
**Its model calls go through our gate** — Jude makes five per question plus an
embedding per retrieval, and synthesis alone is 30-90 seconds, so unarbitrated
it was a fifth door onto the one ollama this machine has.
`integrations/ollama_gate.py` takes `model_protocol.hold()` around every
generating call and Jude is pointed at it with `OLLAMA_HOST`; because Jude also
hardcodes ollama's address for its ChromaDB embedding function, a
`sitecustomize` shim on the child's `PYTHONPATH` closes that hole without
editing Jude. Priority is `background`, so Jude yields the model to voice
commands rather than racing them. **Nothing reaches the internet** — Jude's own
default is a cloud cascade (Gemini → LLMod → ollama), so every role is pinned
to local ollama on `ollama.model` (one resident model, not two) and the cloud
keys are blanked, unless `jude.allow_cloud` is explicitly set. **It is reached
through this API** — both clients POST to `/jude/chat` on 8080 with the usual
key, and the server translates Jude's SSE into the NDJSON every client already
renders for `/voice/stream`, so Jude's own port never leaves the machine and no
client learns a second protocol.

Missing checkout, switched off, or not started yet are all normal states that
produce a sentence naming what to do — `GET /jude/status` never errors. The
brain is untouched: these routes are plumbing, and Jude cannot be asked to
create an event.

**Prerequisite:** Jude's retriever hardcodes `nomic-embed-text`, so that model
must be pulled (`ollama pull nomic-embed-text`) even though every generating
role is pinned to `ollama.model`.

### Coursework
**What:** Courses + assignments tracking (the university tab).
**Where:** db `courses`/`assignments`; Mac Coursework tab; iOS
`Features/Coursework/CourseworkView.swift`, `CourseStore.swift`.
**How:** Toggleable tab (settings); feeds tags ("Coursework").

### iOS app & offline queues
**What:** The full iPhone client — calendar, tasks, voice, review, vocabulary,
workout, timer — working offline and syncing when the Mac returns.
**Where:** `MACalendar-iOS/`; queues and caches in `LocalStore.swift`; the
circuit breaker and `bootstrap()` in `API/APIClient.swift`; polling via
`GET /changes`; the protocol written down in
`DOCUMENTATION/SYNC_PROTOCOL.md`.
**How:** Three queues (CRUD ops with temp-id repointing, queued voice
recordings, pending LLM commands) plus a local event/todo/tag/**holiday**
cache so views work offline; lost-stream recovery (checks whether the Mac
finished the command anyway); a background assertion keeps a voice command
alive when the app is backgrounded; burst-refresh after actions;
vertical-swipe month change; guests via the system Contacts picker with
per-guest Message/WhatsApp actions; reaches the Mac over Tailscale only.
**Every write survives the Mac being away.** Queueing used to be decided per
tab, and most tabs decided wrong: Coursework, Timer, Counters, Categories,
Vocabulary and Teach wrote straight to the Mac and swallowed the failure, so a
course deleted offline came back on the next sync and an assignment added
offline was gone by it. One helper decides now — `APIClient.mutate` performs the
write or enqueues it — and `tests/unit/test_ios_offline.py` fails the build for
a mutating call that goes around it without a declared reason. The writes whose
replay depends on *when* it happens carry the instant they happened
(`/timers/<id>/start` and `/stop`, `/counters/<id>/press` and `/cashout`), so a
timer started on the train is not billed from the moment the Mac woke up.

**Offline is instant, not eventually.** Reads always fell back to the cache —
but only after each request had spent its full 8 s timeout, and a cold start
ran several of those one after another, so the app opened on an empty calendar
for tens of seconds. Three changes: an **offline circuit breaker** (after one
failure, requests throw `.offline` immediately without touching the network;
only `/health` and `/changes` still probe, on a 3 s leash, backing off
2 → 20 s; the voice uploads check it too, so a recording is queued at once
instead of waiting out a 120 s timeout); **one bootstrap request**
(`GET /sync/bootstrap` — three months of events, tasks, tags, tag rules,
categories and holidays in a single round trip); and **painting the cache
before awaiting the network** on every month navigation.

### Heartbeats & the health CLI
**What:** `assistant doctor` — is every layer wired: LLM, storage, engine,
panel, macOS app, external devices.
**Where:** `assistant/cli.py`; `assistant/heartbeat.py`
(`~/.assistant_tools/heartbeats/`); devices POST `/heartbeat`.
**How:** See `DOCUMENTATION/CLI.md`. The engine layer is version-tied to
`BRAIN_VERSION`; a redesign that forgets the doctor fails the build.


## Purely backend

### Search & jump-to-date

**What:** the Mac toolbar has a search box: type words to find events (title/
location/description) and tasks (title/notes), pick a result to jump to its
date or the Tasks tab; type a date ("2026-10-14", "14/10") to jump straight
there. iOS gets a magnifying-glass sheet over the offline cache, so it works
away from the Mac.
**Where:** Mac `calendar_ui/window.py` (`_on_search`, `_parse_jump_date`);
server `GET /search` (`db.search_events/search_todos`); iOS
`Views/SearchView.swift`.
**How:** substring LIKE queries, events soonest-first, open tasks first; the
Mac GUI queries its local db directly (same path as rendering), iOS filters
`LocalStore` — no network needed on either.

### Share event as .ics

**What:** one event exported as a standard calendar file — "Share .ics" in
the Mac event dialog (saves via file dialog), share-sheet on iOS.
**Where:** `assistant/ics_export.py` (pure), `GET /events/<id>.ics`
(`server.py`), Mac `event_dialog.py`, iOS `EventDetailView.swift`.
**How:** one row → one VEVENT deliberately: series are materialized rows
here, so an RRULE would double-book on re-import and can't express
observance skips. Floating local times (the store has no timezone), RFC 5545
escaping + 75-octet folding. Import's symmetric half.

### Small conveniences

**What:** duplicate event (dialog button → one-off copy, undoable); ISO week
numbers in the month grid (`ui.show_week_numbers`); Timer stats → CSV export
mirroring exactly what the panel shows.
**Where:** `event_dialog.py` + `window.py` (duplicate), `month_view.py`
(week numbers — the row's Monday names the ISO week, since a Sunday-first
row straddles two), `timer_view.py` (`_on_export_csv`).
**How:** duplicate strips series identity (a copied instance is a one-off,
same boundary as undo-restore); CSV derives rows from the panel's own
aggregation helper so file and tiles can't disagree.

### "How to Talk to Me" tips

**What:** five short tips on effective voice phrasing (Settings → Assistant
→ "How to Talk to Me…"), deliberately kept to five (Gil, 2026-09-16: don't
overload the user with content). Mac only — not built for iOS this pass.
**Where:** `assistant/tips.py` (content), `calendar_ui/tips_dialog.py`
(the dialog), wired in from `settings_dialog.py`'s Assistant section
alongside Vocabulary/Review/Categories.
**How:** each tip is a factual claim about pipeline behavior, verified LIVE
against `assistant.engine.run_transcript` when written — one candidate tip
turned out false when checked and was dropped before shipping. Tied to
`assistant.trace.BRAIN_VERSION` via `TIPS_BRAIN_VERSION`: `tests/unit/
test_tips_current.py` fails the build the moment the engine version moves
past what the tips were verified against, the same "downstream of the
pipeline" contract `test_panel_agreement.py` holds the thinking panel to —
so a future engine change forces a re-verification rather than silently
shipping stale claims.

### Personal lexicon

**What:** the engine's word lists, extendable by the person who speaks them
(Gil, 2026-09-18): *"in the settings we should have a section where these are
all listed out and linked to what's in the code and can be dynamically updated
... so that it can be fine-tuned to how he speaks"*. Add "squeeze" to the
shorten-verbs and `"squeeze the event at 2pm to be 15 minutes"` starts working.

**Why it exists:** `"Can you shorten the event at 2pm walk Jada to be 15
minutes"` silently did nothing, because one hand-typed verb list had never
learned the word "shorten" while another had known it for weeks. There are
**239 pattern constants** under `intent/` and `engine/`; every one is a place
the engine's idea of English can fall behind its user.

**Where:** `assistant/intent/lexicon.py` (`LEXICONS` declares each list and the
module constant it mirrors; `LexiconStore` holds the person's additions in
`~/.assistant_tools/lexicon.json`, `MACALENDAR_LEXICON`). Read through
`rule_parser._extend_verbs()`, consulted by both the router and the
extend/shorten slot logic. API: `GET /lexicon`, `POST /lexicon/<name>`,
`DELETE /lexicon/<name>/<word>`.

**How it stays safe:**

- **Additive only.** `effective()` is `built_in | user`, always. No edit can
  take a word away, so tuning your phrasing can never break a command that
  used to work. A built-in has no removal path at all.
- **A declaration points at real code** — `built_in()` imports the module and
  reads the constant, so the settings screen shows fact rather than a second
  copy. A second copy is the defect this feature exists to prevent, and
  `test_lexicon.py` fails if a declaration names an attribute that no longer
  exists.
- **A corrupt store degrades to the built-ins** rather than raising inside a
  voice command; `~/.assistant_tools` is hand-editable by design.

**Still to build:** the settings screens themselves (Mac and iOS) — the API and
the engine read-through are done and tested, the UI is not. Three lists are
declared so far (`extend_verbs`, `title_strip_verbs`, `calendar_words`);
declaring a fourth is one line, and both the API and the screen pick it up with
no further wiring.

### Foldable settings sections

**What:** every section on both Settings screens folds away, and stays folded
until you open it again (Gil, 2026-09-17: *"perhaps add a minimize on each
section starting to be a lot of things there"*). Six sections on the Mac and
seven on the phone had grown past one screenful, so the ones nobody visits twice
were pushing Server and Notifications off the screen.
**Where:** Mac `calendar_ui/settings_dialog.py` — the existing `section()`
helper now returns a folding box, so all six got it in one change and a seventh
would too. iOS `Views/SettingsView.swift` — `CollapsibleSection`, which WRAPS
`GroupBox` rather than replacing it, so every section keeps exactly the look it
had.
**How:** the fold state is per-machine UI chrome and is stored as such — Mac
`QSettings` (redirected by `MACALENDAR_UI_STATE`, which `conftest.py` scratches),
iOS `@AppStorage` under `settingsSection.<key>`. Deliberately NOT in
`config.yaml`: the phone reads that file, and which boxes you keep folded on the
Mac is not something the phone should inherit.

Three things this cost, each worth keeping written down:

- **Not `QGroupBox.setCheckable`.** Qt's built-in way to make a group foldable
  puts a CHECKBOX beside the title, which reads as "switch this whole section
  off" — a different and alarming promise. An arrow that turns says only what it
  does.
- **A module-level `QSettings` is destroyed with the `QApplication` that
  outlived it**, and every later use raises `RuntimeError: wrapped C/C++ object
  has been deleted`. Invisible in a single test; it broke the three that build a
  real dialog after another test tore an app down. `_ui_state()` builds one per
  call for that reason.
- **Its default writes the user's REAL macOS preferences**, so the suite was
  folding boxes in the app Gil had open until the env override went in — the
  same class of accident as the four `~/.assistant_tools` stores.

`tests/unit/test_settings_collapse.py` drives it with `QTest.mouseClick` on the
header, per the repo rule that a UI test which never sends a mouse event tests
nothing: the body hides, the arrow turns, the neighbouring section does not
move, and a second dialog opens with the fold remembered.

### The day panel

**What:** One summary of today — the day's events in the order they happen,
then today's tasks — delivered once, at `notifications.digest_time` (07:00
local by default). **On or off, and that is the whole control** (Gil,
2026-09-11: *"it's on or off and it shows in a nice manner the event calendar
and tasks for today"*). It replaced a stream of "starting soon" banners.

**Where:** `assistant/notify.py` — `digest_verdict` (when, and whether a
Shabbat/yom tov window holds it) and `build_digest` (what it says);
`GET /digest[?date=]` serves it; the Mac fires it from `notifier.py`
(`DIGEST_KEY`, a negative sentinel in `reminder_log`, is the once-a-day
guard — the same UNIQUE row that dedupes reminders); the switch is
`notifications.daily_digest`, writable through the existing `PATCH /config`.

**How, and why it matters:** the SERVER owns the wording, not just the rows.
`build_digest` returns the finished `title` and `body`, so the Mac banner and
the phone's notification say the same thing — two clients formatting their own
drift the moment one learns about all-day events and the other does not. A
dated task belongs to its due date; an undated one is *outstanding*, which is
a today concept, so it appears on today's panel and no other day's. Unlike a
pre-event reminder, a late panel is NOT caught up: a reminder that arrives
late is still about something that has not happened, but a summary of the day
arriving at 4pm is the noise this replaced.

**On the phone** (2026-09-17): `ReminderScheduler` lodges ONE notification per
day, straight from the Mac's finished wording, and Settings › Notifications is
the one switch — shared with the Mac, so turning it off here stops its banner
too. Offline the switch goes to the write queue like any other change, and the
Mac's value is adopted on load only while nothing of this phone's is still
queued.

iOS notifications are **scheduled, not pushed**, and that is the one thing
this feature's shape turns on. There is no server that can reach the phone at
07:00 — iOS fires from a request lodged earlier — so the phone must already
hold tomorrow's panel tonight. `GET /digest/upcoming?days=7` returns the week
in one round trip; the phone caches it (`mc_digests.json`) and re-lodges the
lot on cold start, on foreground and whenever the `/changes` token moves. The
payoff is that a panel arrives on time with the Mac asleep, the tailnet down
and the app never opened — which is the whole reason the phone is the ringer.
Days held for Shabbat or yom tov come back with `fires_at: null` and the
reason, and the phone schedules nothing for them rather than re-deriving an
observance verdict it could not compute.

**The permission ask is part of the feature, not an afterthought.** The panel
ships ON, and until 2026-09-17 nothing on this path ever asked for
authorization: a clean install fetched the week, called `add` seven times and
iOS rejected all seven in silence. It now asks at the first moment it has a
real panel to lodge. `DayPanelUITests` drives a clean install and fails if the
ask stops happening — it is the test that found this.

### Pre-event notifications (dormant)

**Status:** `notifications.pre_event` ships **false** — the day panel replaced
these. On the MAC nothing is deleted: `reminder_minutes` is a frozen engine
contract, "with a 15 minute reminder" still parses and stores, and turning the
flag on restores the whole path below (pinned by `test_digest.py`). **On the
phone this half is retired, not dormant** (2026-09-17): `ReminderScheduler`
schedules panels now, so flipping the flag would bring the banners back on the
Mac alone. The scheduler still SWEEPS the old `evt-*` requests on every
reconcile, because an app updating from an older build has up to 55 of them
lodged with iOS that no code owns any more.

**What:** "remind me before it starts." The server computes each event's
`notify_at` (lead resolution: event override → category lead **or mute — a
category can opt out entirely** → global default, shipped opt-in) and embeds
it in every event payload; the phone schedules local notifications from its
offline cache (fires with the app closed and the Mac asleep); the Mac shows
best-effort banners (+ optional spoken heads-up) while the calendar stack
runs. Quiet windows: evaluated on the FIRE time — an event inside
Shabbat/yom tov gets no reminder (reason in the payload), a motzei lead is
clamped past havdala, fasts don't suppress, fail-open like the series skip.
Additive on top of the banner: an **"Up Next" Live Activity** — a persistent
lock-screen card (and Dynamic Island) showing today's remaining agenda, each
row's title/time/category colour, with the running event (or failing that
the soonest one) picked out by a coloured glow and the one after it by a
lighter version of the same — no countdown number, current always outranking
next. **This shape is LOCKED** (Gil, 2026-09-18; DEVQA Q23): the agenda was
chosen over a countdown with both built and rendered side by side, so it is
not up for redesign and a ticking number must not come back unless he asks
for one. Bug fixes inside it are ordinary work. **Clearing it keeps it cleared** (Gil, 2026-09-17: *"if i clear it, it
shouldn't reappear"*): dismissing a Live Activity records nothing, so the next
sync used to start a fresh card within seconds of the swipe. A dismissal now
writes `agendaCardSuppressedUntil` and the card returns at **06:00** the next
morning — best-effort via a `BGAppRefreshTask` (iOS decides the actual minute;
no APNs in a local-only app), and for certain on the first foreground after 6.
It has **its own Settings toggle**, no longer riding on the reminders switch,
and switching it back on clears a dismissal so you can have the card back
today. Its rows are **Liquid Glass** on iOS 26 (`.glassEffect` tinted with the
event's category colour) with a hand-built material + specular hairline below
26. Also additive: a **"Show today's agenda now" button** in the phone's
Reminders settings — pops one local notification, on demand, with the
WHOLE day's events (not just what's left, and not gated on the reminders
toggle or a horizon), phrased the same way the Mac's own "Brief Me" reads it
aloud ("You have 3 events today: X at 9, Y at noon, and Z at 5").
**Where:** policy `assistant/notify.py`; store `events.reminder_minutes` +
`reminder_log` (`db.py`); Mac thread `assistant/notifier.py` (osascript);
settings `settings_dialog.py` + iOS `SettingsView`; phone
`ReminderScheduler.swift` + `NotificationRouter` (tap deep-links to the
event); per-event picker **on the iPhone only** — `EventDetailView.swift:124`
(Inherit / None / N-minutes, `-1` meaning "no stored override") plus the plain
reading of `notify_suppressed_reason` at `:51-64`; config `notifications:`
section (PATCH /config). "Show today's agenda now": `SettingsView`'s
Reminders section, `LiveActivityManager.todaysAgendaSummary(now:events:)`
(a pure function over `LocalStore`'s cache, no server round-trip) fired
through the existing `APIClient.notify(title:body:)` immediate-local-
notification helper. Live Activity: app-side
`LiveActivityManager.swift`, shared contract
`MACalendar-iOS/MACalendar-iOS/Shared/UpNextActivityAttributes.swift` (compiled into both
targets), UI in the new `MACalendarWidgets` app-extension target
(`UpNextLiveActivity.swift`, bundle id `com.macalendar.app.widgets`,
deployment target 16.2, embedded via "Embed Foundation Extensions");
`NSSupportsLiveActivities` in the app's `Info.plist`.
**How:** no new sync surface — the event payload is the contract; the phone
reconciles ≤55 `UNCalendarNotificationTrigger`s (headroom under the 64 cap
for workout rest timers); `reminder_log` dedupes across `--reload`
restarts; late fires obey `catch_up_minutes`. The Live Activity needs no
push and never gets one: nothing in the card is system-animated any more —
it is a static snapshot the app pushes when the *agenda* changes, which it
does from the paths where it already wakes
(`ReminderScheduler.reconcile()`, ContentView's foreground handler, its
`/changes` branch and its 30 s tick), all funnelled through one debounced
`LiveActivityManager.sync()`. Cards carry a `staleDate` at exactly the
moment they stop being true (the running event ends, or nothing was
running and the next one starts), so a transition missed while the phone is
locked is dimmed by iOS rather than shown as a lie. Starts only within the
8 h ActivityKit cap, and respects the device-local reminders toggle.
**The Mac has no per-event picker** (corrected 2026-09-14 — this entry claimed
"both edit surfaces" and that was never true). `calendar_ui/event_dialog.py:147-238`
lays out Date, Time, Attendees, Location, Notes, Repeat, Until, Colour and
nothing else; `grep -ci remind` over that file returns 0. Everything under it
is already there — the column (`db.py:128`), the PATCH allow-set (`db.py:1182`)
— so it is one form row, not a feature. Worth knowing before building it:
reminders ship **opt-in** (`notifications.default_lead_minutes: 0`,
`config.example.yaml:141` / `NotificationsConfig` `config.py:218`), so until an
event or a category asks for a lead, nothing fires anywhere — a per-event
picker is exactly how an event would ask. (The 2026-09-14 audit called this
path "dormant behind `notifications.pre_event=false`"; there is no such
setting — `grep -rn pre_event` over the repo returns nothing. The opt-in
default is the real mechanism.)
**Voice phrase → lead time (phase 3) SHIPPED**, in two steps: the inline form
on 2026-09-06 (`1172811` — "book gym tomorrow at 6:30 and give me a heads-up
half an hour before" attaches `reminder_minutes=30`), then the reader moved
into `assistant/intent/lead_time.py` on 2026-09-07 (`816cea7`, `7ff29b8`) so
both tracks share one copy: `decompose.py:151-163` strips the clause per item
on the deep track, `rule_parser.py:471-472` strips it during FastRule
normalization, and `fastrule/objects.py:472-478` puts the slot on the intent.
Stripping happens BEFORE the until/through rule deliberately — a bare surviving
"before" reads as a recurrence-end marker.
**Two halves of phase 3 are still missing** (verified 2026-09-14): `_apply_slots`
applies `reminder_minutes` only when `item.action == "create_event"`
(`objects.py:476`), so there is no voice path for *changing* a reminder on an
event that already exists; and nothing announces a suppressed reminder in the
spoken reply — `notify.py:145-154` computes `notify_suppressed_reason` and the
iPhone renders it, but no reply string anywhere mentions it. Plan:
`NOTIFICATIONS_PLAN.md`.

### The home-screen widget (iOS)

**What:** a small or medium home-screen widget — "UP NEXT" (or "NOW", once the
event is running) in that event's category colour, its title and clock time,
up to three rows on the medium size, and "N more today" alongside.
Unlike the lock-screen Live Activity next door, **the pointer advances on its
own**: the widget rolls to the next event at exactly its start time with the
app not running.
**Where:** `MACalendar-iOS/MACalendarWidgets/UpNextHomeWidget.swift` (342
lines — the widget, its timeline provider and both views), registered beside
the Live Activity in `MACalendarWidgetsBundle.swift`; the app↔extension
contract is `MACalendar-iOS/MACalendar-iOS/Shared/WidgetSnapshot.swift`
(compiled into BOTH targets, Foundation-only, like
`UpNextActivityAttributes.swift`); the app side is
`LocalStore.refreshWidgetSnapshot()` (`LocalStore.swift:208-231`) and
`LocalStore.widgetItems` (`:242-267`). Shipped `902e8a4`.
**How:** the two widgets are fed two opposite ways on purpose. A Live Activity
is *pushed* its content and can only change while the app is awake; a widget
timeline is handed to WidgetKit **once**, with future-dated entries, and the
system swaps them in with nothing of ours running. `changePoints()`
(`WidgetSnapshot.swift:135-148`) is that trick: every start, every end still
ahead, plus the next midnight, capped at 30 entries.
The extension runs in its own process and cannot see the app's Documents, so
the channel is an **App Group** (`group.com.macalendar.app`, declared in both
`.entitlements` files): the app mirrors a small JSON snapshot into the shared
container on every `LiveActivityManager.sync()` — and only when the content
actually moved, because WidgetKit budgets timeline reloads and spending them
redrawing an unchanged widget is how a widget ends up refusing to update at the
moment it matters. The extension owns no formatter, no locale knowledge and no
colour policy: `timeLabel` and `colorHex` arrive already resolved. Snapshot
caps: 12 items, `staleAfter` 36 h (older than that says "Not synced / Open
MACalendar" rather than pretending the day is empty).
**The honest caveat — it may never have drawn anything real.** App Groups need
a provisioning profile from the paid developer program, and
`NOTIFICATIONS_PLAN.md:141-147` records that only `com.macalendar.app` has a
profile on this Mac while `com.macalendar.app.widgets` has none, and that a
headless `xcodebuild` cannot mint one ("No Accounts"). **This is a doc
assertion nobody has re-tested** — the 2026-09-14 audit could not verify it
either, and no commit after `902e8a4` records a device check. Every failure
path is handled (`WidgetBridge.containerURL` is nil, the app's mirror is a
silent no-op, the widget draws its placeholder), so nothing crashes; but
`902e8a4`'s own message says that if App Groups turn out to be unavailable the
widget *"placeholders forever and the honest fix is dropping it."* One Run from
Xcode.app with the phone reachable settles it.

### The engine (engine-v3) — the brain
**What:** Speech/text → events, tasks, answers. A fast track (confident rule
parse commits instantly, the deep track verifies behind it) and a deep chain of
six boxes, one stage per folder:

    X0 -> ingest -X1-> segmentation -X2-> decompose_validate
       -X3-> fastrule -X4-> llmjudge -> commit(+label)

**Where:** `assistant/engine/` (one FOLDER per stage — its code, its datasets,
its experiments and its own `ARCHITECTURE.md`; `state.py` holds the frozen
contracts and `state.STAGES` is the authoritative stage list); entered only via
`assistant.api` (`/voice*` routes).
**The chain was re-cut 2026-09-08** (`a962a9f`, Gil's drawing): decompose and
validate became one box, generate became `fastrule` (the stage IS
object-making), crosscheck became `llmjudge`, and label moved INSIDE commit so
a row can never be written and left unlabelled. `BRAIN_VERSION` is `engine-v3`
(`assistant/trace.py:22`) and `CHAINS["engine-v3"]` is what the review panel
draws. This entry described the superseded 7-step chain until 2026-09-14 — the
same drift `assistant/engine/__init__.py:23-26` admits to in its own docstring.
**How:** `DOCUMENTATION/ENGINE.md` is the canonical stage-contract reference
and `assistant/engine/ARCHITECTURE.md` is the map. Deterministic-first
everywhere — a stage may call the model only when its deterministic reading
found nothing; every LLM call schema-constrained and grounded on the raw
transcript. Per-stage tests (`test_engine_<stage>.py`), per-stage boards under
each folder, and `scripts/engine_stage_check.py --stage <name>` for one stage
against the real local LLM.
**Two things are wired and deliberately INERT**, so their presence is not
working behaviour: LLMSeg is off (`MACALENDAR_LLMSEG`), and the judge's
loop-back is gated on a rewrite that is still a stub — re-entering a
DETERMINISTIC segmenter with unchanged text cannot produce a new answer, which
is why the gate exists rather than a plain re-run.
**Step 0 — is this a command at all?** `repair.is_ignorable()` runs at the
engine's front door, before the run lock and before the config is read, so
silence that transcribed to nothing and a recording that is only the word
which ended it ("execute", "that's it", "set events") cost microseconds
instead of queueing behind whatever is running. `run()` keeps the same check
for the custom stop phrases the front door has not read yet.
**Notable behaviours (each a named, tested rule):** ingest coalescing of
queued commands; stop-word peeling (every trailing keyword, not just the
last); trivial/false-start filtering (ignored AND not remembered); anaphora ("the one I just made" → context memory);
"another one at 7" title carry-over; not-found honesty on updates/deletes
with one LLM second opinion — never a guess; am/pm correction; past-date
bump; move-time fill ("from 9:30 to 9"); cadence rounding announced, never
silent; question-creates-nothing and remove-echo guards; junk/placeholder
event drop; quantity extraction ("5 apples" → one task ×5); shared-verb list
splitting ("buy chicken and rice"); same-activity multi-time split ("walk
the dog at 9 and 2:30" → two events); prompt-injection defense (refuses
"ignore previous instructions" transcripts); max-duration cap (a `create_event`
the engine itself builds longer than `engine.max_event_hours`, 4 by default,
is clipped from the end — never a manual GUI edit); quiet-hours flag (a start
or end time inside `engine.quiet_hours_start`/`_end`, 23:00–06:00 by default,
is flagged in the reply rather than changed, spoken or defaulted alike).

### The one-shot LLM engine — a measuring instrument

**What:** a PARALLEL brain that replaces the whole chain with a single
schema-constrained model call — transcript in, objects out. `MACALENDAR_ONESHOT=1`
routes every command to it; off by default, and the chain is untouched either
way. Gil, 2026-09-13: *"build a parallel engine which is just an LLM trying to
one shot"*. Shipped `9481853`.
**Where:** `assistant/engine/LLM_one_shot/__init__.py` (245 lines — `SCHEMA`,
`build_objects`, `_to_intents`, and a stage-shaped `run(state, cfg)`); the
branch point is `assistant/engine/__init__.py:317-333`; it is listed as a
component but explicitly NOT a stage in `assistant/cli.py:236-237`, and
`tests/unit/test_cli.py:77` pins that exception; the sweep harness selects it
with `CHECKPOINT_ENV` at `scripts/checkpoint_sweep.py:78`.
**Why it exists:** to answer a question the chain cannot answer from inside
itself — **does the six-box deep track earn its complexity?** It is deliberately
the dumbest honest baseline: the raw transcript, today's date, and a schema. No
vocabulary repair, no segmentation, no rules, no validation, no judge, no
retry. Anything it gets right it gets right from the model alone. It is not a
proposal to replace the engine.
**How:** Ollama is format-constrained by `SCHEMA`, so the model *cannot* emit a
shape the mapper does not understand — only wrong content, which is the thing
under test. Anything malformed is DROPPED rather than repaired, because quietly
fixing the output would measure the fixer. And it commits through the same
`_commit`: the objects become the same `(action, intent)` pairs on the same
`Item`s, so a scorer sees two runs that differ in HOW the objects were decided
and in nothing else.
**What it measured** (the checkpoint sweep, 2026-09-14):
**count-correctness 66.0% on the sealed 300** — `dataset/runs/checkpoint-sweep-oneshot-sealed/manifest.json`,
`count_ok_rate 0.66` on rows fingerprint `6dc8c8674e39:300` — against `main`'s
**77.3%** on the byte-identical rows
(`DOCUMENTATION/experiments/checkpoints/RUN_STATUS.md:105-113`); and
**count-correctness 50.3% on the personas 300** —
`dataset/runs/checkpoint-sweep-personas-v2/manifest.json`, `count_ok_rate
0.5033` on fingerprint `1a3064b09c1c:300` — against `main`'s **79.3%** on the
same rows. The error bar was measured for the first time by running `main`
twice on the sealed set: 77.3 / 76.7, so **0.6 pt**, and both gaps are far
outside it. Read plainly: one schema-constrained call is 11 points behind the
machine on clean prompts and 29 points behind on the persona voices, so the
chain IS holding the number up — which is worth knowing before anyone
simplifies it. It is also roughly seven times faster (p50 5.4 s vs 40.2 s on
the sealed 300), which is the other half of the trade. **Both boards are `split:"test"` rows and are RETROSPECTIVE
ONLY**: they may never pick the next thing to work on
(`DOCUMENTATION/experiments/ITERATION_PROTOCOL.md`).

### The action set
**What:** What a voice command can *do* — 15 registered actions: create /
update / delete event, query_schedule, clarify (ask instead of guess),
create / update / complete / delete todo, add / complete / delete subtask,
query_todos, generate_workout_routine, schedule_workout.
**Where:** `assistant/actions/` — one package per domain, `@register`
plugin classes.
**How:** The registry auto-builds the LLM's system prompt from the action
schemas, so adding an action is one class; fuzzy title+date matching for
targets; deletes clear context memory.

### Task tags — a finite classification
**What:** Tasks classify into a closed set of classes (builtin: Groceries,
Coursework… + user customs) with per-tag colours, filtering, and "tag mode"
(auto-apply one tag to every voice task).
**Where:** registry `todo_tags` table (`db.py`); classifier
`assistant/actions/todo/tagging.py`; applied in
`assistant/actions/todo/action.py`; iOS tag UI in `TasksView`/`TaskRowView`.
**How:** Precedence: what the user said > tag mode > keyword inference
(`suggest_tags` over a large keyword→class map). `resolve_tags` heals LLM
near-misses to the closest class (case, plural stems incl. y↔ies, tight fuzzy
at 0.8) and drops far-off hallucinations — the finite set never grows by
accident.
**Inference is the STORE's, not each caller's** (2026-09-14): `create_todo`
infers when `tags` is `None` ("nobody chose") and leaves `[]` alone ("chosen to
be none" — what the Untagged filter relies on). It used to be every caller's
job and they disagreed: the API and the GUI quick-add inferred, calendar sync,
the workout planner and the coursework view did not, so a task's tag depended
on which surface made it. `update_todo` labels a renamed task that is still
untagged — how a calendar-sync task gets one when its event is renamed — and
never replaces a tag that already exists. Pinned by `tests/unit/test_autolabel.py`.
**Offline, on the phone:** the Mac serves the classifier's table at
`GET /tags/rules` (keywords, never-infer set, the real palette, and the user's
own vocabulary labels) and `TagClassifier.swift` scores against it, so a task
typed with the Mac away is tagged on the spot instead of landing untagged for
good — the Mac never re-tags a task it did not create. The table is served
rather than shipped: a second keyword list in a second language drifts, and
`personal_labels` ("Haxaga" is a course) cannot be compiled into an app at
all. The phone's answer is a **preview** — the queued create body still says
what the user said, so the Mac classifies it itself on replay and its answer
is the one that lands. `test_sync_bootstrap.py` transcribes the Swift
algorithm back into Python and asserts it agrees with `infer_tag`.

### Events: categories, colours & binder stacking
**What:** Every event auto-categorised and coloured — adjacent events never
share a colour, hand-picked colours are never overridden; overlapping events
stack like binders.
**Where:** `assistant/actions/calendar/categories.py`; stacking Mac-side in the
views + iOS `Features/Calendar/EventStacking.swift`; category registry
`~/.assistant_tools/categories.json`.
**Renaming moves the label** (2026-09-14): renaming is how a manual add gets
fixed — book "meeting", correct it to "gym" — and the category used to keep
describing the typo, and with it the colour. `update_event` reclassifies when
the title changes and the caller passed no `category`. The colour follows only
if it is still the OLD category's colour, i.e. this code wrote it; `_AUTO_COLORS`
alone cannot tell, since it only recognises a colour nothing has touched and so
calls every categorised event hand-picked.
**How:** Deterministic classifier over title/attendees/location with a
per-category palette; `auto_category_and_color` runs inside event INSERTs so
every write path (voice, GUI, API) gets it.

### Hebrew calendar & observance
**What:** Jewish/Israeli holidays in the views; Shabbat/yom tov/fast windows
computed from the sky (candle lighting → tzeit) at the user's actual location;
the observance check on AI-created one-offs (a FLAG since 2026-09-08, see
below); recurring series skip holy days (meals excepted, fasts inverted,
Shabbat-anchored kept).
**Where:** `assistant/observance.py`, `hebrew_calendar.py`;
`db._skip_for_observance`; engine gate in
`engine/decompose_validate/observance_gate.py` (moved out of the retired
`validate.py` on 2026-09-08, `c3364df`), consumed at
`decompose_validate/stage.py:213-221`; location from
the phone via `/observance/location`; iOS `HebrewDate.swift`,
`DeviceLocation.swift`.
**The one-off gate FLAGS, it no longer refuses** (Gil, 2026-09-08, same
commit): the verdict logic moved across intact — an engine-created one-off
inside Shabbat or yom tov must be leyning, a meal or davening, and on a fast a
meal must not be booked before the fast ends — but a positive verdict now lands
as `flag:observance` on the fix list and an `observance: <reason>` entry in
`item.slots["flags"]`, and the event is still created. The argument is in the
module header: a blocked item is a command that silently did nothing, and the
speaker is better served by the row existing with a note they can act on. The
SERIES rule (`db._skip_for_observance`) is unchanged and still skips.
**How:** `pyluach` + `astral`, sundown-bounded not midnight-bounded. All
gating sits behind `observance.enabled` (config, default on;
`MACALENDAR_OBSERVANCE` env override — the test harness turns it off).

### Recurring events
**What:** daily / weekly / monthly / **yearly** series — anything else is
rounded and the rounding is announced; "until" excludes its day,
"through"/"including" keep it; weekly series start on the soonest named
weekday, and a weekly series may name **several** weekdays.
**Where:** `db.create_event` + `db._next_date` (`db.py:459-505`) do the series
instancing; the cadence is read by `decompose_validate/resolve.py:450` (`resolve_recurrence`) on
the deep track and by `intent/recurrence.py` on the fast track; the rounding
announcement is `_rule_cadence_round_and_announce`
(`decompose_validate/object_rules.py:253`), whose unsupported-cadence table
is `decompose_validate/text_helpers.py:35-43` (`unsupported_cadence`, `:98`).
**How:** Series instances materialise as rows sharing `series_id`; observance
skipping applies per instance at creation.
**The fourth cadence** (Gil, 2026-09-08; `61f2fe6`): rounding a yearly ask to
monthly is 12× wrong and fires eleven times nobody asked for, so `yearly` is a
real cadence rather than a rounding. `db.py:495-504` steps it from the ANCHOR
month/day, because chaining from the previous instance would turn one leap-day
series into a permanent 28th.
**Several weekdays** (`3fa9bde`, 2026-09-08): `events.recur_days`
(`db.py:110,132`) carries "tuesday,thursday" for a WEEKLY series, so "gym every
tuesday and thursday" steps to the next NAMED day instead of always +7. It is
which days a weekly series lands on, not a fifth cadence. It is filled on the
deep track only — `resolve.py:689` → `stage.py:117,147` → `CalendarIntent.recur_days`
→ `db.py:923`.
**Two things the docs used to claim that the code still contradicts** (both
re-verified 2026-09-14, both live, neither fixed here):
- **The fast path still rounds yearly to monthly.** `intent/recurrence.py:40`
  is `(r"\bevery\s+year\b|\byearly\b|\bannually\b", "monthly", True)`, and
  `rule_parser.py:1324-1331` writes that cadence straight into the slots. So a
  confident rule parse of "book the check-up every year" still books a monthly
  series — the exact case the fourth cadence was added to stop.
  `resolve.py:481-483` was fixed; this second reader never was.
- **The rounding announcement is stale in two places.** `text_helpers.py:41`
  still lists `every <x>day and <y>day` as an unsupported cadence and announces
  a rounding that `recur_days` no longer performs, and the reply string at
  `object_rules.py:266` still reads *"I can only repeat daily, weekly or
  monthly"*, omitting the fourth.

### The API server
**What:** The single front door — 113 endpoints; every surface is its client.
**Where:** `assistant/api/server.py` (HTTP only — no parsing/execution);
generated reference `DOCUMENTATION/API_REFERENCE.md`
(`scripts/gen_api_reference.py`).
**How:** Flask with `--reload`; NDJSON streaming for voice; optional API key;
binds Tailscale with `--tailscale`. Colour-coded logs
(`api/log_color.py`, see `DOCUMENTATION/LOGGING.md`).

### Hosted calendar sync
**What:** Optional two-way Outlook sync and read-only ICS subscriptions —
supported, not required; the default posture is fully local.
**Where:** `assistant/calendar_sync/outlook_sync.py`,
`actions/calendar/graph_client.py`; `calendar_sources` table.
**How:** Dirty-row preservation when two-way is off; ICS rows are locked
read-only.

### The self-improvement loop
**What:** The AI system improves itself: measure against a 3,000-utterance
ground truth → read failures → predict → change one component → verify —
autonomous, with every score/change/decision recorded and plottable.
**Where:** `DOCUMENTATION/SELF_IMPROVEMENT.md` (the map);
`dataset/` (DATASET.md, HYPOTHESES.md, RESULTS.md, loop_log.csv,
loop_changes.csv); harness `scripts/engine_dataset_compare.py`,
`scripts/field_quality.py`, `scripts/plot_loop.py`; questions in `DEVQA.md`.
**How:** Frozen-clock replays at each row's recorded timestamp; metrics:
count-correctness, item-level P/R/F1, field quality (when-paramount,
similarity titles, classification tags), latency; noise floor and graduation
rules in `DOCUMENTATION/experiments/ITERATION_PROTOCOL.md`. Metrics are
organised BY COMPONENT, not as one flat list — `dataset/METRICS.md` is the map,
and REAL USAGE (`weekly_review`) outranks the rest because it is the only
instrument measuring real speech.
**Two standing constraints on it**, both live as of 2026-09-14:
- **A SEALED 300.** Since 2026-09-07 the stratified 300 in
  `dataset/inputs/test_split.json` is excluded from every run by default; the
  other 2,699 rows are free for mining and training. A `--test` run reports
  aggregates only and never spawns a hypothesis — direction comes from
  training-pool failures alone.
- **Whole-engine cycles are PAUSED.** `DOCUMENTATION/STAGE_ISOLATION_PLAN.md:3-4`
  (Gil, 2026-09-07) supersedes the whole-engine loop until each stage is proven
  on its own dataset; `dataset/loop_log.csv` ends at run 21, the sealed
  pre-loop baseline. The loop itself is intact and resumes once the parts are
  proven — what is paused is the scheduling, not the machinery.

### Diagnostics & self-observation logs
**What:** The system writes evidence about itself: `NLU_TRACKING.md` (every
parse with path + source), `SCENARIO_BUG.md` (an LLM-as-judge records cases
where the rule parser and the model disagreed), the hand-written audit
corpus (regression floor), and a routing-confidence calibration checker.
**Where:** appended by the engine/server; `scripts/audit_assistant.py`,
`scripts/calibration.py`. The audit corpus writes
`DOCUMENTATION/ASSISTANT_AUDIT_SUMMARY.md`; it is a **regression floor only**,
not the primary number (that is the verification dataset — see the
self-improvement loop).
**How:** All read-only instruments — they observe the live system, never
steer it.
**The calibration checker is measuring the wrong line** (verified 2026-09-14,
not fixed here). `scripts/calibration.py` hardcodes 0.85 as the routing
threshold in five places (`:3, 93, 99, 102, 112-120`), while the live one is
`RULE_THRESHOLD = 0.80` (`assistant/intent/rule_parser.py:102`, tuned
2026-09-07) with a sub-item bar of 0.60
(`assistant/engine/fastrule/objects.py:46`). So its "at or above 0.85 / below
0.85" split does not name the decision the engine actually makes — anything it
says about where to move the threshold is answering a question nobody asked.

### Published explainer pages
**What:** Public artifact pages (architecture, explorer, internals) whose
quoted constants are build-enforced against the code.
**Where:** `DOCUMENTATION/artifacts/*.html`;
guard `tests/unit/test_artifact_claims.py`;
brief `DOCUMENTATION/ARTIFACT_BUILDER.md`.
**How:** Any drifting number (endpoint counts, thresholds) turns the build
red naming the page.

### Weekly review
**What:** A Wednesday 10:00 report over real usage — flag rate, honest
accuracy (refuses below 3 approvals, drops verdict bursts).
**Where:** `scripts/weekly_review.py`; LaunchAgent;
`WEEKLY_REVIEW.md` output.
**How:** The real-world scoreboard the dataset loop eventually hands off to.


### Learned labellers — event category and task tags
**What:** Two classifiers that label what the assistant writes: a title → one
of thirteen event categories (and its colour), or → a set of task tags. They
**stack behind** the keyword rules rather than replacing them, and ship **off by
default**.
**Where:** `assistant/engine/label/` (`model.py`, `train.py`, `feedback.py`,
`datasets/`, `experiments/`); config `labels.model_event` /
`labels.model_task`; call sites `db.auto_category_and_color` and
`actions/todo/action.py`; tests `tests/unit/test_label_learning.py`.
**How:** Logistic regression over word 1-2 grams ∪ char_wb 3-5 grams. The rules
answer first and keep their measured 91.7% precision; the model only fills a row
they had no opinion about; below a confidence bar it abstains to the catch-all.
Two tiers — a BASE model identical for every user, built from committed
class-conditional datasets on first use, and a PERSONAL one fitted on top from
that user's own corrections and never leaving the machine. On vocabulary the
training never saw: event category 49.1% vs the rules' 33.0%, task tags 95.7%
exact-set on real data vs 88.6%. Numbers and method:
`engine/label/experiments/RESULTS.md`.

### Passive label learning — corrections become training data
**What:** When a person *changes* an assigned category or tag, that correction
is recorded and the personal model is refitted once enough have accumulated.
**Where:** `engine/label/feedback.py`; hooks in `db.update_event` and
`db.set_todo_tags`; `~/.assistant_tools/label_feedback.jsonl`
(`MACALENDAR_LABEL_FEEDBACK`).
**How:** **Only corrections and explicit picks are gold.** A label the system
assigned and nobody objected to is recorded but never trained on — silence is
not agreement, and training on it would teach the model its own output. Refits
trigger on new *gold* rows, not new items. A refit ships only through a
promotion gate: it must not regress on a frozen generic set and must improve on
a time-ordered held-out slice of that user's own corrections, with the incumbent
re-scored on the same rows.

### Offline command queue — see it, edit it, hold it
**What:** A command spoken while the Mac is unreachable shows what the phone
heard, can be corrected before it runs, and is not sent while you are editing it.
**Where:** iOS `LocalStore.swift` (`PendingVoiceCommand`), `APIClient.swift`
(`syncPendingVoice`), `ContentView.swift` (`VoiceQueueView`,
`QueuedCommandEditor`), `VoiceButton.swift`.
**How:** The on-device recogniser's `liveText` is kept as a draft when the
command is queued, so the row is not anonymous. Untouched → the audio is sent
and the Mac transcribes it properly; edited → the *text* is sent, because a
correction beats any re-transcription. `heldForEdit` makes every flush —
reconnect, foregrounding, the poll loop, opening the screen — walk past a row
being edited.


## Request protocol

**What it is.** One ollama serves four processes on the Mac and every phone on
the tailnet. This decides two things — *whose words may be spoken in one breath*
and *who gets the model next* — which are the same question, because identity
answers both.

**Where it lives.** `assistant/model_protocol.py`, wired into
`assistant/api/server.py` (verification, the `/devices/*` routes, the pending
flush), `assistant/intent/parser.py` and `llmseg` (the gate), and both clients.

**How it works.**

- **Enrolment.** `POST /devices/enroll` returns a server-generated id and an
  HMAC-SHA256 token over `(source, id)`. Clients enrol once and send both. A
  self-chosen id is only a claim: two devices could collide by accident, and any
  caller could elect to be your phone.
- **Merge or queue.** One device's queued commands coalesce into
  `("a")and("b")` — one person's backlog, one parse. Different devices never
  concatenate. Two iPhones are two people.
- **Unverified means ISOLATED, not refused.** A caller presenting an id it
  cannot prove lands in `ios:untrusted:<hash>` — its own queue. So spoofing buys
  nothing, a revoked device cannot rejoin the stream it owned, and old clients
  that send nothing keep working.
- **Priority.** A live device beats a background board, and a real device beats
  a test. It is a *yield* signal, not a mutex: LIVE tries for 50ms then proceeds
  anyway (a command degrades to slow, never to failed), BACKGROUND blocks and
  releases between every call.
- **The gate is `fcntl.flock`**, chosen because the kernel releases it when the
  holder dies — a crashed board must not wedge the assistant.
- **A failed retry stops batching.** A batch is all-or-nothing, so one
  unparseable command used to bump every row beside it; first attempt coalesces,
  every attempt after runs alone.

**Measured** (2026-09-10): before it existed, a trivial five-token call behind a
running board took 2.0s → 42.5s → 43.9s. With it, live waits 52-74ms while a
board is mid-inference; a killed board frees the gate in 0ms.

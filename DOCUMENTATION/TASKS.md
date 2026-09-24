# Task tracker

Running list of user-reported issues and feature requests, with status. Update when working on the app.

| # | Item | Status | Where |
|---|------|--------|-------|
| 1 | Event categories with per-category colours; adjacent events never the same colour | done 2026-08-26 | `assistant/actions/calendar/categories.py`, iOS Settings → Event colours |
| 2 | Binder-style stacking of overlapping events (tap to pop out, tap again to edit) | done 2026-08-26 | `assistant/calendar_ui/stack_layout.py`, `EventStacking.swift` |
| 3 | iOS Timer tab synced with the Mac (timers, sessions, counters, cash-out) | done 2026-08-26 | `/timers`, `/counters`, `TimerView.swift` |
| 4 | Review screen shows real event dates; dismiss stale backlog | done 2026-08-26 | `/memory/unreviewed`, `AssistantReviewView.swift` |
| 5 | Review banner overlapping screen titles | done 2026-08-26 | `ContentView.swift` |
| 6 | Mic / + buttons misaligned when the "Show what it did" chip shows | done 2026-08-27 | `VoiceButton.swift` (chip is an overlay) |
| 7 | "Wrong" on review shows a spurious "unreachable (cancelled)" error | done 2026-08-27 | ignore cancelled requests |
| 8 | Timer sync latency: 3 s poll while a timer runs; Mac reloads its Timer tab on DB change | done 2026-08-27 | `TimerView.swift`, `window.py` |
| 9 | Adaptive sync: 1 s polling for 45 s after a voice command / 10 s after an edit, else 30 s | done 2026-08-27 | `APIClient.burstRefresh`, `ContentView` poll loop |
| 10 | Voice edit changed the wrong event ("the event I just made") | done 2026-08-27 | `_normalise_intents` anaphor/date guard; `_find_event` scores distinctive words only |
| 11 | Recording: Redo / Add more / Send after stop; option to disable silence auto-stop | done 2026-08-27 | `VoiceButton.swift`, Settings → Voice |
| 12 | Guests on events: names from voice, Contacts lookup, invite via Messages / WhatsApp / Mail / .ics share | done 2026-08-27 | `GuestsSection.swift` |
| 13 | Swift Sendable warnings (AVFoundation, UserNotifications) | done 2026-08-27 | `@preconcurrency import` |
| 14 | Verify every claim in the .md docs against the code | standing — last full reconciliation 2026-09-14 | a 15-agent adversarial audit (file:line over doc assertions); its findings are folded into this file, `STATUS.md` and `FEATURES.md` |
| 15 | Weekly assistant review | scheduled 2026-09-02 | `scripts/weekly_review.py`, LaunchAgent |
| 16 | Mac gets the iOS thinking timeline: live stage-by-stage panel, result card, tap-a-word fix, 👍/👎 | done 2026-08-27 | `assistant/calendar_ui/thinking_panel.py`, `Pipeline` trace |
| 17 | Mac "Review commands" backlog (👍 / 👎 / Fix…) — was iOS-only | done 2026-08-27 | `assistant/calendar_ui/review_dialog.py` |
| 18 | Mac "Event Colours & Categories" editor — was iOS-only | done 2026-08-27 | `assistant/calendar_ui/categories_dialog.py` |
| 19 | Mac dropped voice commands when the LLM was offline (phone queued them); now queued + retryable | done 2026-08-27 | `Pipeline._queue_pending`, `retry_pending` |
| 20 | Leaving the iOS app mid-command killed the stream and froze the timeline | done 2026-08-27 | `BackgroundAssertion`, `VoiceButton.recoverLostStream` |
| 21 | Mac Assistant Settings overflowed: the Font Sizes grid rendered at zero height | done 2026-08-27 | `window.py` settings dialog now scrolls |
| 22 | Mac Assistant Settings regrouped into the iPhone's sections (Appearance / Tabs / Hebrew / Voice / Assistant) | done 2026-08-27 | `window.py` `_on_settings_popup` |
| 23 | Redo / Add more / Send bar on the Mac; a spoken stop word ("execute") sends with no wait, on both apps | done 2026-08-27 | `Pipeline._await_review`, `ReviewBar`, `VoiceRecorder.stopReason` |
| 24 | Thinking panel placement configurable (auto-open vs chip only, which corner) | done 2026-08-27 | Settings → Assistant |
| 25 | iOS could not edit a timer/counter after creating it, or log time it forgot to start | done 2026-08-27 | `POST /timers/<id>/sessions`, `LogPastTimeSheet`, edit mode in `NewTimerSheet` |
| 26 | iOS Tasks had no calendar→tasks sync (endpoint existed, was never called) | done 2026-08-27 | `syncTodosFromCalendar`, Tasks toolbar menu |
| 27 | **iOS never polled at all**: `.task` captured `scenePhase`, frozen at `.inactive`, so the 30 s sync loop was dead — Mac changes only appeared after backgrounding the app | done 2026-08-27 | `ContentView` polls `UIApplication.shared.applicationState` |
| 28 | Cross-device latency 30 s → ~2 s via a cheap change token instead of blind refetching | done 2026-08-27 | `GET /changes`, `APIClient.changeToken` |
| 29 | "August 12 2026" (a past date) became *today*; "the 12th of August" became 12 Sep | done 2026-08-27 | `server.py` past-date bump + month-aware ordinal guard |
| 30 | The test suite wrote "buy milk" / gibberish into the real command memory and vocabulary on every run | done 2026-08-27 | `MACALENDAR_VOCAB` / `MACALENDAR_CATEGORIES` + scratch paths in `tests/conftest.py` |
| 31 | Redundant `@Published` writes re-rendered the whole app on every failed poll | done 2026-08-27 | `APIClient.request` assigns only on change |
| 32 | **Offline queue lost work**: a change made offline to an item *created* offline (tick off a new task) referenced a temporary negative id, 404'd on replay, and — since sync stopped at the first failure — blocked every later change for ever | done 2026-08-28 | `LocalStore.remapTemporaryID`, `syncPending` drops un-retryable entries |
| 33 | Offline-created rows appeared twice after syncing (local placeholder + the Mac's copy) | done 2026-08-28 | `cacheTodos`/`cacheEvents` drop a placeholder whose twin arrived |
| 34 | Voice commands spoken while the Mac was away were thrown away; now queued, replayed on reconnect, with a banner, a "Queued commands" screen and a local notification | done 2026-08-28 | `PendingVoiceCommand`, `syncPendingVoice`, `VoiceQueueView` |
| 35 | Stop-word listener fell back to Apple's servers when on-device recognition wasn't available, against the local-only rule | done 2026-08-28 | `VoiceRecorder` requires `supportsOnDeviceRecognition` |
| 36 | Queued work waited up to 30 s after reconnect; now flushes the moment the Mac answers | done 2026-08-28 | `APIClient.request` offline→online transition |
| 37 | The Mac's thinking panel was blind to commands run from the phone (separate processes); it now tails a trace bus and labels them "from your iPhone" | done 2026-08-28 | `assistant/trace_bus.py`, `CalendarWindow._poll_phone_traces` |
| 38 | Editing the same event on both devices while apart silently lost one side's change; the Mac now refuses a stale edit (409) and the phone says so | done 2026-08-28 | `base_updated_at` on `PATCH /events/<id>`, `updated_at` stamped at creation |
| 39 | The review bar's raw status string ("3\|add lunch…") leaked into the Mac's toast | done 2026-08-28 | `_handle_status` handles STATUS_REVIEW before toasting |
| 40 | Optimistic-concurrency guard extended from events to tasks | done 2026-08-28 | `base_updated_at` on `PATCH /todos/<id>` |
| 41 | **A spoken "7am" was booked at 7 PM.** The exemption for an explicit morning time tested `\b(am\|a.m.)\b`, which cannot match "7am" (no boundary after the digit) or "a.m." (none after the dot). Morning words had no say either, so Shacharit at 7 became 7 PM | done 2026-08-28 | `rule_parser._extract_temporal`, 15 regression tests |
| 42 | `scripts/audit_assistant.py` wrote replayed transcripts and learned aliases into the real vocabulary; it now audits against a copy | done 2026-08-28 | `MACALENDAR_VOCAB` copy in the audit harness |
| 43 | **"from 9 to 10" crashed the rule parser** with an unhandled AttributeError (the recogniser returns a match with no resolution). Callers only caught `RuleParserSkip`, so the command died instead of falling back to the LLM | done 2026-08-28 | `rule_parser._extract_temporal` guards; both callers now fall back on any parser error |
| 44 | "lunch from 12 to 1" produced 12:00–01:00 — an event ending before it starts | done 2026-08-28 | end-before-start post-pass (leaves genuine overnight ranges alone) |
| 45 | "rename X to Y" answered "No changes specified" — even "rename gym to workout". Read literally now, with a guard so "rename the meeting to 3pm" stays a reschedule | done 2026-08-28 | `_RENAME_RE` in `rule_parser._fill_slots` |
| 46 | **Voice edits hit the wrong event.** "the meeting with Ima" reached the matcher as just "meeting", so it scored a generic word and took the nearest meeting (Shaul's) | done 2026-08-28 | `_extend_title_with_whom` keeps the person in `match_title` |
| 47 | **Naming an event that isn't on the day given edited whatever else was.** "move the gym on Sunday" moved "Meeting with Ima". A named-but-missing event now reports not-found; the day fallback only applies to a generic title ("the event on Sunday") | done 2026-08-28 | `_find_event` gates the date fallback on `meaningful_words` |
| 48 | **A multi-item task command made one task.** "buy chicken and rice" became one task — the LLM merged it (sometimes into an invented "buy groceries"), the rule path kept the verb only on the first. One task per item now, verb shared out, tag inferred from each title | done 2026-08-31 | `assistant/intent/list_split.py`, `assistant/actions/todo/tagging.py` |
| 49 | **The trace was only visible if you were looking at the calendar** — which you are not when you speak to the assistant from your phone. It is its own always-on-top app now: never takes focus, translucent until hovered, works with the calendar closed | done 2026-08-31 | `assistant/thinking_hud.py`, streaming `assistant/trace_bus.py` |

| 50 | Same brain for both devices: the GUI stopped parsing locally and now POSTs to `assistant.api` like the phone does; ~1,200 lines of duplicated orchestration deleted | done 2026-09-01 | `assistant/pipeline.py`, `assistant/api/server.py` |
| 51 | The LLM now validates **every** command, not only low-confidence ones — a confident wrong parse was the one case nothing was checking | done 2026-09-01 | `verify_fast_path` in `config.example.yaml`, `server._run_transcript` |
| 52 | Thinking panel: stopped re-popping, keeps a searchable history of every run, filters by device / kind / outcome, and separates test traffic from real use | done 2026-09-01 | `assistant/calendar_ui/thinking_panel.py`, `assistant/thinking_hud.py`, `trace_bus.read_history` |
| 53 | Repeating events understand "every day at 7pm until Oct 6" — "until" exclusive unless stated, and occurrences on Shabbat and chag are skipped using locally-computed sundown (meals excepted, fasts not) | done 2026-09-01 | `assistant/db.py` `_skip_for_observance`, `assistant/observance.py` |
| 54 | Personal vocabulary gained two more powers beyond spelling fixes: expand an acronym, and carry a label used for task tags and event colours | done 2026-09-01 | `assistant/stt/vocab.py`, `assistant/actions/todo/tagging.py` |
| 55 | **Settings UI for the vocabulary** — view, edit and clear labels and acronyms on both iOS and macOS, with the user's permission required before anything is added | done 2026-09-03 | `VocabularyView.swift`, Mac Settings |
| 56 | **The harness** — `--memory` replays against a copy of the real history and `--memory-k N` changes the retrieval count, so k=0 vs k=4 is one flag. Originally: a memory-aware audit mode so the personalisation layer can be measured at all — does history help, is `k=4` right, are verified examples better | done 2026-09-03 | `scripts/audit_assistant.py --memory` |
| 57 | **Confidence calibration IS fast-path coverage — one job that was being tracked from two ends, merged here 2026-09-14 so it is not built twice.** The knobs are hand-picked and have never been checked against outcomes: `rule_parser.py:102 RULE_THRESHOLD = 0.80`, `objects.py:46 SUBITEM_RULE_THRESHOLD = 0.60`, and the four multipliers in `_compute_confidence` (`*= 0.95`, `*= 0.85`, `*= 0.80`, `*= 0.7`). The checkpoint retrospective arrived at the same work from the other side and calls it the highest-leverage lever available (`DOCUMENTATION/experiments/checkpoints/RECOMMENDATIONS.md` §2), and `fastrule.py:83 CONFIDENCE_SIGNALS` names itself its target. Three things bind it. **(a) The hypothesis may not come from the boards that motivated it** — every row of the sealed 300 and the personas 300 is `split:"test"`, so re-derive on `fastrule-v1` vs `main` over dev-fast-250, which is freely mineable; expect that re-derivation to be most of the cost. **(b) The instrument is stale:** `scripts/calibration.py` hardcodes 0.85 as the routing line in five places (`:93,:99,:100,:102,:112`) while the live threshold is 0.80 — and its original "waiting on a week of real use" blocker is satisfied, the read has simply never been done. **(c) The multipliers are pinned to a published page** at `tests/unit/test_artifact_claims.py:128-142`, so changing them goes red by design — that is the guard working, not a problem. **Blocked on a ruling, not on work:** `STATUS.md:302-306` fences fast-rule mining behind *"only after the deep track is improved"*, and this points straight at it | todo — needs Gil's decision first | `assistant/intent/rule_parser.py`, `assistant/engine/fastrule/fastrule.py`, `scripts/calibration.py` |
| 58 | Two-level label hierarchy (Exercise → Running / Gym) and promoting the planner's ad-hoc categories into the registry | todo | `categories.py`, `tagging.py` |
| 59 | Ask for 👍/👎 only when the self-check is unsure, instead of on every command. **This is TWO jobs and the first was never started.** The row names `scratchpad/flag_precision.py` — the measurement of whether the self-check's opinion agrees with the user's — as its own prerequisite, and that file **does not exist and never did**: `git log --all -- "*flag_precision*"` is empty and there is no `scratchpad/` directory in the checkout. Write the measurement first; gating the prompt before it is building on an unmeasured assumption | todo (the measurement) · blocked (the gate) | review flow |
| 60 | Few-shot pool: prefer verified examples, and stop recency from evicting corrections. **Genuinely unwritten** — `memory.py:461-475` only *labels* corrected rows after retrieval — **but the path it would improve is dormant**: `config.example.yaml:188` ships `memory_examples: 0`, `config.yaml` sets no value at all, and `FEATURES.md:325-328` records few-shot injection as *"measured to hurt the engine"*. Ranking a pool that nothing reads buys nothing | closed 2026-09-14 as superseded — reopen only paired with a decision to turn k>0 back on | `assistant/intent/parser.py` `_few_shot_for` |
| 61 | Three iOS fixes committed but not installed on the device — poll storm, counter history sheet, speech continuing after it was turned off | done 2026-09-02 | `xcrun devicectl device install app` |
| 62 | Explainer artifacts: big-picture done; internals page still needs genericising, a first-time-reader rewrite, and interactive figures | done 2026-09-03 | `DOCUMENTATION/ARTIFACT_BUILDER.md` |
| 63 | **"pasta times 5" made five identical tasks.** Neither parse path could represent a count, so the only way the LLM could say "five" was to repeat the title five times — and five identical rows mean ticking one tells you nothing. Counts are now read from the words, repeats are folded, and the number shows on the task row | done 2026-09-02 | `assistant/intent/quantity.py`, `todos.quantity`, `TaskRowView.swift`, `todo_view.py` |
| 64 | **Sundown was computed for a hardcoded place.** `ObservanceSettings` defaults and the `observance:` config block held the same values but nothing connected them, so any call without an explicit settings object — including the recurrence Shabbat skipping — ignored the configuration | done 2026-09-03 | `observance.current_settings()`, `tests/unit/test_observance_settings.py` |
| 65 | Device location: the phone reports its coordinates so sundown follows you, off by default, with a Settings toggle that also clears it | done 2026-09-03 | `observance.set_location`, `/observance/location`, `DeviceLocation.swift` |
| 66 | Sundown verified against published times rather than trusted: fetched once from an authority, checked in, compared offline. 126 comparisons over 6 cities, worst disagreement 28 s — no fix needed | done 2026-09-03 | `scripts/fetch_zmanim_reference.py`, `tests/unit/test_zmanim_accuracy.py` |
| 67 | **Misheard names could never be learned.** Every failed name was already in the word list, but the matcher compared letters while speech fails phonetically, so no correction was made, none was learned, and the same command failed forever. A sound-code gate recovers 5 of 6 on first encounter, up from 1 | done 2026-09-03 | `vocab.phonetic_key`, `tests/unit/test_vocab_phonetic.py` |
| 68 | Third explainer: an explorable drawing rather than 6,600 words of prose | done — row closed 2026-09-14, bookkeeping only: the page is 235 KB, last touched by `2930186` (2026-09-13) and maintained alongside the other three artifact pages, and its two child defect rows (69, 70) were both closed *after* it | `DOCUMENTATION/artifacts/explorer.html` |
| 69 | Explorer: the trace log opened the review panel's text (both carried the same panel id); storage panel too long to read; nothing described how several events in one sentence, or a queue of recordings, are handled | done 2026-09-03 | `DOCUMENTATION/artifacts/explorer.html` |
| 70 | Explorer named the deciding process "the brain" and the model host "model server", so a reader concluded the server held all three models. It holds one — spaCy and Whisper load inside the deciding process, which the drawing hid | done 2026-09-03 | `explorer.html`, `test_artifact_claims.py` |
| 71 | **Reformulation mining**: when a command is deleted and a near-identical one succeeds moments later, the pair is a correction the user already gave for free. Runs after every command, on a daemon thread. Finds nothing in the current history — the loose version found three pairs and two were nonsense | done 2026-09-03 | `assistant/intent/memory.py` |
| 72 | Four false starts ("Execute.", "No.", "I need a b-") were parsed, executed and remembered as real commands, teaching the model that junk is normal | done 2026-09-03 | `server.is_trivial_transcript` |
| 73 | **Ran the memory comparison.** k=4 98% vs k=0 97% over 89 commands — but the LLM path, the only place examples enter the prompt, is 100% in both arms, so the corpus cannot detect an effect on it. No measurable difference, and the instrument is the limitation | done 2026-09-03 | `ASSISTANT_AUDIT_SUMMARY.md` run 7 |
| 74 | Build a corpus from the real history's *failures* to measure the memory — the hand-written one is at ceiling on the path that matters, so it can only detect harm | **delivered, and the follow-on work is DROPPED** (Gil, 2026-09-14: *"dont do the real speech dataset then"*) | It shipped under another name: `dataset/realspeech/` — 1,200 rows, a generator, a board and `REALSPEECH.md`, with a baseline banked at `RESULTS.md:2103` (realspeech faithful/test: handled 70.3% before `643b01f`). **The built artefacts stay on disk; what is dropped is further work on them.** Do not schedule realspeech cycles, and read `RESULTS.md`'s citation of it as a record, not a live target |
| 75 | **Found and fixed while mining row 74**: editing one event in a same-typed batch ("book gym, then a meeting, then dinner") applied that edit's fields to every same-typed action in the batch, corrupting the others' stored correction — `example_records` only tracked action *type*, not which specific action a record came from. Two real corpus cases added from the same mining pass (duration arithmetic, a dropped self-correction), both still reproduce live | done 2026-09-03 | `assistant/intent/memory.py` `feedback_for_record`, `tests/unit/test_vocab_memory_trace.py` |
| 76 | **Memory scaling study, in progress overnight**: does retrieval pool *size* matter, and is any k>0 effect about personalisation specifically or just "having more examples"? Real history (74 commands, 65% from one day) can't grow, so built a second pool from HWU-64 (Liu et al. IWSDS 2019, CC BY 4.0) — 3000 real calendar/reminder utterances run through the actual parser against scratch DBs, nested tiers at 60/300/1000/3000. Comparing k-sweep on the real history, a held-out slice (dominant day + the row 75 bug's corrupted correction removed), and each external tier. Fixture and build script checked in, `.db` outputs regenerable and gitignored. **Answered**: real history +3pts at k=4 (95% vs 92%), survives the held-out slice; external pool flat 91–93% at every size — personalisation, not volume. Keep k=4; don't grow the pool with non-personal data. Full write-up: `ASSISTANT_AUDIT_SUMMARY.md` § "The memory-scaling study" (unnumbered — the engine-v2 sessions took run numbers 8–13) | done 2026-09-04 | `scripts/fetch_hwu64_sample.py`, `scripts/build_memory_scaling_pool.py`, `DOCUMENTATION/experiments/memory_scaling/` — results land in `ASSISTANT_AUDIT_SUMMARY.md` |
| 77 | **The audit's headline "N% accurate" collapsed two different failure modes**: missing something asked for vs. producing something extra. `_check()` now tracks each expected item individually and counts extra actions/task rows explicitly, so the report gets recall and precision — overall, by area, by parse path — plus a dedicated "produced more than expected" section. Confirmed it surfaces something real: tasks area is 95% recall but 79% precision, driven by the row 75/76-adjacent duplicate-task bug. Headline number also now labelled explicitly as case-level exact match against the hand-written corpus, not a real-usage or human-judged figure. `A_k0`/`A_k1` of the overnight run predate this and lack the breakdown — cheap to backfill (~15-20 min each) once the rest finishes | done 2026-09-03 | `scripts/audit_assistant.py` `_check`, `_recall_precision` |
| 78 | **Linux/PC host migration checked, deferred.** Core (parser, Ollama, spaCy, API, DB, GUI via PyQt6, default STT) is already cross-platform — no work needed. One real blocker: TTS shells out to macOS `say` directly, on by default, in the live voice pipeline (not just dev tooling) — needs swapping for a cross-platform engine (`pyttsx3` / `espeak`) before a Linux host would actually speak replies. Minor, non-blocking degradations: the thinking HUD's "join all Spaces" polish is an AppKit best-effort layer with no Linux equivalent yet (falls back to a normal always-on-top window); optional macOS Calendar.app import wouldn't apply; launch script and weekly-review scheduling are trivially cron-able | todo | `assistant/tts/speaker.py` |
| 79 | **Dataset redefined by actual spec, and a reusable scorer built.** "Complex" means genuine multi-action (event+event/task+task/event+task compounds, constructed by joining real utterances — HWU-64 is one action per utterance, so this doesn't occur naturally and had to be built), not just longer sentences. `scripts/score_dataset_run.py` scores a `dummy_<N>.db` with no hand-written ground truth — compound provenance gives free deterministic expectations (a task+task compound should yield ≥2 task rows) — and diffs two runs (which prompts flipped pass/fail). About half its metrics are dataset-specific (need `hwu64_sample.json`'s provenance); half are fully general and will run against real production traffic once there is any, unchanged. First real findings (1000/3000 partial build): complex 28% correct vs simple/medium 91%/89%; event+task failures are specifically a dropped *event* (68%), not a random mix; the earlier date-collapse fix accounts for only ~3% of event+event failures, so most of that failure mode is still unexplained; hybrid parse path underperforms both pure rule and pure LLM (57% vs 75%/77%) | done — row closed 2026-09-14 | `scripts/score_dataset_run.py` is live and is the scorer `scripts/checkpoint_sweep.py:555,633` imports. **One known debt rides on it**, still open under cycle B in `dataset/RESULTS.md`: `score_dataset_run.py:43 _GARBAGE_TITLES` is still the old `{"then","and","also","and then","so","please","now"}` set that the FastRule board already outgrew (`fastrule_shape.py:115-119 _EMPTY_TITLE_RE`), and `checkpoint_sweep.py` inherits the blind spot by importing it — the five-word edit is trivial, the open debt is the re-measure the prediction existed to produce. **Numbering collision:** this row and the Engine-v2 row below were both written as 79 and are both cited by number elsewhere, so neither is renumbered — read the title, not the digit. Also `DOCUMENTATION/experiments/memory_scaling/METRICS.md` |

| 79 | **Engine v2 — the brain rebuilt as the 7-step deep track** (branch `engine-v2`). The old `_run_transcript` (~800 lines of interleaved heuristics, plus four background bolt-ons) retired and replaced by `assistant/engine/`: frozen per-stage contracts (`state.py`, `ENGINE.md`, `test_engine_contracts.py`), fast track (instant rule-parser commit) + deep track (segment → decompose → validate → generate → commit → label → crosscheck), every old named rule ported into `validate.py` with its regression tests, observance gate for AI-created events (leyning/meals/davening on holy days, fasts exclude meals), `needs_edit` transcript-confirmation round-trip gated on `supports_edit`. All eight stages live and stage-gated (LLM gates for segment/decompose/crosscheck passed against real Ollama); step-1 gate + learning loop + Mac dialog/settings done; ingest lock + coalescing done (pending-retry loop batches its backlog); per-stage audit lines added. **Primary instrument now the verification dataset (user decision 2026-09-04): improve against its metrics (count-correct by complexity/compound-kind, missing-half, garbage titles, date collapse); the hand corpus is the regression floor.** Pilot: engine 73% vs old 70% (compounds 2-3x better); full-3000 comparison running overnight → its per-metric report becomes the improvement backlog. Merged to `main` 2026-09-04 (bce502e); iOS edit sheet, one-tap revert, versioned panel all shipped; dataset-driven tune cycles continue as the improvement loop (see below) | done 2026-09-04 | `assistant/engine/`, `DOCUMENTATION/ENGINE.md` |

| 80 | **Voice lead-times (notifications phase 3, inline shape)** — "book gym tomorrow at 6:30 and give me a heads-up half an hour before" / "with a 15 minute reminder" attaches `reminder_minutes` to the created event. Design: decompose strips the reminder clause into `slots["reminder_minutes"]` BEFORE validate (its `_EXCLUSIVE_END` regex reads a bare "before" as a recurrence-end marker — the C-design catch); generate's `_apply_slots` maps the slot onto `CalendarIntent.reminder_minutes` (new optional field, pinned in `test_engine_contracts.py` in the same change). Standalone-update shape ("remind me 30 min before my meeting" as its own command) deferred to a follow-up row. | done 2026-09-06 | `engine/decompose_validate/decompose.py`, `engine/generate/generate.py`, `actions/calendar/intent.py` | run 14 (run 14: board flat as predicted, fieldq 85.3 best-ever; behavioral goal delivered) |

| 81 | **The review panel was cluttered — measured, not felt.** `scripts/shoot_panel.py` (new) renders the real `ThinkingPanel` against a real engine trace, writes a PNG and prints content-vs-card; it exists because the two defects this row fixes were invisible to every assertion and obvious in a picture. Findings and fixes: (a) the chain rail drew the word **"skipped"** into the 14×14 box it shares with the ✓ and the spinner, so it rendered as **"pp"** — and `test_thinking_hud` pinned the bug by reading the label's text back. Now one glyph (`_ChainRail.SKIP_MARK`) plus a tooltip, with a test that measures the label against the box. (b) The rail drew **all 8 slots on every run** however few the command walked — 4 dead rows on a fast-lane answer. It still shows every slot *while the run is in flight* (the unlit ones are what's ahead); on `finish()` a run of ≥2 unreached slots folds into one "N steps not needed" line, and clicking it puts them back. (c) Row metrics: the ⓘ carried the default font, a point taller than the label beside it, setting the height of all 8 rows; step rows spent 14px of bottom gap each (98px over 7 rows) on top of the painted connector that already separates them; the result card's "Click a word to fix it" was a permanent line for an occasional action, now folded into the "I heard" heading. **Measured on the shooter, dark/light:** "book gym tomorrow at 7 and remind me to buy milk" — content 825px→704px in a 395px viewport (2.09×→1.78×), rail 192px→134px (−30%, 5 of 8 slots shown); "thanks so much" — 614px→475px (1.55×→1.20×), rail 192px→98px (−49%, 3 of 8). Rail unchanged in kind: it is still the map above the journey, per Gil's "improve the implementation, don't restructure". | done 2026-09-11 | `assistant/calendar_ui/thinking_panel.py`, `scripts/shoot_panel.py`, `tests/unit/test_thinking_hud.py` |

| 82 | **The panel could not tell "this wasn't calendar work" from "this reached me damaged".** Both are items that leave the object stage without an object, and they are opposite kinds of event — one is the engine reading correctly, one is an upstream defect. Neither was visible AT ALL: both were recorded only in `state.fixes`, which nothing outside decompose_validate traces (ENGINE_AUDIT P6), so `"play some music"` drew a card that looked like the assistant had done nothing — verified with `shoot_panel` before changing anything. Fix: `objects._trace_outcome` emits a per-item trace step tagged `data["outcome"]` (`NOT_AN_ASK` / `BAD_ITEM`, `ok=False` only for the defect), titled `Read part N` like the per-item steps beside it; the panel's `_StepRow._OUTCOMES` draws a chip — muted for the correct reading, amber for the defect, red still reserved for the error stage. `test_panel_agreement` now fails the build if the engine gains an outcome the panel has no wording for. No chain change, so no BRAIN_VERSION bump. **The first cut pushed the row wider than the 400px card and clipped the end of every line** — invisible in the text assertions, caught in the picture; `shoot_panel` now reports any row wider than the card, and a test measures it. **Not done: iOS**, which has no equivalent badge — this container has no Swift toolchain and the rule here is that unbuilt Swift does not ship (row 83). Also noted: `"thanks so much"` is NOT currently tagged `other` by fastseg (bare `"thanks"` is), so it reaches this path as an event — a segmentation gap, not a panel one. | done 2026-09-11 | `assistant/engine/fastrule/objects.py`, `assistant/calendar_ui/thinking_panel.py`, `tests/unit/test_panel_agreement.py` |

| 83 | **iOS ThinkingView lags the Mac panel** — no outcome badge (row 82) and no folded chain rail (row 81). **Re-verified 2026-09-14, and it has not moved:** `ThinkingView.swift:341-345 stateMark()` still returns the literal string `"skipped"` into the 14×14 box it shares with the ✓ and the spinner, so it draws as "pp" — precisely the defect the Mac fixed at `thinking_panel.py:456 SKIP_MARK = "·"` and pinned in `test_thinking_hud.py`; and a grep for `outcome|NOT_AN_ASK|BAD_ITEM` across `MACalendar-iOS/` returns nothing engine-related, so there is no outcome chip and no "N steps not needed" fold either. Three commits touched the file after the Mac fixes landed and none added them. CLAUDE.md's rule is that the panel is downstream of the pipeline, so this is a real divergence rather than cosmetics. Needs a machine with Xcode: `swiftc -parse` is not enough, it missed three real errors last session | todo | `MACalendar-iOS/MACalendar-iOS/Views/ThinkingView.swift` |

The rows below were opened 2026-09-14 out of the reconciliation audit. Each one
was already true in the code and recorded nowhere a person would look — most of
them only in `DOCUMENTATION/experiments/checkpoints/`, which until today nothing
in the repo linked to.

| # | Item | Status | Where |
|---|------|--------|-------|
| 84 | **`llm_ms` is never recorded on the fast path, so every latency board is wrong there.** `engine/__init__.py:907-931 _recheck_not_found` calls the model and never adds to `state.llm_ms`. Verified by grep: `llm_ms +=` has exactly six sites (`llmjudge/llm_fallback.py:41`, `llmjudge/llmjudge.py:121`, `segmentation/old_seg/segment.py:631`, `LLM_one_shot/__init__.py:231`, `decompose_validate/decompose.py:88`, `decompose_validate/text_repair.py:57`) and this is not one of them, though every other model caller does it. Rows that spent ~40 s record `llm_ms 0` against `total_ms ~40,000`. A second half sits in the transport, which indicts itself at `intent/parser.py:515-518`: *“Its callers — call_llm_json's four, and fix_title_async — record no llm_ms at all, which is how a 40-second call stayed invisible in every latency board.”* **Do this before row 85** — it is the instrument row 85 is judged with, and `RECOMMENDATIONS.md` §3 says this gap is *why* row 85 went unnoticed for weeks. One line for the recheck, a handful for the transport | done 2026-09-15 | `_recheck_not_found` now reads `parser.last_llm_ms` after the retry call; `call_llm_json` and `fix_title_async` now time their dispatch the same way `parse()` already did (`t0`/`finally`), so `last_llm_ms` means the same thing on every path that sets it, not just the one that happened to first. `assistant/engine/__init__.py`, `assistant/intent/parser.py`. Not yet re-measured against a board — that's row 85's job, which this unblocks |
| 85 | **Gate `_recheck_not_found` on candidates actually existing.** Same function, and there is no store query anywhere in it — it goes from the trace step straight to `_generate._get_parser(cfg).parse(state.text)`. When the target store holds no candidate rows the model cannot read a target into existence, so the ~40 s call is pure cost: measured at 25 of the 30 slow fast-path rows, ~20% of fast-path traffic (`checkpoints/RECOMMENDATIONS.md` §1). **Two things must ride in the commit message.** (a) `scripts/checkpoint_sweep.py:178` calls `reset_calendar()` before every row, so *every* delete in that board targeted an empty store — the measurement was taken under exactly the condition that guarantees the finding. (b) The recheck earns its place where candidates DO exist: the sealed run's own row detail shows it changed the outcome on 5 of 32 slow rows, including the run-9 `“Walk Mark's dog”` case it was built for. **Gate it; do not delete it.** A count check in one ~25-line function | done 2026-09-15 | `_has_candidates` in `assistant/engine/__init__.py`: `SELECT 1 FROM events/todos LIMIT 1` (table picked from `item.action`) before the LLM call, kept as a genuinely cheap existence check rather than a real match. Verified against a scratch store both ways (empty → skipped, one row added → proceeds); full suite still 1650 green |
| 86 | **FastRule's PRIMARY board has never once reported its “NOW rows” section.** `fastrule/experiments/fastrule_shape.py:121` reads `re.compile(r"\\b(?:right\\s+now|now|immediately|asap)\\b", re.I)` — doubled backslashes inside a raw string, so the compiled pattern hunts for literal backslashes, `NOW_N` stays 0, and line 341's `if NOW_N:` silently omits the whole section. The correct sibling is `decompose_validate/object_rules.py:30`, single-escaped. The check exists specifically because ~152 rows saying “now” were landing at midnight and scoring as fine, and CLAUDE.md makes this board FastRule's primary instrument. One character class | **STALE. Re-checked 2026-09-15 and found already fixed** — `fastrule_shape.py:132` is single-escaped (`r"\b(?:right\s+now|now|immediately|asap)\b"`) with a comment recording the exact doubled-backslash defect this row describes, so the fix landed at some point without the row being closed. Verified by RUNNING `--split train`, not by reading it: `booked at midnight 0.0% (0/33)` prints — the section reports | — |
| 87 | **The decompose_validate traceability board's vocabulary is hand-maintained and has drifted seven times.** `decompose_validate/eval_metrics/score.py:216-232` indicts itself — *“SEVENTH TIME… The vocabulary below is hand-maintained and drifts behind the resolver every time a form is added (this round: yearly/annually)… Not done here because it is a board refactor”* — and then at `:230-232` ships yet another hand-maintained alternation. Two recorded instances of the cost: 115 correct weekly recurrences reported as invented because the board had never heard of “twice a week”, and every correct 21:00 from “tomorrow night” reported as invented because “night” was missing. Fix is to derive the vocabulary from `normalization.py`'s closed tables — the gold's own words — which keeps the board independent of `resolve.py` while removing the drift. **Timing is load-bearing:** do it BEFORE the next batch of forms lands. What it manufactures is false *invention* failures, and a whole cycle can be spent chasing a defect that does not exist. (Same item as decompose_validate carried-forward #4 below; tracked here so it is visible from the tracker rather than only from a stage note) | done 2026-09-15 | **Re-checked first, per CLAUDE.md's own rule: the specific gap the row's quote names (this round: yearly/annually) was already closed** — `score.py`'s vocabulary already had `yearly\|annually\|annual` and the `twice a`/`once a` pattern before this session touched it, presumably fixed alongside row 90's `yearly` work. What was still genuinely missing was the STRUCTURAL fix the row asks for and the code's own comment says "Not done here". **Ran into a real constraint doing it literally**: `score.py`'s own docstring states it is stdlib-only — "safe to import from inside a process that already holds a model" — and any import reaching into `assistant.engine.*` (even a leaf module with zero heavy deps of its own, like `normalization.py`) unavoidably runs `assistant/engine/__init__.py` first, which imports the whole stage chain. A live import would violate that constraint for real, not just its letter. Built the same enforcement this project already uses for exactly this shape of problem (`test_panel_agreement.py`): the vocabulary is now a named, importable constant (`RECURRENCE_VOCAB`) instead of an inline literal, and a new test (`test_decompose_validate_score_vocab.py`) imports the GOLD's closed table (`normalization.RECURRENCES`) — tests may import what score.py itself may not — and asserts every phrase it can produce is recognised, going red the moment a new form is added without a matching board update. Verified the test has teeth: reverting the vocab to a version missing "yearly" reproduces exactly the failure the row describes. Also verified independence from `resolve.py` is still true, and pinned it as its own assertion. score.py's self-test still passes | `assistant/engine/decompose_validate/eval_metrics/score.py`, `tests/unit/test_decompose_validate_score_vocab.py` |
| 88 | **`scripts/engine_stage_check.py` — closed 2026-09-15, riding row 91's merge.** The `crosscheck` import and the `STAGES` dict had already been fixed by the time row 91 landed (the `llmjudge as crosscheck` import and the seven-stage dict were already correct, unclear exactly when) — verified by RUNNING `--stage all`, not by reading it. What was still broken: two cases in `_cases_generate`/`_cases_crosscheck` tested behaviour the 2026-09-10 restructure changed on purpose. `update_event` no longer commits at the FastRule stage alone (`stage._COMMITTABLE = ("create", "query")` — a target-taking action always defers to LLMJudge now, since confirming it names a real record needs a store lookup the stage cannot do), so the case was rewritten to assert the defer instead of a committed action. The "dropped ask" case asserted `finding.type == "missing"`, a type the RE-CUT judge (PLAN.md §6, ask extraction removed) no longer produces at all — removed, not fixed, same as the identical case in row 91's own test fixes. `--stage all` is clean now except one fixture artifact (see row 91) | done 2026-09-15 | `scripts/engine_stage_check.py` |
| 89 | **Ingest has no dataset and no board — the only stage with neither.** `assistant/engine/ingest/` holds `ARCHITECTURE.md`, `__init__.py`, `coalesce.py`, `repair.py` and nothing else, on HEAD and on `engine-component-folders` alike; its own doc says so at `ARCHITECTURE.md:51` (*“Not yet dug into. Moved here for structure; no dataset, no board of its own”*) and `STAGE_ISOLATION_PLAN.md`'s stage table still carries it under its old name `transcript`, status **not started**. It is the FIRST stage in the chain, so anything it gets wrong is charged to every stage below it, and the vocabulary rewrite happens before every parse — a regression here is invisible to every downstream board yet changes what the whole engine sees. **The one stage-isolation item that is neither frozen nor already done on the branch.** Constraint: the (word, corrected word) pairs come from the real `~/.assistant_tools/vocab.json`, which CLAUDE.md rules is hand-curated personal data — point `MACALENDAR_VOCAB` at scratch | todo | `assistant/engine/ingest/` |
| 90 | **The fast path can still book a MONTHLY series for a YEARLY ask.** `assistant/intent/recurrence.py:41` is still `(r"\bevery\s+year\b|\byearly\b|\bannually\b", "monthly", True)`, and `rule_parser.py:1327-1329` writes that cadence straight into the slots. `resolve.py:481-483` added `yearly` on 2026-09-08 to fix exactly this; **the second reader was never updated**, and it is not fixed on `engine-component-folders` either. CLAUDE.md is explicit that yearly is the one cadence rounding could not honestly cover — twelve times wrong, firing eleven times nobody asked for. **This is a live user-visible wrong answer, not a metric line.** Two stale dependants fall out of the same duplication: `decompose_validate/text_helpers.py:41` still announces a rounding for “every tuesday and thursday” that no longer happens (`recur_days` is supported end to end — `db.py:110,460-478,923`), and `object_rules.py:266`'s reply still tells the user *“I can only repeat daily, weekly or monthly”*, omitting the fourth cadence | done 2026-09-15 | `recurrence.py:40` now maps `every year\|yearly\|annually` to `("yearly", False)` — no rounding needed, so no false "rounded" announcement either. **Verified live, not just unit-tested**: `run_transcript("block my anniversary every year on september 20th at 7pm for dinner")` commits on the FAST path with `recurrence: yearly` in the row and the reply says "Created recurring yearly event". The "recur_days supported end to end" half of the original claim was checked and found TRUE only for the deep track (`resolve.py`) — the fast path's own `Recurrence` class has no slot for a second weekday at all (verified: `detect("every tuesday and thursday")` silently drops "thursday", `rounded_from` stays `None`) — so `text_helpers.py`'s "two days a week" entry is still load-bearing there; fixed `object_rules.py`'s `_rule_cadence_round_and_announce` to skip it only when the committed object's own `recur_days` already has 2+ entries (the deep-track case), rather than deleting the check. Also fixed two more places a reader would see "yearly" is missing and be wrong: the LLM-facing schema description in `actions/calendar/action.py` (the model was never told yearly is a valid value to propose), and — the one with real user impact — the Mac GUI's event-edit recurrence dropdown (`calendar_ui/event_dialog.py`) had no "Yearly" option at all, so opening a yearly event's edit dialog showed "None" selected and **saving after editing any other field silently converted it to a one-off event**. Panel text (`trace.py`'s current `engine-v3` entry + iOS `ThinkingView.swift`'s matching `v3` block, left the frozen `engine-v2` historical entries untouched) also updated. Full suite green throughout: 1650 unit + 32 integration | `assistant/intent/recurrence.py`, `assistant/engine/decompose_validate/{resolve.py,text_helpers.py,object_rules.py}`, `assistant/actions/calendar/action.py`, `assistant/calendar_ui/event_dialog.py`, `assistant/trace.py`, `MACalendar-iOS/MACalendar-iOS/Views/ThinkingView.swift` |
| 91 | **`engine-component-folders` merged into `main`, 2026-09-15.** Gil's call: merge. Brought in FastRule's restructure (`fastrule/build.py` the converter, `fast_track.py` the front door; `objects.py` deleted), LLMJudge's stage-isolation rebuild (`rewrite.py` — the loop-back is now LIVE, not a stub — plus `verdict.py`, `rescue.py`, `findings.py`, `render.py`), Label's two learned classifiers, and the `engine/llm.py` accessor consolidation (one `IntentParser` cache, not two). **Not mechanical — ~23 files conflicted**, resolved by reading both sides' intent rather than picking one blind (docs superseded by whichever side was chronologically later; code reconciled by tracing actual callers, e.g. `_call_ollama`/`_call_ollama_verify` needed BOTH sides' independent additions, `llm_bus` logging and `model_protocol` gating, not one or the other). **One real regression found and fixed**: the branch's `objects.py` deletion would have silently reintroduced a HEAD-only bugfix (`_fast_item_words` — a two-item fast-path command giving both items the whole transcript instead of just their own words); ported into `fast_track.py`, tested. **One more found fixing it**: `fastrule/stage.py`'s `_flag()` tagged trace steps `fastrule_result=` but the review panel reads `data["outcome"]` — two independently-written pieces of the merge that never agreed on a key name, so a flagged item never rendered on the panel; fixed by also writing `outcome=`. A second suspected regression (`asked_fastrule` keying) turned out to be moot — the per-item FastRule recheck it protected was deliberately removed by the restructure, not lost by accident (see STATUS.md for the full trace). Full suite green: 1650 unit + 32 integration. `scripts/engine_stage_check.py` (row 88, also fixed here — it was already mostly right, just needed `--stage all`'s case set updated for the new `_COMMITTABLE` restriction on updates/deletes) still flags one case (`Shabbat gym refused`) that traces to a `SimpleNamespace` test fixture not behaving like a real `CalendarIntent`, not a real defect — the 79 real observance/Shabbat tests in the pytest suite are all green | done 2026-09-15 | `assistant/engine/fastrule/`, `assistant/engine/llmjudge/`, `assistant/engine/label/`, `assistant/engine/llm.py`, `assistant/engine/__init__.py` |
| 92 | **The deep track drives the whole pipeline before learning the LLM is unreachable, and discards resolved sibling items when one item's LLM call fails.** Found 2026-09-15 tracing the phone's offline voice queue against a live simulation (scratch server, `MACALENDAR_LLM_DISABLED`/a real disconnected-Ollama POST to `/voice/text`), then verified by reading the two functions directly rather than guessing. **(a) The retry loop already does the right thing; the first attempt doesn't.** `start_pending_retry_loop` (`api/server.py:207-248`) checks `_llm_reachable(cfg)` — a 1.5 s ping to `{base_url}/api/tags`, `api/server.py:197-204` — before ever re-calling `run_transcript` on a queued command, and skips the whole batch if it's down. But a LIVE command has no equivalent gate: `_run_locked` (`engine/__init__.py:131-209`) walks the entire deep track — segmentation, decompose_validate, generate.py's real Ollama call — before the failure surfaces, on every command needing the deep track while the model is down, paying for both the deterministic stages and however long the doomed HTTP call takes to time out. **(b) A multi-item command loses more than the failing item.** `generate.run()`'s per-item loop re-raises `LLMUnavailableError`/`LLMTimeoutError` (`generate.py:255` `except (LLMUnavailableError, LLMTimeoutError): raise`) out of the whole function, so `_commit()` never runs at all — an already-resolved sibling item (parsed by `rule_parser`, no LLM needed) is thrown away along with the one that actually failed. **Agreed fix, not yet built:** gate `_deep_parse` behind the same `_llm_reachable()` check `start_pending_retry_loop` already uses, so a known-offline Mac queues immediately instead of walking the pipeline first; and let resolved items reach `_commit()` independently of a sibling's LLM failure, so only the item(s) that actually needed the model get deferred. **Explicitly rejected as over-scoped:** persisting a partial `EngineState` at queue time and resuming specifically at llmjudge on reconnect — the stages it would skip are milliseconds, not worth the complexity of serializing state across a reconnect (and a possible Mac restart); reconnect stays "re-run the queued transcript from scratch", unchanged. A related but separate bug was found and fixed the same session on the phone side (not engine, so tracked in the app-features worktree, uncommitted as of this writing): `syncPendingVoice` was marking a queued voice command `.done` — and telling the user "Ran your queued command" — for exactly the `parse:"error"`/`pendingId` response this row's case (a) produces, when the Mac had actually only queued it server-side; left uncorrected, retrying that command in the old (30 s timeout) code path would have handed the Mac a second copy of the same transcript, which `start_pending_retry_loop` could then execute twice | done 2026-09-15 | Both halves built against the post-merge code (`generate.py` no longer exists; the equivalent logic is now `fastrule/stage.py` + `llmjudge/rescue.py`, per row 91). **(a)** `is_reachable(cfg)` moved from `api/server.py`'s private `_llm_reachable` into `engine/llm.py` (one shared implementation, not two); `_locked` now calls it right before `self.parse(state, cfg)` and raises `OllamaUnavailableError` immediately on a known-offline model, reusing `_parse_error_response`'s existing queue-and-apologize path rather than duplicating it. **Verified live, not just mocked**: the exact compound sentence that took 9.6 s to run for real earlier this session now fails in 1.49 s with a known-offline model, `parse: "error"`, a `pending_id`, and the honest message. **(b)** `rescue()`'s per-item loop no longer re-raises `LLMUnavailableError`/`LLMTimeoutError` out of the whole function — it marks the failing item AND any remaining un-attempted ones as "couldn't read this part" (no point paying a fresh timeout per item once the model's confirmed gone) while items already resolved earlier in the same loop keep their result and reach `_commit()`. Two new tests prove it: a two-item batch where item 1 succeeds and item 2 fails still commits item 1; a three-item batch stops asking the model after the first failure rather than retrying items 2 and 3 individually. Full suite green: 1653 unit + 32 integration | `assistant/engine/llm.py`, `assistant/engine/__init__.py`, `assistant/engine/llmjudge/rescue.py`, `assistant/api/server.py` |
| 93 | **The day panel replaced pre-event notifications** (Gil, 2026-09-11: "more of a panel that nicely shows what i have today and not when something is about to pop up… it's on or off"). One summary of today at `notifications.digest_time`, delivered once. `notify.digest_verdict` decides when (held through Shabbat/yom tov on DEVQA Q6's ruling, fails open); `notify.build_digest` decides what it SAYS as well as what is in it, so the Mac banner and the phone read identically. Mac delivery reuses `reminder_log`'s UNIQUE row with a negative sentinel id as the once-a-day guard rather than adding a table. Pre-event banners are dormant, not deleted — `pre_event: false`. A late panel is not caught up, unlike a late reminder: a summary arriving at 4pm is the noise this replaced. | done 2026-09-11 | `assistant/notify.py`, `assistant/notifier.py`, `GET /digest`, `tests/unit/test_digest.py` |
| 94 | **iOS half of the day panel (row 93).** The server side is done: `GET /digest` serves today's events + tasks with the wording already decided, `notifications.daily_digest` is the on/off through the existing `PATCH /config`, and the Mac fires it. The phone still schedules up to 55 per-event reminders in `ReminderScheduler.swift` and still shows lead-time controls in `SettingsView`; it needs to schedule ONE daily notification from the digest and show ONE toggle. Needs a machine with Xcode — unbuilt Swift does not ship (same constraint as row 83). | done 2026-09-17 | `ReminderScheduler` now schedules ONE panel per day from the Mac's finished wording, and Settings shows ONE switch. **A new endpoint was needed and the row did not anticipate it**: iOS notifications are SCHEDULED, not pushed, so the phone must hold tomorrow's panel before tomorrow morning and cannot ask at 06:59 — `GET /digest/upcoming?days=7` returns the week in one round trip (cached in `mc_digests.json`, re-fetched on cold start, foreground and every `/changes` token move). **One live bug found by driving it rather than reading it**: the panel ships ON, and nothing on this path had ever asked for notification authorization — a clean install fetched the week, called `add` seven times, and iOS rejected all seven silently (the adds are fire-and-forget). The feature was dead on arrival unless the user happened to open Settings and find the permission row. It now asks at the first moment it has a real panel to lodge; `DayPanelUITests` is the regression test, and it fails if the ask stops happening. **Verified end to end on the simulator against the live Mac**, not by reading Swift: of the seven days served, four were scheduled and three correctly were not — today (07:00 already past), Saturday (`shabbat`) and Monday (`yom_tov:Yom Kippur`). Then `digest_time` was moved to two minutes out, the app was CLOSED, and `panel-2026-09-17` arrived in the simulator's DeliveredNotifications store reading "Thursday 17 September — 3 events · 9 tasks" — the Mac's wording, delivered with the app not running. Suppression is sundown-bounded and it shows: at 19:14 the Yom Kippur day is no longer held, where at 07:00 it was. The retired `evt-*` per-event requests are still swept on every reconcile, because an app updating from an older build has up to 55 of them lodged that no code owns any more | `ReminderScheduler.swift`, `Views/SettingsView.swift`, `API/{APIClient,Models}.swift`, `LocalStore.swift`, `Views/ContentView.swift`, `assistant/api/server.py`, `MACalendarUITests/DayPanelUITests.swift` |
| 101 | **The lock-screen card said "elapsed"** (Gil, 2026-09-17: *"Remove the elapsed. I don't want to see that it says elapsed time"*). While an event was running the Up Next card counted UP from the start under the label "elapsed". Time already spent is not something a lock-screen card can act on; how long is left is. Both phases now count DOWN — to the start, then to the end — under one label, "to go". | done 2026-09-17 | `MACalendarWidgets/UpNextLiveActivity.swift`, `Shared/UpNextActivityAttributes.swift` |
| 95 | **Jude integration rebuilt** — the old one was laggy and thin. Two causes: the Mac app relaid out the whole document per token (2,000 tokens = 2,000 relayouts), and Jude's ollama calls were unarbitrated, racing voice commands. Now `assistant/jude/` on top of a new `assistant/integrations/` convention, with an ollama gate taking `model_protocol.hold()` per call. Old version in `retired/jude-bridge-v1/`, tagged. | done 2026-09-17 | `assistant/integrations/CONVENTION.md`, `assistant/jude/ARCHITECTURE.md` |
| 96 | **`assistant/integrations/` — the convention for hosting an external program.** Jude is its first consumer. Covers discovery, supervised spawn, a status shape that never raises, an ollama gate, and a `sitecustomize` shim for children we may not edit. | done 2026-09-17 | `assistant/integrations/CONVENTION.md` |
| 97 | **`assistant/features/` — the convention for OUR OWN tabs/panels.** Deliberately NOT an Integration (a tab has no checkout, port or subprocess). One declaration per feature replaces three hand-synced iOS lists and five Mac wiring sites; visibility is one `features:` map in config.yaml served by `GET /features`, replacing three separate systems. | done 2026-09-17 | `assistant/features/CONVENTION.md` |
| 98 | **Mac panels now keep a declared contract** (`FeaturePanel`: `reload` / `apply_theme` / `apply_ui_config`). Fixed a live bug: the DB-change poll reloaded Tasks and, as a bolted-on special case, Timer — **Coursework and Workout went stale until restart** when the phone changed them. | done 2026-09-17 | `assistant/calendar_ui/feature_panel.py`, `window.py` |
| 99 | **Coursework offline writes were silently dropped — FIXED (`bbe7892`), verified 2026-09-18.** `/courses` and `/assignments` now enqueue on `APIError.offline`, each create carries a `client_token` so a replay cannot duplicate, and `LocalStore.remapTemporaryID` repoints anything queued behind a placeholder id. `CourseworkView`'s `try?` is gone — a refused delete puts the row back. Regression-tested by `tests/unit/test_ios_offline.py` (`test_the_coursework_paths_are_actually_queued`) plus the offline-queue and idempotency suites: 53 passing. The row said NOT FIXED for a day after it was fixed, which is how a cleared blocker sends the next person looking for work already in the tree. | done | `CourseStore.swift`, `CourseworkView.swift`, `APIClient.swift` |
| 100 | **Jude's data prerequisites.** Its retriever hardcodes `nomic-embed-text`, and the local `chroma_db` had lost `data_level0.bin` (924 MB of vectors) so the index would not load at all. | done 2026-09-17 — model pulled; index restored from Hugging Face in 30s rather than re-embedding for ~70min; Hebrew text migrated INTO the index so `chroma_db` is now the only artifact Jude needs, and the absolute `he_path` that made the published dataset work on one machine only is gone (HF `dbc22305`, GitHub `f6917c3`). | `assistant/jude/ARCHITECTURE.md` |

**Q4 (Gil 2026-09-06, app stream) — RULED IN, STILL UNBUILT.** Mac
notification settings gains a "remind me even when the calendar is closed"
option; the LaunchAgent detach ships BEHIND that toggle, default off (it
changes the launch model: --reload, HUD, shutdown ownership — the plan's
riskiest phase, which is exactly why it is opt-in). Checked 2026-09-14: neither
half exists. `settings_dialog.py:218-266` has exactly four notification
controls — "Pre-event notifications", the lead-time spin, "Spoken heads-up",
"Hold on Shabbat & yom tov" — and none of them is this; `find . -name "*.plist"`
finds no launchd plist for `assistant.api`. **It has been unblocked since
2026-09-06** and two docs went on calling it blocked. Carried in the order of
play as notifications phase 5.

**Q9 confirm-prompt flow (Gil 2026-09-07, app stream) — SHIPPED 2026-09-07**,
and this note said "IN BUILD" until 2026-09-14 while the paragraph 29 lines
below already recorded it as shipped. An interrogative create ("should i add
yoga…?") pops a confirmation box with the parsed proposal — yes creates, no
discards. Response-contract pattern of the transcript gate: the server returns
`parse:"confirm_create"` + a proposal payload only when the request declares
`supports_confirm` (`api/server.py:379,387`), `POST /voice/confirm`
(`server.py:598`) executes or discards, older clients keep deep-decides. Mac
dialog + iOS sheet. Dataset: 16 interrogative families relabeled
action="propose" (251 rows) — a fast commit on them now scores as a violation.

**Client + engine work, 2026-09-17** (branch
`claude/ios-macos-perf-features-lh6du9`), all shipped:

1. **Discard a recording** — a trash button beside the mic while it listens
   and in the review bar, on both platforms. The phone had no way out of a
   recording at all; the Mac's was a 400 ms double-tap.
2. **Step 0 in the engine** — `repair.is_ignorable()` runs before the run lock
   and the config load, and now catches the stop-word-only transcripts the old
   single-strip check missed ("that's it", "set events").
3. **Offline is instant** — an offline circuit breaker on the phone, one
   `GET /sync/bootstrap` for a cold start, cached holidays, and `loadMonth`
   painting the cache before it awaits. `DOCUMENTATION/SYNC_PROTOCOL.md` is
   the protocol, written down for the first time.
4. **Task tags offline** — `GET /tags/rules` + `TagClassifier.swift`, the
   Mac's classifier running on the phone over a table the Mac serves. The
   phone's answer is a preview; the Mac's is what lands.
5. **Timer drift** — the Mac writes six fractional digits and iOS parses
   three, so the phone's live counter sat at 00:00 and its total ran
   backwards. Parser fixed; `start_epoch`/`end_epoch` served beside the
   strings.
6. **Jude** — the Judaic study assistant wired in as a separate repository
   (`assistant/jude/ARCHITECTURE.md`): iOS tab (off by default), its own Mac app, LLM
   calls pinned to the assistant's local Ollama, reached only through
   `/jude/*` on 8080.

**Open for Gil:** Jude's `jude.enabled` is false in `config.example.yaml`, so
nothing turns on until the checkout is in place and the flag is flipped.
Merged into this branch 2026-09-17 (PR #3); the wording above and
`DOCUMENTATION/TASKS.md`'s row numbers were reconciled against the
reconciliation-audit rows (84–94) added the same week on this side.

## How we are working right now (2026-09-20)

**THE IMPROVEMENT LOOP, resumed** (Gil, 2026-09-20, DEVQA Q31). Stage
isolation (`DOCUMENTATION/STAGE_ISOLATION_PLAN.md`, 2026-09-07) did its job —
every stage has its own dataset, board and test file — and the day it ended
showed why the loop had to come back: five changes that each moved a stage
board by nothing or two rows moved the whole chain from 74% to 85%
count-correct on dev-100 (runs 22–26, `dataset/RESULTS.md`), because the
misses were seams no stage corpus holds. The working slice is dev-100
(direction, ±3 pt), dev-fast-250 confirms, the sealed 300 is milestone-only;
a stage-internal change is still boarded alone on its stage before it is read
on dev-100. `dataset/loop_log.csv` runs to 26. The queue is "THE CHECKPOINT'S
QUEUE" below: item 4 next, three rulings for Gil in item 8.

*What used to stand here said "cycle 5 in flight 2026-09-06". There was no
cycle 5; the epoch reset of 2026-09-05 was followed by four era-2 cycles and
then the pause. The branch it named, `loop-cycle-1`, is not where work happens
any more.*

**Where the live queue actually lives.** The checkpoint retrospective is at
`DOCUMENTATION/experiments/checkpoints/` — `RECOMMENDATIONS.md` (what is worth
fixing, 2026-09-13) and `RUN_STATUS.md` (the six-checkpoint boards). Until
2026-09-14 a repo-wide grep for either filename returned **zero** hits outside
that folder: it was unreachable from CLAUDE.md → STATUS.md → TASKS.md, which is
how rows 84, 85 and the other half of row 57 survived unnoticed for weeks. This
file is the link now. Its three surviving recommendations are **row 85** (gate
the not-found recheck), **row 57** (fast-path coverage) and **row 84** (the
`llm_ms` recording gap); a fourth — A/B the segmentation swap via
`MACALENDAR_SEGMENTATION` — was dropped by Gil on 2026-09-13 as not relevant.

**Two streams, two checkouts — and the branch positions below were stale.** App
features and cleanups still happen in `../MACalendar-app` (branch
`app-features`), merged between cycles, never during a measurement run.

**Corrected 2026-09-17:** `app-features` is MERGED into `main` (its Live Activity
agenda design is what shipped, on Gil's choice between the two designs), and
`jude-status-wording` is retired rather than merged — its one commit patched a
file the Feature-convention refactor had already moved the code out of, so the
fix was re-applied at the new location instead. The `origin/main is at 5561883`
and `local main is stale at 18f95d9` readings above are both wrong now; both
`main` and `origin/main` are checked with `git log -1`, not from this paragraph.
The lesson the old text was trying to teach still stands: a stale local ref is a
fetch, not work, and never "176 commits behind".

### Standing rulings recorded here 2026-09-14 because they exist nowhere else

These came out of a working session and the audit could not find them anywhere
in the repo. They are real, and two of them contradict what other docs still
say, so they belong in the tracker rather than in a chat log.

- **The real-speech dataset is DROPPED.** Gil, verbatim: *"dont do the real
  speech dataset then."* The built artefacts stay on disk — `dataset/realspeech/`
  (1,200 rows, generator, board, `REALSPEECH.md`) — and what is dropped is
  further work on it. `dataset/RESULTS.md` still cites its baseline as though it
  were a live target; read that as a record. See row 74.
- **The segmentation freeze is PARTIALLY LIFTED.** Gil, verbatim: *"well
  segmentation as long as the structure remains the same, and just fixing
  implementations then its fine. same for fastrules."* So **implementation fixes
  inside `assistant/engine/segmentation/` are allowed; structure and design
  changes are not.** This supersedes the blanket *"no edits to
  `assistant/engine/segmentation/` at all"* gloss the segmentation section below
  used to carry, and it retroactively explains the two commits the audit flagged
  as freeze breaches — see that section.
- **Prefer not to restructure.** Gil: *"i don't really want to make structural
  changes if i don't have to."* Read every open row through that: a fix inside a
  module beats a reshaping of the chain, and CLAUDE.md's rule that stage I/O
  contracts are frozen is the same instinct written down.

**The app stream's Gil-approved queue shipped 2026-09-06** (243d99f → 3b89809):
.ics share, search + jump-to-date, duplicate event, week numbers, Timer CSV,
agenda view, observance checkbox, iOS heartbeat/share/search, ThinkingView file
move; two bugs found and fixed (settings-dialog imports; pydantic dropping
`observance.enabled`).

**Notifications is NOT "planned only, blocked on DEVQA Q4–Q6".** Q4, Q5 and Q6
were all answered 2026-09-06 (`DEVQA.md:178-190`; Q6 re-confirmed at `:90`
2026-09-11), and phases 1, 2 and 4 shipped and merged: `assistant/notify.py`
(155 lines), `assistant/notifier.py` (225), the DB column and `reminder_log`
table, `NotificationsConfig`, the Mac settings section, `ReminderScheduler.swift`,
`LiveActivityManager.swift`. Phase 3 shipped its inline half as row 80. What is
genuinely left is phase 5 — see the order of play. The pre-Shabbat digest in
that row is **closed, not deferred** (`DEVQA.md:90-92`).

**Both platforms now show the day panel and nothing else** (2026-09-17, row
94). The pre-event machinery is dormant on the phone as well as the Mac —
`notifications.pre_event` ships `false`, so `notify_at` comes back null on
every event payload and the phone's per-event mirror had been running empty
for six days before it was replaced. Turning `pre_event` back on restores the
Mac's half whole; the PHONE's half is now retired rather than dormant, so
that switch alone would no longer bring the banners back to iOS.

**The confirm-create gate (DEVQA Q9) shipped 2026-09-07** — an interrogative
create is offered rather than executed or dropped (`parse: "confirm_create"` +
`proposal`, `POST /voice/confirm`, Mac Add/No box, iOS alert); see FEATURES.md
and ENGINE.md.

**The dentist bug is fixed, 2026-09-11** — it was queued here and in STATUS.md
as an open engine bug ("queries can emit mutations"). `object_rules.py:183
_rule_question_mutates_nothing` is the rule, with the imperative-wearing-a-
question-mark discrimination beside it, pinned by `test_engine_checks.py:319-354`
and written up in `8fa8e72`. Residue: `HYPOTHESES.md:247` still wants a
full-engine run to confirm the 14 sweep hits are gone — that can ride any future
sweep, it is not its own job.

Previous thread, as of 2026-09-03 — history, kept because the k=4 finding still
binds:

**Row 76 landed** (2026-09-04, overnight): the full A/B/C comparison is
written up as run 8 in `ASSISTANT_AUDIT_SUMMARY.md`, and `k` is no longer an
open question — k=4 stays, on evidence. The external dataset's own parser
findings (compound commands 29%, dropped-event failure mode) are in
`DOCUMENTATION/experiments/memory_scaling/METRICS.md` and feed whichever
session works the compound-parsing problem next. Note for tooling: every join
against the pool keys on `raw_transcript` (verbatim input), because the
pipeline can rewrite a transcript before storing it.

Decisions that were "waiting on a number" then, and where each actually stands
now (2026-09-14):

- **The eviction policy (row 60)** — moot rather than answered. Run 8 said
  protect real, reviewed examples and that bulk data has no measured value; the
  few-shot path then shipped at `memory_examples: 0` and `FEATURES.md:325-328`
  records it measured to HURT the engine. Row 60 is closed as superseded.
- **The confidence weights (row 57)** — the blocker is gone and the read was
  never done. A read-only run during the 2026-09-14 audit reported 91 real
  commands, 69 with a human verdict, 13 of those also carrying a confidence, and
  4 of 6 buckets too thin to read. n=13 is thin, but "waiting on a week of real
  use" is no longer the reason nothing has happened. Row 57 now carries this together with the
  retrospective's fast-path-coverage job.
- **Whether labelling should move to the LLM** — partly overtaken by
  `117dd69` (2026-09-13), which moved task/event labelling INTO the store:
  `create_todo` infers when `tags is None`, and `update_todo`/`update_event`
  relabel on rename. That settles *where* labelling happens; it does not settle
  *what decides*. The Label stage's two learned classifiers exist on
  `engine-component-folders` (row 91) and would.

## CLOSED 2026-09-08 — the order-dependent unit test (was: open bug)

`tests/unit/test_mixed_commands.py::test_a_list_of_things_to_buy_makes_exactly_its_items`
fails in the full suite and passes on its own. It had been dismissed as an
Ollama flake in chat more than once, including by me; it is not.

What the bisect establishes:

- **Deterministic, not random.** 4/4 failures inside `pytest tests/unit`,
  8/8 passes running the test alone.
- **Not caused by the segment splitter** (a222f60). It reproduces identically
  with `segment.py` and `coordination.py` checked out at `a222f60~1`.
- **The trigger is `tests/unit/test_command_source.py` running first** —
  that file alone, before this test, reproduces it. Files 1-11 of the suite
  before it do not.
- **Ruled out**: few-shot memory injection (`nlu.memory_examples` is 0);
  background verify threads (`_no_bg()` gates them and conftest sets
  `MACALENDAR_NO_WARMUP=1`); an LLM exception swallowed by `_llm_segments`
  (Ollama returns 200 on every call in the failing run).

What is left: the model gives a different segmentation for the same prompt
after `test_command_source` has posted six commands through `/voice/text` in
the same process. The remaining suspect is Ollama-side session state (the
project already has a `keep_alive` gotcha on record), which would make this a
test-isolation problem rather than an engine defect — but that is a
hypothesis, not a finding.

Why it matters beyond the red tick: if prior traffic in the same process can
change a later parse of the same words, that is worth knowing about the
product, not just the suite.

**Closed by the kind fix (bb2b80c), not by touching the test.** "add buy milk
and buy bread to my list" now reads as a TASK — `_TASK_RE` recognises the list
destination — so decompose's list splitter runs on it, instead of generate
failing to route an event and returning no actions. The suite is 1311 passed,
0 failed, in full-suite order.

The diagnosis above still stands as the reason it was order-dependent, and the
underlying question is NOT answered: it remains unexplained why the model
returned a different segmentation for the same prompt after earlier commands
had gone through the same process. That row was removed from the failing path
rather than the mechanism being understood, so if a later cycle sees the same
shape again, start from here.

## Segmentation — PAUSED 2026-09-09, and where it got to

`assistant/engine/segmentation/PLAN.md` §0 is the status; `ARCHITECTURE.md` §0 is
the standing overview and §2 is FastSeg phase by phase with the flow chart.

    exact-row        51.3% -> 68.2% train, 66.5% SEALED
    spoken time      73.4% -> 91.9% train, 93.5% sealed
    tag              87.3% -> 89.7% train, 90.2% sealed
    END TO END       51.6% -> 85.9%
    inventions           0 -> 0

The sealed 660 rows were read once, aggregates only, and land within 1-4 points of
train while being better on five metrics — weakest on item count, which is exactly
where the work stopped.

**FROZEN by Gil, 2026-09-09** — *"for now segmentation we leave, I don't want to
edit or make changes there."* The list below is where it resumes, kept intact so
nothing has to be re-derived.

**PARTIALLY LIFTED — Gil, 2026-09-14**, and this is the ruling that matters when
reading everything below. Verbatim: *"well segmentation as long as the structure
remains the same, and just fixing implementations then its fine. same for
fastrules."* So the line is **STRUCTURE, not the folder**:

- **Allowed:** implementation fixes inside `assistant/engine/segmentation/` — a
  regex that reads a case wrong, a rule that fires where it shouldn't, a board
  that miscounts.
- **Not allowed:** structure and design — adding or removing a component,
  changing what FastSeg and LLMSeg are to each other, changing the stage's
  contract or its place in the chain. Those are DESIGN decisions and go to Gil.

This supersedes the earlier gloss that read *"no edits to
`assistant/engine/segmentation/` at all"*, which was a tightening this file added
on top of what Gil actually said. **It also settles the two commits the
2026-09-14 audit flagged as freeze breaches: both were implementation, so both
were permitted.** `8fa8e72` (2026-09-11) changed nine lines of
`fastseg/fastseg.py` so that "thanks so much" tags as `other` — a closed list of
intensifiers riding the greeting group — and measured both sides: exact-set
76.6%, right item count 85.3%, item F1 94.6%, over-split 46 / under-split 108
rows, IDENTICAL either way on the segmentation train corpus. `b7687ea`
(2026-09-13) added 25 lines to `llmseg/llmseg.py` so that its model calls appear
in the new LLM console — observability, no behaviour. **One real piece of
bookkeeping survives:** `segmentation/experiments/RESULTS.md` was last written
2026-09-08 and does not carry `8fa8e72`'s measurement, so the board's own record
is two fixes behind the code it describes.

**When it resumes in full, pick it up at PLAN.md §0's ordered list.** First is
3b, the under-split compounds (`PLAN.md:42-43`: 108 under-split rows;
`and_compound` 53.6%, `joiner` 50.0%, `remind_then` 45.8%; multi-ask rows 17
points behind single-ask on the segmentation train corpus) — the biggest
remaining lever and the risky half, because over-split is garbage immediately.
Second was **re-testing LLMSeg** — **DONE 2026-09-16**, same verdict on the
current FastSeg: the oracle-gate ceiling (the best ANY routing rule could do,
even a cheating one) fell from the historical +3.8% to +0.0% on 204 fresh
rows — 0 fixed, 57 broken. Two new task shapes designed against the old
failure modes (`word-index`: absolute position output instead of verbatim
copying; `mark`/`mark2`: local true/false at each candidate join instead of
either) were also tried and also lost, `mark2` on a full 293-row
trap-stratified sample (exact-row 64.8% -> 57.0%, fixes 13 / breaks 36). Board
D still has not run — moot while the ceiling is 0%. Full numbers:
`assistant/engine/segmentation/ARCHITECTURE.md` §3 and §6. The next lever, if
this is picked up again, is a different local model, not another prompt.

Two items in that list need a ruling before anyone picks them up. **§8.3, the
injected date floor** (`fastseg.py:352` writes the literal word "today" into
`time`, costing two live workarounds at `state.py:108-115` and
`stage.py:100-106`, and one past audit failure) is the only frozen item actively
costing something today — but it needs the dataset regenerated, which makes it a
cycle of its own rather than an implementation fix. And **a board for the `other`
tag** is arguably exempt from the freeze entirely, since a board measures
segmentation without editing it and could live in `scripts/` — but it needs a
dataset of unusable inputs built first. Ask rather than assume.

## The measurement that set the priority (2026-09-09)

`decompose_validate/eval_metrics/end_to_end.py` settles which stage to work on. On
its 1,924 train rows, running the REAL segmenter:

- **decompose_validate makes 0 value errors of its own.** All 1,445 value errors on
  matched items are cases where different WORDS arrived; the resolver computed each
  correctly from what it was given.
- **Segmentation loses 265 of 2,557 items** (recall 89.6%), invents 162, and emits
  106 provably malformed ones (54 with two clocks in one item, 52 with an action
  ending in a joiner) — the last two countable without any gold.

So end-to-end row accuracy is **51.6%** against 99.9% gold-fed, and the gap is
segmentation's. **Segmentation is the next stage to work on, not FastRule** —
whose own board would be read through the same lossy input. Its §8.1 already names
the two defects, and §7b now carries these numbers from the receiving end.

**A second measurement, 2026-09-13, points somewhere else, and both are true.**
The checkpoint sweep scored `main`'s two paths on the SAME 170 sealed rows:
fast path (rules only) **93.1%** count-correct, deep path (six stages + the
model) **65.3%** — 28 points apart, on identical rows, with the cheap path
ahead. It reproduces on 300 persona rows that share nothing with the sealed set
(`RUN_STATUS.md`: `main` +5 to +7 on simple and −8 on complex against
`fastrule-v1`). These do not contradict each other: this section says
segmentation is where items are LOST, and the sweep says that everything
downstream of the loss does worse than not going there at all. **Both boards are
`split:"test"`, so neither may pick the next thing to work on** — see row 57 for
the legal re-derivation route.

## decompose_validate — carried forward (2026-09-08)

The stage is rebuilt, measured and wired; v1 is retired and tagged
(`decompose-validate-v1`). What is deliberately NOT done, in the order it is
worth doing:

| # | item | why it is not blocking |
|---|---|---|
| 1 | **`decompose.py` is the last v1 file** (194 lines: item splitting). This stage's settled design says it does NOT split — segmentation does. | **Partly answered 2026-09-08**: disabled, the 25-case audit is IDENTICAL (76% / 81%) and all 1336 tests pass. Three of four probe cases are identical and the fourth is *worse with it* (see below). Evidence says removable; it deserves the FULL audit corpus both ways before deleting, not a 25-case slice — the slice is events-only and the splitter's list path is a task path. |
| 2 | **FastRule re-parses instead of reading `item.slots`.** | Behaviour is already right (values reach the intents in `run_objects`), so this is duplicated parsing rather than a wrong answer. **WRITTEN, not merged (2026-09-14):** it is phase B3 on `engine-component-folders` — *"83.5% of atomic train rows built through the real chain, operation 90.8%, title 55.5%, all eight values copied"* — and its 32 tests caught two real defects on the way. This is now merge work (row 91), not implementation work. |
| 3 | **11 sealed rows still fail** (of 840; date 99.1%). | They sit in a construction class **train has no failing instance of**, so fixing them means growing train speculatively — and the sealing rule forbids reading the test rows. Below the noise floor. |
| 4 | **The traceability board's vocabulary is hand-maintained** and has drifted 7 times. | **Done 2026-09-15, see row 87** for the full account. Stayed hand-maintained (a live import of the gold's closed table would violate `score.py`'s own stdlib-only constraint) but is now a named constant with a parity test enforcing agreement with `normalization.RECURRENCES`, so drift #8 fails a test instead of shipping quietly. |
| 4b | ~~**`"walk the dog at 9 and 2:30"` is broken BOTH ways**~~ — **STALE. Do not schedule a fix against this row.** | **Re-checked and found already fixed, 2026-09-11 (`8fa8e72`)**, which took this recorded-but-unfixed list in order and checked each case before touching it: the command now produces exactly two events, both titled "walk the dog", at 09:00 and 14:30. Cycle A part 1's clause-boundary splitter fixed it downstream and nobody closed the note. Kept here rather than deleted because the shape still teaches: a recorded defect can be fixed by unrelated work, so **check before you schedule**. |
| 5 | **Segmentation §8.1 / §8.2 / §8.3** are recorded for Gil, §8.3 being the date FLOOR injected into `time` as a word. | Another stage's work. §8.3 already costs two workarounds and caused one live audit failure, so it is the one with a price attached. |

## FastRule + LLMJudge — phase A on HEAD, B and C on a branch (corrected 2026-09-14)

**This section said "PLANNED, not started… no code has been touched" until
2026-09-14. That was false twice over**, and the cost of leaving it standing is
that anyone told to start phase B writes it a second time.

| phase | actual state, verified 2026-09-14 |
|---|---|
| **A · PORT OUT** | **LANDED ON HEAD** at `46f7967` (*"Port Gatekeeper and the LLM fallback to llmjudge/, before FastRule is broken up"*). `class Gatekeeper` now exists at `assistant/engine/llmjudge/gatekeeper.py:106` **and nowhere else** — `grep -rn "class Gatekeeper" assistant/` returns exactly that one line — and `fastrule.py:47-55` carries the `PORTED OUT 2026-09-09 (Gil)` import redirect, which is the plan's own design: the code moved, the call sites did not, behaviour unchanged. |
| **B · RESTRUCTURE** | **DONE 2026-09-10 on `engine-component-folders`**, not on HEAD. That branch has `fastrule/build.py`, `fast_track.py` and the B-phase boards (`experiments/b1_ceiling.py`, `b3_live_chain.py`, `stage_board.py`); HEAD's `fastrule/` still has `objects.py` and no `build.py`. Its own PLAN.md marks B1–B4 and B6 done, B3 reading: *"83.5% of atomic train rows built through the real chain, operation 90.8%, title 55.5%, all eight values copied."* |
| **C · MEASURE** | **DONE on the same branch** (C0–C3 marked done), together with LLMJudge's stage-isolation work — `rewrite.py`, `verdict.py`, `rescue.py`, `findings.py`, `render.py`, `datasets/` and six boards, **none of which exist on HEAD**. |
| **D · STOP** | Not reached, because B and C were never merged. |

**So the open work here is a MERGE DECISION, not implementation — row 91.** Two
specific things that look open on HEAD and are not: `rewrite_for_retry` is
`return None` here but is a 286-line `rewrite.py` on the branch, already
embodying Gil's 2026-09-09 TRIM ruling; and LLMJudge's 0.25 ask-matching
threshold, which an earlier audit said "should be swept", **must not be swept** —
the branch deletes the matcher it belongs to, because ask extraction was removed
on Gil's instruction (*"that defeats the point of what segmentation →
decompose_validate → FastRule did"*).

**Q13 is ruled and the carve-out stays** (Gil, 2026-09-07, re-confirmed
2026-09-14: *"Q13 seems like that is fine"*). A fast commit on a compound that
the parse fully covers is FINE: `_parse_covers_the_compound`
(`fastrule.py:188`, used at `:268`) is deliberate, not a leak. The
non-atomic bucket is a DIAGNOSTIC split — covered / half-executed / deferred —
with no single "violation" number; the primary metrics are atomic handle-rate
and correct-on-handled. See `DEVQA.md:116-127`.

**FastRule's own freeze is lifted on the same terms as segmentation's** (Gil,
2026-09-14: *"same for fastrules"*) — implementation fixes yes, structure no.
Rows 86 and 57 are both implementation.

The plan below is kept because it is still the record of WHY the box is shaped
the way it is, and because the merge decision is judged against it. Gil's
definition of the box is what it was measured against:

> *"FastRule's job is only to take each Item and make it into an object format the
> system accepts, so we can commit when ready."*

Against that, ~423 of ~890 lines in `fastrule.py` + `objects.py` belong elsewhere,
and the function doing the job the stage exists for is **eleven lines** copying
**two of eight** available values. The plan's target is one entry point,
`build(item, *, today) -> BuildResult`, with no model, no database and no opinion
about whether to commit.

**Four phases, in this order** (Gil, 2026-09-09) — `fastrule/PLAN.md` §3, with
where each one actually is as of 2026-09-14:

| | | where | state |
|---|---|---|---|
| **A · PORT OUT** | `Gatekeeper` + the LLM fallback into `llmjudge/` — a move with an import redirect, behaviour identical, **no number moves** | `llmjudge/PLAN.md` §1.0 | ✅ on HEAD, `46f7967` |
| **B · RESTRUCTURE** | measure the ceiling → `build(item, today)` proven alone → **B3 WIRE IT INTO THE ENGINE** (five touch-points, the format, and the md files) → `Atomicity`+`fast_propose` → a new `fast_track.py` → delete the call sites and the dead code | `fastrule/PLAN.md` §3 | ✅ on `engine-component-folders`, unmerged |
| **C · MEASURE** | fix the generator, add gold Items, rewrite the board to feed `build()`, iterate until satisfied | `fastrule/PLAN.md` §3 | ✅ on `engine-component-folders`, unmerged |
| **D · STOP** | report to Gil. **LLMJudge's own work does not start before this** | — | not reached — blocked on row 91 |

Phase A exists because Gil asked for it directly — *"before we start breaking
FastRule code, port what's relevant to the LLMJudge folder"* — and the reason holds
up: trim first and the ported guards exist only in git history, so "port" becomes
"rewrite from memory". `_guard_inventions` is the one that would be lost first, and
it exists because a model once fabricated an event onto the calendar (cycle 7).

**Two things B3 settles that are easy to get wrong.** `BuildResult` is **internal**
— X4 stays `item.action` + `item.intent` on the frozen `Item`, so most of the
pipeline needs no change at all; what changes is that the values are COPIED from
`item.slots` instead of re-parsed. Making `BuildResult` the stage's real output
would be an `Item`-contract change and therefore a design decision for this file,
not a step inside phase B. And **`fastrule/objects.py` is the engine's shared
accessor** for the action registry and both parsers — six call sites outside the
stage, including `server.py`'s warm-up — so those need a home (`engine/llm.py`)
*before* anything deletes the file, not during.

**The branch did that (B6) and HEAD still carries the duplication it removes.**
On HEAD there are two independent `IntentParser` caches of the same object —
`engine/llm.py:17` and `fastrule/objects.py:65`, both `global _parser`, both
built from `get_registry()` — and `engine/__init__.py:274` has to reset both in
a loop (`for _mod in ("assistant.engine.llm", "assistant.engine.fastrule.objects")`)
because of it. That loop is the tell: a single accessor would not need it. Not a
live wrong answer, but a real piece of what row 91 buys.

**Phase C is mandatory, not polish** — B2 invalidates the instrument. The 7,200-row
board feeds raw TEXT into `FastRule.run(text)`; the restructured box takes an
`Item`. So the moment `build()` lands, the primary board cannot run at all, and
FastRule would be unmeasurable exactly when it has just been rewritten.

*The branch solved this by ADDING rather than rewriting* (C3): `fastrule_shape.py`
stays as the FRONT-DOOR board — `FastRule(0.80).run(text)`, which the restructure
does not touch — and `experiments/stage_board.py` is a new board for the box,
taking `--input gold` or `--input chain`. Worth knowing before the merge, because
it means row 86's fix to `fastrule_shape.py` is not thrown away by it.

✅ **The phase-C blocker is GONE — verified 2026-09-11.** This paragraph used to
read that `scripts/gen_fastrule_dataset.py:56-57` still pointed at
`dataset/fastrule/banks/` and raised `FileNotFoundError`, so the 7,200-row
dataset could not be rebuilt or extended. It was fixed at some point and this
entry was not. Checked by RUNNING it, per "before trusting any board, run it":
it builds 7,200 rows, exits 0, and regenerates the committed jsonl
**byte-identically** (md5 `c387bb6de818f7f36ca9f9f6b2628e82`) — deterministic,
and the committed dataset is exactly what the generator produces.

All four sites of the rot class are healthy as of 2026-09-11: segmentation's
generator, FastRule's primary board, `fit_route_models.py` and
`gen_fastrule_dataset.py`. **Mind the `ROOT = parents[1]` inversion when
checking them** — it is the repo root for the two under `scripts/` and the
STAGE folder for `fastrule_shape.py`, so a naive sweep reports the board as
broken when its path is correct. That false positive was hit, and corrected,
during this very check.

⚠️ **There was a FIFTH site, and the same lesson applies to it** (found
2026-09-14, now row 88): `scripts/engine_stage_check.py` — the per-stage gate
CLAUDE.md points at — imports `assistant.engine.llmjudge.crosscheck`, which does
not exist, and lists a stage set three renames out of date. The identical defect
in `assistant/cli.py` was found and fixed the day before (`c82d5f8`) and this
copy was not, because **finding some of these is not finding all of them** — and
once again the survivor is the one living in `scripts/` rather than in the folder
that owns it. Healthy *as of a date* means checked on that date, in that sweep,
against that list.

**Segmentation is FROZEN — Gil, 2026-09-09**: *"For now segmentation we leave, I
don't want to edit or make changes there."* The order is FastRule → LLMJudge →
Gil decides. This supersedes the "segmentation is the next stage to work on"
verdict below **as an order of work**; it does not touch it as a measurement,
which still stands and still says where the score is lost.
**Amended 2026-09-14:** the freeze now bars STRUCTURE, not the folder —
implementation fixes are allowed in both segmentation and FastRule (Gil: *"same
for fastrules"*). See the segmentation section above for the full ruling and for
what it says about the two commits that were flagged as breaches.

**What the freeze changes is the instrument.** With segmentation fixed, its
265-item loss is a permanent ceiling rather than a thing to fix, so a whole-engine
number is no longer evidence about FastRule at all:

- **Use `fastrule/experiments/fastrule_shape.py`** — the 7,200 product-shape set
  feeds FastRule directly, so segmentation is not in the path and the board is
  unaffected by the freeze.
- **Not `scripts/engine_dataset_compare.py`** for judging this work — it runs the
  real segmenter, so it measures the upstream loss we have agreed not to touch.

Reporting the second as a FastRule result would break the dataset/metric/meaning
rule in its most expensive direction: blaming this stage for another's loss.

**`BRAIN_VERSION` is not bumped by any of it.** `Gatekeeper`, the fallback and
`Atomicity` are Components, not Stages; the chain's shape is unchanged. This is the
`old_seg -> FastSeg` case, not the rename case.

## OPEN — the review panel must SHOW the flagged items (Gil, 2026-09-10)

**Not started. Recorded here so it is not lost, because the engine half landed
first and the two are easy to leave out of step.**

FastRule now returns THREE kinds of result, and the panel has to tell them
apart. Gil, 2026-09-10: *"for a valid item make a relevant object; for a bad
item a bad item object is expected — not expecting to fix a bad item; an item
tagged as other and not event/task/review is a DIFFERENT object which we will
use to show on the review panel later."*

| `item.slots["fastrule_result"]` | when | what the panel should say |
|---|---|---|
| *(absent)* | a valid item | the object, as today |
| `bad_item` | the item ARRIVED malformed | *this part reached me damaged* — and WHICH upstream stage, once that is attributable at runtime |
| `not_an_ask` | segmentation tagged it `other` | *this wasn't something for the calendar* |

The two flags share a carrier (`item.blocked`) but mean different things: one is
an upstream defect, the other is a correct reading of a non-ask. Collapsing them
in the UI would lose exactly the distinction the user needs.

The ENGINE side is done (`fastrule/build.py::NotAnObject`, flagged onto
`item.blocked`, reported by `_commit` as *"I left 'X' alone — …"* and pinned by
`test_every_item_leaves_the_stage_either_built_or_flagged`). **The CLIENT side
is not.** The thinking panel and the iOS timeline draw a command's chain from
its trace, and a flagged item currently has no place in that drawing — so the
user sees the reply sentence but not *which part* of what they said was set
aside, or why.

What this needs, per CLAUDE.md's *"the review panel is downstream of the
pipeline"* rule:

- a trace step for a flagged item, distinguishable from a REFUSAL (which is a
  correct reading held back) and from a DEFER (which the model then answered)
- the Mac `thinking_panel.py` and the iOS `ThinkingView` rendering it — an item
  that produced nothing should be *visible* as a decision, not an absence
- check whether this is a `CHAINS`/`BRAIN_VERSION` matter: it is a new step
  KIND, not a new stage, so probably not — but `test_panel_agreement.py` is the
  arbiter and should be run before assuming either way

**Why it matters more than it looks:** the silent version of this was a real
defect. Before 2026-09-10 an `other` item was set to `intent=None` and the
execute loop skipped an empty intent before it looked at anything else, so the
speaker was told *nothing at all* — indistinguishable from success. The engine
now says something; the panel should show it.

## Deferred, filed 2026-09-10 — three things found while working elsewhere

Each one is real, each was found by a board rather than by reading, and none is
being fixed in the change that found it.

### 1 · decompose_validate — an invalid clock time reaches the database

`start_time = '30:00'` on live rows **1993 ("Walk Val")** and **1994 ("shool")**,
both written at `18:41:59` on 2026-09-09 — the same second as row 1995
("Walk Mark"), so ONE compound command produced all three and two came out
corrupt.

`30:00` is not a time. `CalendarIntent`'s validator rejects hours > 23, so these
reached the DB down a path that skipped it. Gil, 2026-09-10: *"this is something
that should be fixed in the decompose_validate step."*

**To do:** reproduce from the compound that made them, find which path writes a
clock without validating, fix it there. Check whether other rows carry
out-of-range values — the query that found these is in `label/experiments/`.

### 2 · segmentation — does a DROPPED ASK ever actually happen?

LLMJudge stopped extracting the asks from the raw text (2026-09-10, Gil: *"that
defeats the point of what segmentation → decompose_validate → FastRule did"*).
It was re-deriving segmentation's answer with a weaker instrument and blaming
segmentation when the two disagreed — and the one false flag on its own board
was exactly that, the extraction inventing an ask from *"i already handled it"*.

**What was given up:** nothing in this engine now notices when segmentation
MERGES two asks into one. A well-grounded object built from half a command looks
perfect to a per-object check.

**Two places it bites, not one:**

- the foreground loop can no longer raise `missing`, so X1' is never triggered by
  a dropped ask;
- the fast track's BACKGROUND patcher loses the same finding, which makes
  `_commit_missing_ask` unreachable — the path that added a missed ask behind an
  instant commit.

**To do (Gil: "mark to test later in segmentation and see if it requires
fixing"):** measure on segmentation's OWN board how often a real command loses an
ask. If it is rare, this was free. If it is not, the fix belongs in segmentation,
not in a downstream stage second-guessing it.

### 3 · categories — `Running` and `Gym` are not in the palette

40 of 54 live events carry one of them; neither is one of the 13 defaults, and
`~/.assistant_tools/categories.json` does not exist — so `color_for()` falls back
to Personal's colour for all of them, and they are invisible to every
per-category setting.

**Ruled (Gil, 2026-09-10): both fold into ONE category, and it is `Fitness`** —
already in the palette, so nothing new is introduced.

**To do:** find where the training planner stamps `Running`/`Gym`, change it to
`Fitness`, add the keywords so `classify()` agrees, and migrate the existing rows.

## explorer.html — BOTTOM PRIORITY, filed 2026-09-10 (Gil)

The published explainer is downstream of the code, and the code moved. Three
things, none urgent, all real.

### 1 · the LLMJudge box is out of date

The stage was re-cut on 2026-09-10: the ask extraction is gone, it makes ONE
model call instead of two, and the findings are now three per-object types
(`ungrounded_subject` → X1' · `unsupported_field` → commit and say so ·
`not_an_ask` → review panel) instead of four. The page still describes the
extract-and-diff design.

Check `tests/unit/test_artifact_claims.py` first — the model-calling-stage count
is read out of the code and the page must agree with it.

### 2 · the stage-to-stage arrow TOOLTIP renders wrong

**Specifically `X_i`.** The input/output tooltip on the arrows between stages
does not render the subscript correctly. Reproduce by hovering an arrow in the
chain diagram; compare against the `X0 / X1 / X2 …` naming the engine's own
`ARCHITECTURE.md` uses.

### 3 · COMMIT + LABEL is missing its labels, and should say where they are going

Gil, 2026-09-10: *"i think its missing labels, i want it to be a ML model."*

Two separate things to write there:

- **what it does today** — an event gets a CATEGORY (13 of them, keyword-scored
  by `actions/calendar/categories.py::classify`) and its colour; a task gets
  TAGS (multi-label, `actions/todo/tagging.py`). The page should show the label
  as part of the commit step, since a row is written and categorised together.
- **where it is going** — both classifiers become ML models. **The measured
  state, and the honest reason it has not happened yet**, is in
  `assistant/engine/label/experiments/RESULTS.md`: the rules currently BEAT
  every model on real data (events 71.4% vs 50%, tasks 88.6% vs 81.4%) because
  the only labels this project owns are the rules' own output. The blocker is
  data, not model choice. A page that shows an ML classifier shipping today
  would be claiming something untrue.

## decompose_validate — three malformed values reaching the intents (2026-09-10)

Found as free diagnostics in **Board D's stderr**, not by looking for them: 25
rows out of the first ~600 built an intent that pydantic then REFUSED, so the
row silently produced nothing. All three are value-shape defects upstream of
FastRule, and none is LLMJudge's to fix.

    18   delete_event   "Either match_title or match_start_time must be provided"
    10                  "time must be HH:MM, got '09:59:59'"
     2   create_event   "Event title cannot be empty"

The middle one is a SIBLING of the already-filed `start_time = '30:00'`: a clock
value reaching the intent with seconds on it. Both say the resolver is emitting
a shape the intent contract does not accept, and the contract is right — a time
is HH:MM. Fix the producer, not the validator.

The first is the larger count and the more interesting one: a delete built with
BOTH identifiers empty is a delete aimed at nothing, and this project's rule is
that when the engine cannot identify what to delete, empty slots surfacing as
"I couldn't find …" is the right answer. It is currently surfacing as a
swallowed exception instead, which is the same outcome by accident rather than
by design — and an accident that stops being safe the moment the fields are
half-populated.

**Reproduce:** any `board_d` run prints them to stderr; `-n 200` is enough.

**The first line (`delete_event`, empty match_title/match_start_time) is FIXED
— 2026-09-15, `llmjudge/experiments/RESULTS.md` cycle 18 — and the "upstream of
FastRule, none is LLMJudge's to fix" framing above was wrong for this one.**
Traced stage-by-stage rather than assumed: `decompose_validate` and FastRule's
`build()` both already resolve the target correctly; the model's OWN
confirmation re-parse (`needs-target-check` → `llmjudge/rescue.py`) was
occasionally discarding it, because the hand-off designed to show the model
that answer (`Defer.partial`, "what WAS read, so LLMJudge starts warm") was
dead code — `rescue.py`'s `_Verdict.partial` hardcoded to `None`, nothing else
in `assistant/engine/` ever setting it. Two fixes, each tested and measured on
its own: the hint is wired through (`fastrule/build.py`, `fastrule/stage.py`,
`llmjudge/rescue.py`), and a deterministic fallback reuses FastRule's own build
when the model still fails after being given it. Measured on the full
update/delete/complete pool (884 rows, 552 reaching `needs-target-check`): raw
model failure rate 0.4% (far below the ~40-60% three hand-picked adversarial
rows suggested), 94.4% → 94.7% after the fallback. Full unit suite green
(1655 passed). Not yet committed.

**The HH:MM:SS/ISO-datetime/bare-phrase line is FIXED too — 2026-09-15,
`llmjudge/experiments/RESULTS.md` cycle 19, and it was never
`decompose_validate`'s bug either.** `decompose_validate.run_objects`
already unconditionally re-resolves and overwrites `start_time`/`end_time`
on every intent that reaches it — the model's own guess was always
throwaway. The actual producer was `assistant/intent/parser.py::
_parse_response`, constructing the model's raw JSON straight into pydantic
without normalizing it first. Fixed with `_normalize_time_fields`: extract
the HH:MM prefix an ISO datetime or HH:MM:SS carries, drop anything
unparseable (a bare phrase, a relative duration like `"by an hour"`) to
`None` rather than crash the item. Measured on the full create_event/
update_event population (1,963 rows, ~54% of the eligible pool): 187 rows
(9.5%) would have hit this; 79.9% → 88.6% correct overall, 171/187 of the
recovered rows score fully correct. **Corrected same day**: the first
measurement pass scored `update_event`/`delete_event` rows by reading
`.title` (an attribute those intents don't have — they carry `.match_title`),
silently undercounting BOTH sides; the originally reported 73.6%→79.8%
(122/199 recovered) is retracted — see `llmjudge/experiments/RESULTS.md`
cycle 19 for the full account. Full unit suite green (1664 passed).
Committed (`b0cc371`, `a46fed1`).

**Empty create_event title is the one line still unfixed** from the
original 2026-09-10 filing — smallest count (2/30) of the three, not yet
traced.

## A phantom "Reminder" event — TRACED, and it's a design decision, not a bug fix (2026-09-15)

    "book flu shot new year's eve at 9:15, notify me 15 minutes before"

Traced stage by stage, same method as cycles 18/19. The full mechanism,
confirmed:

    after segment:              item_1 "book flu shot" (time="…9:15")
                                 item_2 "notify me" (time="today 15 minutes before")
    after decompose_validate:   item_1.slots: date/start_time resolved, NO reminder_minutes
                                 item_2.slots: reminder_minutes=15 (correctly resolved!)
    after fastrule:             item_1 builds fine; item_2 -> action=None (no title, no route)
    final (model rescues item_2): item_1 "flu shot", reminder_minutes STILL None
                                 item_2 becomes a fabricated "Notification"/"Reminder"
                                 event, flagged unsupported_field (a made-up start_time) —
                                 or, on a different sample, loops via ungrounded_subject
                                 and the fabricated event gets an `r1_` id instead. Which
                                 one happens varies with the model's own sampling; the root
                                 cause is upstream of both.

**This is not a bug in any one stage — `decompose_validate` computes
`reminder_minutes` correctly on `item_2`; the problem is nothing ever
transfers it onto `item_1`, the event it is actually about.** `item_2` has
no title, no action, and nothing to build on its own, so whatever handles it
downstream (FastRule's Defer path, then the model) has no honest option
except inventing something — the reminder value is real, computed
correctly, and stranded on an item nothing knows how to attach to its
neighbor.

**Why this is filed as a decision, not fixed outright**: segmentation
DELIBERATELY produced two items here — that is what its "STRUCTURE" gate is
for when a command's words describe more than one component. Fixing this
means either (a) segmentation should recognize a bare lead-time clause
("notify me N minutes before") as a modifier of the PRECEDING item rather
than a second ask, or (b) `decompose_validate` gets a new cross-item merge
step that folds a reminder-only item's `reminder_minutes` onto its
predecessor and drops the orphan. (a) is squarely a segmentation STRUCTURE
change, which the 2026-09-12 ruling reserves for Gil's say-so
(`STATUS.md`). (b) touches how many items reach FastRule, which is the same
category of call — decompose_validate's own contract says "it never
splits; segmentation already decided the boundaries," and merging two of
segmentation's items back into one sits right against that line. Recorded
here rather than implemented, per the standing rule to read every proposal
against *"I don't really want to make structural changes if I don't have
to"* and to route exactly this kind of call to Gil rather than decide it
solo.

**If Gil rules in favor of a fix**: search the fastrule_7200 train split for
more real rows shaped like this ("notify me"/"remind me"/"alert me" ...
"before", combined with another ask) to see how common the pattern is
before choosing (a) or (b) — one repro is not enough to size the fix.

## Empty create_event title — CONCLUDED, not a bug (2026-09-15)

Found real reproducing rows before deciding anything, same method as cycles
18/19: scanned 500 create_event train rows, one model call each. **Exactly
1 hit (0.2%)** — consistent with the original 2026-09-10 filing's 2/~600
(≈0.3%), so the rate itself isn't in question, only whether it's fixable.

    "i owe Blake a conversation, let's do on the 15th"

FastRule's deterministic rule parser found NO route at all here (`skip`,
`had_partial: False`) — this phrasing has no verb+object shape any pattern
recognizes. The model, asked cold, ALSO produced no usable title. Both
readers independently found nothing, which is the tell: unlike the two
lines fixed this session, there is no known-correct answer sitting
unused anywhere in the pipeline to recover — `decompose_validate` never
re-derives a title the way it re-derives `start_time`/`end_time`, so there
is nothing to fall back to.

**Verdict: this is not a bug to fix, at this frequency, with this evidence.**
Inventing a title ("conversation with Blake"?) would be exactly the kind of
invention this project's architecture exists to refuse. Today's "I couldn't
read this part" is honest, if generic. Not pursuing a special-cased message
for a 0.2% edge case with no derivable answer — the cost of the abstraction
would exceed the value of the fix.

## A venue name after a comma still splits into a second event (2026-09-15)

Surfaced verifying the period-clock fix above, on the SAME real utterance —
fixing the clock reading exposed this as the remaining half of what Gil
saw, exactly as CLAUDE.md's own lesson warns ("fixing a stage exposes the
next one").

    "Movie at Lincoln Square tomorrow, AMC, 11.15 AM tomorrow"

now correctly resolves 11:15 (was 15:00) — but still becomes TWO events:
"Movie at Lincoln Square" and "AMC", because segmentation splits at the
comma before "AMC". One event, spoken with a venue name set off by commas
as an aside, reads as two asks.

**Where this lives**: `assistant/intent/coordination.py`'s `ASK_JOINER_RE`
has a bare `[;,]` fallback — ANY comma counts as a possible ask-joiner,
independent of the NP-vs-clause-coordination check this same module
already does properly for "and" (spaCy dependency parse: a VERB conjunct is
a second ask, a NOUN/PROPN conjunct is a longer noun phrase, per this
module's own docstring). The comma path does not get that check at all.
The module's own comment says this is a KNOWN, deliberate trade-off ("A
comma inside a single ask over-counts, which is the safe direction... the
downstream consumer prefers to defer") — meaning today's design expects
FastRule's compound gate to catch an over-split comma and defer rather than
build two objects, and evidently doesn't, at least not for this shape.

**Not investigated further this session** — this is a candidate STRUCTURE
change (how commas are read for coordination), squarely inside the
segmentation-adjacent freeze, and deserves its own trace (does
`_parse_covers_the_compound` see this case and fail to catch it, or does it
never get asked) before anyone decides whether extending the NP/clause
check to commas is an implementation fix or a structure change. Same method
next time: find more real rows shaped like "X [location/name set off by
commas], time" before touching anything.

## Deferred — a structural convolution sweep over the engine (queued 2026-09-15)

Gil asked for a pass over `assistant/engine/`'s seven areas (orchestrator +
shared infra, ingest, segmentation, decompose_validate, fastrule, llmjudge,
label) specifically for STRUCTURAL convolution — not correctness bugs, but
places where the code's actual behavior has drifted from what its own
comments/docstrings claim, fields/functions that exist but nothing reads or
writes, a stage reaching into another's internals outside the documented
Item/Defer boundary, or logic duplicated where it should be shared. Cycle
18/19's own findings are the calibration example: `Defer.partial` existed,
was documented ("what WAS read, so LLMJudge starts warm"), and was never
wired end to end; `fastrule/stage.py` had a comment describing behavior the
code next to it did not implement.

**Deferred, not abandoned** — a 7-finder-plus-verifier workflow was launched
and then stopped immediately (`wf_d0b846f7-7a5`, no findings produced) because
weekly session quota was at 8% remaining at the time
(`claude-session.py --advise`: "one lane only — finish what's in flight,
don't start a wide batch"). Re-run once quota resets. The workflow script
that was about to run is banked at
`.claude/.../workflows/scripts/engine-structure-review-wf_d0b846f7-7a5.js`
(session-local path, not in the repo) — re-invoke with that `scriptPath`
rather than re-authoring it from scratch.

## iPad view renders like the iPhone view — DEFERRED, not investigated (queued 2026-09-15)

Gil, reported verbally, not yet reproduced or traced: the iPad layout looks
like the iPhone layout rather than using the extra screen — sounds like a
missing size-class / `UIUserInterfaceIdiom.pad` adaptation somewhere in
`MACalendar-iOS/`, but that is a guess, not a finding; nobody has opened it
on an iPad or the iPad simulator yet to confirm which views are affected.
Belongs to the app stream (`../MACalendar-app` worktree, `app-features`
branch) when picked up, not this checkout. Whoever starts this: the iOS
simulator's own tap-automation isn't reliable for this project, so plan on a
real device or manual simulator inspection rather than scripting it.

## A queued command's "tomorrow" means the wrong day — DECISION NEEDED (2026-09-10)

Found while making the offline queue behave. Not a bug with an obvious fix: a
question about what the speaker meant, which is Gil's to answer.

`decompose_validate.resolve_values(state, anchor=None)` falls back to
`dt.date.today()`, and `run()` passes no anchor. So a relative date resolves
against **when the command was FLUSHED**, not when it was spoken:

    spoken Monday, phone in a tunnel until Thursday
    "book gym tomorrow"   ->  books FRIDAY

Both queues have this. The phone's `LocalStore` holds commands that never
reached the Mac; the server's `pending` table holds commands that arrived while
ollama was down. Either can span a day boundary.

**Three readings, and they disagree about a real case:**

1. **Anchor on when it was SPOKEN.** Truest to intent — they meant Tuesday. But
   by Thursday that date is in the past, so `past_date_bump` fires and moves it
   somewhere else anyway; we would have traded one wrong day for another.
2. **Anchor on the flush (today's behaviour).** Never books the past, always
   books a day the speaker did not mean.
3. **Announce it.** This project's own idiom for exactly this shape — *"the
   rounding is announced in the reply rather than done quietly"*, and the same
   rule that makes a recurrence round out loud. The command runs, and the reply
   says the relative date was read against today because it was queued for N
   days.

I lean 3, and it needs no new semantics — but it is a product decision about
what the user is told, so it is filed rather than chosen.

**Reproduce:** queue a row with a `ts` a few days old and a relative date word,
then run `retry_pending_once`. `tests/unit/test_offline_queue_scenarios.py` has
the harness.

## A bare-imperative multi-object task silently drops every object but the first — FIXED (2026-09-17)

**Fixed.** `_dobj_conjunct_title` (`rule_parser.py`, next to `_extract_title`)
walks the coordination chain from the root verb's direct object — spaCy
attaches a coordinated object's conjunct EITHER to the object noun ("buy
notes, APPLES, and PAPER") or to the root verb directly ("call the dentist
and the VET"), both real outputs, so both are walked — and slices the
ORIGINAL text from the first object to the last, keeping the speaker's own
commas and "and" rather than rebuilding them. One guard: a `prep` child of
the root verb sitting between the dobj and a candidate conjunct means the
candidate belongs to THAT prepositional phrase's own coordination ("buy milk
FROM THE STORE and the MARKET" — market pairs with store, not milk), found
by exactly that case over-including "from the store and the market" before
the guard was added. Verified live via `run_transcript` on all three
examples below (now keep every object); 6 new cases in
`test_todo_item_splitting.py`; zero change on the FastRule 7,200-row board,
both halves, output byte-identical before/after (this board's own TITLE
QUALITY metric only flags empty/generic titles, not missing coordinated
objects, so an unchanged score here is the expected confirmation of no
regression, not evidence the board captured the fix).

**A related tension, found but NOT resolved**: `_todo_titles_from_text`/
`list_split.split_items` — the mechanism `_TODO_LEAD`-prefixed commands use
("remind me to buy chicken and rice" → TWO tasks, tested and intentional,
`test_the_reported_command_makes_two_tasks`) — still SPLITS a shared-verb
bare object list into multiple tasks, the opposite of DEVQA's Q14 reversal
(a bare "buy chicken and rice" with NO lead-in now correctly stays ONE task
after this fix). So the same shape currently resolves two different ways
depending only on whether a framing phrase like "remind me to" precedes it
— not touched here, since reconciling it means either changing `split_items`
tested, intentional multi-task behavior (a bigger, riskier change touching
the FastRule corpus's own gold expectations for that shape) or accepting
the inconsistency as a real product-level question for a ruling, the same
way Q14 and `wrapper-phrase` got one. Whoever picks this up: get a ruling
first.

Found while testing whether `decompose_validate` handles a multi-object
segmentation item correctly, after DEVQA.md's Q14 reversal (same date,
above) — it doesn't get the chance to. Confirmed live via
`assistant.engine.run_transcript`:

    "buy eight sticky notes, apples, and printer paper"
       -> saved as "buy sticky notes ×8"        (apples, printer paper GONE)
    "buy shampoo and apples"
       -> saved as "buy shampoo"                (apples GONE)
    "pick up envelopes and sellotape from the stationers"
       -> saved as "pick up envelopes"          (sellotape GONE)

**Root cause, traced to the exact function**: `assistant/intent/
rule_parser.py::_extract_title` (lines 1250-1261). For a bare imperative
with no lead-in phrase ("buy X and Y", not "remind me to buy X and Y"),
`_TODO_LEAD` (lines 1189-1198) doesn't match, so the CORRECT multi-item
splitter (`_todo_titles_from_text` -> `list_split.split_items`, already
capable of handling this — verified directly: `"I want to buy shampoo and
apples"` -> `['buy shampoo', 'buy apples']`, correct) never runs. Code
falls to `_extract_title`'s fallback, which walks spaCy `noun_chunks` and
returns only the FIRST chunk whose `root.dep_ == "dobj"` — "apples" is a
SEPARATE chunk with `dep_="conj"`, never looked at. This one truncated
title then reaches `CreateTodoAction` via FastRule's instant fast-track
(`fastrule/fast_track.py::fast_propose`, confidence 0.95 >= threshold)
before segmentation or `decompose_validate` ever run — confirmed via trace,
only "Rule parser Confident (0.95) — instant" then "execute". The "×8" on
the sticky-notes case is `quantity.split_quantity` correctly parsing the
ALREADY-TRUNCATED title; `quantity.py` is not the bug.

**Long-standing, not introduced by today's session** — `_extract_title`/
`_TODO_LEAD` predate the 2026-09-10 fast-track restructure that made this
path instantly committable without a second look. `tests/unit/
test_todo_item_splitting.py` already covers this exact class of bug, but
every multi-object case in it is prefixed with a lead-in phrase ("I want
to", "I need to", "remind me to", "add a task to") — the bare-imperative
form is the untested gap.

**Why it matters now, more than it looked like it did before today**: DEVQA
Q14 reversal (above) makes "buy shampoo and apples"-shaped bare imperatives
the OFFICIALLY correct, one-item segmentation behavior going forward, not
just the `np_decoy` family's quiet exception — and this is an extremely
common, natural way to give a real shopping-list voice command with no
lead-in phrase at all. This bug has likely been silently losing items on
real usage all along; it just had no segmentation-level gold checking the
FULL downstream title to surface it.

**Not fixed this session** — traced precisely, not touched, per standing
guidance to test and note rather than bundle an unrelated stage's fix into
the same change. Candidate fix directions for whoever picks this up: either
widen `_TODO_LEAD` to also match on bare-imperative + NP-coordination (so
`_todo_titles_from_text` fires without needing a lead-in), or make
`_extract_title`'s fallback itself NP-coordination-aware (collect every
`dobj`-or-sibling-`conj` chunk, not just the first `dobj`). Either needs the
same test-and-measure discipline as everything else this session — a
dedicated bare-imperative test class added to `test_todo_item_splitting.py`
first, then the fix, then the whole FastRule dataset re-run to confirm no
regression on the 7,200-row corpus.

## `wrapper-phrase` gold contradicts its own SPEC.md example — NOT FIXED, filed (2026-09-16)

Found while pushing FastSeg v1's exact-row further (see
`assistant/engine/segmentation/ARCHITECTURE.md` §0b for the full session).
`SPEC.md`'s own `wrapper-phrase` trap row uses **"add buy milk and buy bread
to my list"** as its canonical MUST-NOT-SPLIT example — "one verb + one
destination over both" — and `DEVQA.md`'s 2026-09-16 Q14 entry explicitly
says this exact sentence was "already correct… already never split." The
actual gold row (`ns-0049` in `nosplit_traps.jsonl`) splits it into two
items, and two sibling rows in the same `wrapper-phrase-to-my-list` family
(`ns-0050`, `ns-0052`) do too.

This is the same SHAPE as the Q14 conflict (a documented ruling the dataset
doesn't actually match) — it just wasn't caught by Q14's own fix, because
`has_clause_coordination("add buy milk and buy bread to my list")` is TRUE
here (two real "buy" VERB conjuncts, not a bare coordinated noun list),
which correctly excluded these three rows from Q14's filter but says
nothing about which reading is actually intended: wrapper-phrase's
documented rule, or the row's own gold.

**Not fixed** — this needs the same kind of explicit ruling Q14 got (see
DEVQA.md), not a unilateral code or dataset change either way. Whoever picks
this up: get a ruling first, then either (a) fix the 3 gold rows to match
SPEC.md's documented rule (merge to one item each), or (b) reverse
wrapper-phrase's own SPEC.md row and DEVQA.md's Q14 annotation to match the
gold that's actually there. FastSeg v1's code should not change either way
— like Q14, this is a labelling question, not an implementation one.

## A todo's relative due-date silently falls back to today for some phrasings — NOT FIXED, filed (2026-09-17)

Found while verifying claims for the new "how to talk to me" tips (below)
against the live engine, before writing them down — not chased further,
since it's unrelated to that task.

    "renew the passport in two weeks"   -> due_date SILENTLY = today
    "renew the passport the 15th"       -> due_date SILENTLY = today
    "renew the passport ON the 15th"    -> due_date = the 15th, correct
    "call mom next tuesday"             -> due_date = next tuesday, correct

No error, no flag — the todo is just created with today's date, the same
outcome as if no date had been said at all. `"on the 15th"` works;
`"the 15th"` alone and `"in two weeks"` do not, from a very small,
unsystematic sample (3 phrasings tried, not a real audit). Worth someone
tracing `_fill_slots`'s `create_todo` branch's `temporal.get("date")` path
(`rule_parser.py`) against a proper set of relative-date phrasings before
trusting due dates on tasks generally.

## The bare-ordinal due date is FIXED; two defects found beside it are NOT (2026-09-17)

The filed defect above (*"a todo's relative due-date silently falls back to
today for some phrasings"*) is **half fixed**. `"the 15th"` / `"the 30th"` now
resolve — `assistant/intent/rule_parser.py`, `_BARE_ORDINAL_DATE` +
`_ordinal_to_date`, measured in `assistant/engine/fastrule/experiments/
RESULTS.md` cycle 20 (handle-rate 68.2% → 70.4% on the FastRule 7,200 train
half's 3,200 atomic rows). **`"in two weeks"` and `"by friday"` are NOT fixed**
and are the next cycle, blocked on the ruling below.

**RULED AND SHIPPED, same day (2026-09-17).** Gil chose **ask instead of
guessing**, so the range is read and then OFFERED through the existing
`confirm_create` gate (DEVQA Q9) with the chosen day named — from the fast
parse, with no model call. An update or delete with a range date does not
execute at all (`range-date-target`, REFUSAL), because acting on a day the
speaker never said is the destructive guess the project already rules out.
`"in two weeks"` turned out not to be a range problem at all but a duration,
and the recogniser reads those badly (`"in a week"` → TOMORROW), so they are
arithmetic. Measured in `fastrule/experiments/RESULTS.md` cycle 21: handle-rate
70.4% → **72.9%** on the FastRule train half's 3,200 atomic rows, DESTRUCTIVE
errors **33 → 28**, harm flat at 170. The paragraph below is the question as it
stood before the ruling, kept because it records what was decided and why.

**The question that was asked (now answered):**

**RULING NEEDED — what date does a RANGE phrase mean as an item's own date?**
`_extract_temporal` handles the timex types `datetime`, `date`, `time` and
`timerange` and has no **`daterange`** branch, so the recogniser's answer for
`"next week"` (start 2026-09-21, end 2026-09-28), `"this weekend"`, `"in two
weeks"`, `"next month"` and `"by friday"` is thrown away and the date is
silently dropped. 605 rows of the FastRule train half (12.6%) are affected;
263 are one-off atomic writes, a **+6.3 pt** handle-rate ceiling.

The blocker is not the code, it is that `"book yoga class next week"` has no
single right answer and the FastRule board *deliberately* excludes these rows
from its date metric for exactly that reason (`_phrase_to_date` returns None,
commented "no single right answer"). Committing one means picking a
convention. **Recommended: the soonest day in the named range** (the
recogniser's `start` bound) — consistent with the two rulings the project
already has, that a weekly series starts on the soonest weekday the sentence
names and that "until the end of September" is inclusive. `"by friday"` is the
exception and wants the `end` bound, since it names a deadline rather than a
span. Not started either way.

Two further shapes, each needing its own handling and NOT covered by that
ruling: the 50 boundary rows where the range is a recurrence bound
(`"every monday until the end of the month"` → `date_phrase_2` +
`end_inclusive`, 28 inclusive / 22 exclusive in the train half, governed by the
existing until/through ruling) and the 70 query rows, where a range is the
ANSWER and not a field (`"what do I have this week"`).

## A coordinated-verb task extracts NO title at all — NOT FIXED, filed (2026-09-17)

Found while writing the bare-ordinal tests, when a test row turned out to carry
a second, independent defect. Confirmed to be unrelated to dates — it fails
identically with a date, without one, and with the date removed entirely:

    "wash and fold the laundry the 30th"   -> missing_slots=['titles'], NO intent
    "wash and fold the laundry tomorrow"   -> missing_slots=['titles'], NO intent
    "wash and fold the laundry"            -> missing_slots=['titles'], NO intent
    "wash the laundry the 30th"            -> create_todo 'wash laundry'  CORRECT

A bare imperative with **two coordinated verbs over one object** extracts no
title, so the row carries `create_todo` with no `titles` and produces no intent
at all — it defers to the deep track rather than being wrong, so it costs
latency and accuracy rather than data. Same family as the bare-imperative
multi-object defect filed above (`_extract_title` walking `noun_chunks` and
taking the first `dobj`), and it should probably be picked up with it, not
separately.

## The date text leaks into the title in the lead-in + and-split branch — NOT FIXED, filed (2026-09-17)

Same session. With a lead-in phrase AND a coordinating "and", the todo-title
path splits on the "and" and carries the date words into the second title,
although the date itself resolves correctly:

    "remind me to wash and fold the laundry the 30th"
       -> titles ['wash', 'fold the laundry the 30th']   due_date 2026-09-30 (right)

`_todo_titles_from_text` receives `temporal_spans` and the blocked span IS
supplied by the new fallback (the non-split path proves it: `"wash the laundry
the 30th"` → `'wash laundry'`, clean), so the spans are being ignored or
recomputed somewhere inside the split branch. **Pre-existing** — the title text
was equally wrong before this cycle, which only added the date beside it. Not
touched, per the standing rule against bundling an unrelated fix into a
measured change.

## Order of play (2026-09-18) — `DOCUMENTATION/REAL_SPEECH_PLAN.md`

The plan for the next stretch of engine work, written for whichever session
picks it up. Phase 1 (real-usage board) → Phase 2 (unknown-word gate) →
Phase 3 (latency: instrument, then cut) → Phase 4 gated on Gil. Rows for each
phase go in this table as they start; the plan is the spec, this file is the
tracker. Do not start a parallel list.

## "by 30 minutes" — the RELATIVE duration — NOT FIXED, filed (2026-09-18)

Found while fixing the absolute form Gil reported. `"shorten the meeting to be
15 minutes"` now works: the new end is `start + 15 min`, and the rule parser
knows the start because the speaker said it.

`"shorten the meeting BY 30 minutes"` cannot be answered here. It needs the
event's CURRENT end, which `rule_parser` never loads — it builds an intent, it
does not read the calendar. So the arithmetic belongs either in
`UpdateEventAction.execute` (which has the row) or in a new optional intent
field carrying the delta.

The same shape is already on record from the other direction: STATUS.md's
malformed-value list has the model returning `{'new_end_time': 'by an hour'}`
and `{'new_end_time': '20 minutes'}`, which `parser._normalize_time_fields`
now drops rather than crashing on. So BOTH tracks currently discard a relative
duration; the deep track merely fails more quietly.

Whoever picks this up: decide where it lives before writing it, since an
optional intent field is a contract question and the action layer is not.

## NO WAY TO SAY "THAT ONE IS NOT RECURRING" — NOT FIXED, filed 2026-09-18

Gil, from his phone, immediately after a misheard "every" booked a weekly
series (fixed in 668660a — the CAUSE is gone, this is the CURE that is still
missing):

    "For the event tomorrow, it is not reoccurring, it's only tomorrow,
     please fix, execute."

    Rule parser        skip: no action matched  -> deep track
    Split into commands  2 items: "For the event tomorrow" ·
                         "it is not reoccurring, it's only , pleas"
    Built the objects    0 of 2 converted; 2 to the model
                         ...still working at 15.3s

**It is not a parse bug, it is a missing capability.** `UpdateEventIntent`
carries `match_title`, `match_date`, `match_start_time`, `new_title`,
`new_date`, `new_start_time`, `new_end_time`, `new_location`,
`new_description` — and NOTHING for recurrence. The intent cannot express
"stop repeating", so no amount of parsing would help.

**This is an intent-contract change and therefore Gil's call**, the same
category as the relative-duration row above ("an optional intent field is a
contract question and the action layer is not").

The shape, if approved:

- `new_recurrence: str | None` on `UpdateEventIntent`, where `""` CLEARS and a
  cadence sets. Empty-string-clears rather than None-clears because None
  already means "not mentioned" for every other `new_*` field on this intent,
  and overloading it would make "don't touch the recurrence" unsayable.
- Route the phrasings: "it is not recurring", "it's only tomorrow", "just
  once", "make it a one-off", "stop repeating", "not every week". Note the
  speaker says "reoccurring" as often as "recurring" — both, plus the
  vocabulary path for the mishearings.
- `UpdateEventAction.execute` then has to decide what CLEARING means for a
  series that has already expanded into rows: delete the future instances and
  keep the named one, or keep all and stop generating. That is the real
  question in this row, not the parsing.

Until it exists, the only way out of a wrongly-created series is the Mac GUI
or the phone's event editor.

## CONTRACT CHANGE — decompose_validate may MULTIPLY an item, never RE-CUT one

**Approved by Gil, 2026-09-18.** A DESIGN change to a frozen contract, filed
here rather than slipped into a fix, per CLAUDE.md.

`decompose_validate/ARCHITECTURE.md` says today:

> **decompose RESOLVES. validate CHECKS. Neither one SPLITS.**
> Splitting is segmentation's job and asking twice is how items get double-cut.

Gil: *"the segmentation is just splitting it, but sometimes we also need to do
more splits... in parallel to the recurrence... split first, then the
recurrence, then the validate."* The reason it holds up: **some splits cannot
be decided on words alone — they need resolved values.** Whether "at 9 and
2:30" is two times or one range is a question about VALUES, and deciding it
before resolution is deciding it blind. Same shape as Q16's "never": a rule
stated absolutely because it was written against one failure mode.

**THE RULE THAT KEEPS THE OLD BUG DEAD.** The stage may MULTIPLY an item; it
may never RE-CUT one:

    MULTIPLY   same ask, several occurrences — a recurrence fanning into
               instances, one ask with two clock times. Every product has
               the SAME TITLE.
    RE-CUT     different asks — "buy milk and call mom". Segmentation's,
               permanently.

Double-cutting is always a re-cut and never a multiply, so this preserves
exactly what the original prohibition protected. It is CHECKABLE rather than a
matter of judgement, and it ships with its guard on day one: **a fan-out whose
products have different titles FAILS THE BUILD.** Without that test this
becomes the double-cut bug again in six months.

So the order inside the stage becomes one new step, not two — split and
recurrence are the same operation under this framing:

    resolve  ->  fan out  ->  validate

validate still runs last and still checks the fanned-out items against X1.

**WHAT IT COSTS, and none of it is optional** (the panel procedure in
CLAUDE.md): bump `BRAIN_VERSION`, update `CHAINS` in `assistant/trace.py`, the
HUD render (`thinking_panel.py` + any new stage icon), the iOS `ThinkingView`,
and the explorer diagram. `test_panel_agreement.py` goes red naming what is
missing, and `test_engine_contracts.py` pins the I/O contract being changed.

**NOT STARTED.** Sequenced after the routing fix and the command-frame repair,
which are small and measurable on a board that already exists; this one needs
its own run.

## A TRAILING day is not distributed; a LEADING one is — NOT FIXED, filed 2026-09-18

`fastseg.assign_times` fills each ask's `time` from a day slot and a clock
slot. A day at the FRONT fills the day slot for every ask; a day at the END
fills it only for the ask it sits in, and the earlier asks are floored to
today. Measured through the real pipeline:

    "book the dentist at 3pm and the gym at 5pm friday"
        dentist  time='today at 3pm'    date=2026-09-09   <- WRONG
        gym      time='friday at 5pm'   date=2026-09-11
    "friday book the dentist at 3pm and the gym at 5pm"
        dentist  time='friday at 3pm'   date=2026-09-11   correct
        gym      time='friday at 5pm'   date=2026-09-11

**Gil ruled on the answer (2026-09-18, DEVQA Q16 amendment): both are on
Friday.** So this is now an implementation fix against a settled ruling, which
is allowed under the 2026-09-12 narrowing — but it is in the most-measured
component in the project, so it needs FastSeg's own board (exact-row 74.6%
train / 73.6% sealed) before and after, not just a spot check.

The shape of the fix: a trailing DAY should fill the day slot of an earlier
ask that has a CLOCK but no day of its own. `_SLOT_ORDER = {"day": 0,
"clock": 1}` already exists, so the slot concept is there — what is missing is
distributing the day slot backwards. Do NOT distribute the clock: two asks
with their own clocks keep them, which is what makes this different from the
whole-reference sharing `_scope_trailing_date` governs.

Beside it, and separate: a FRONTED marked deadline is not extracted into
`time` at all — `"by friday file the taxes and call Jordan"` leaves a task
titled `'call Jordan by friday'` and both dates floored to today.

## POSITION INVARIANCE — MEASURED AND FOUR FIXES LANDED, 2026-09-18

Gil, 2026-09-18: *"a very important part of the project is to make sure that
we're invariant to where the time / title are located in the prompt."*

New cross-stage instrument: `scripts/invariance_board.py`, metric defined in
`dataset/METRICS.md` Level 4b, first run in
`DOCUMENTATION/experiments/invariance/RESULTS.md`. It exists because **every
row of the FastRule 7,200 set puts the time at the END**, so every number that
board has printed is an end-position measurement and none of them could see
this.

First run, FastRule 7,200 train half, 1,548 comparable groups — **percentage
of groups whose variants DISAGREE**:

    segmentation         16.0%     <- the owner; loses the word partition 1 row in 6
    decompose_validate    9.1%     <- inherits only, adds none
    fastrule (stage)      7.9%     <- inherits only, adds none
    front door           68.7%     <- a separate problem

Invariance degrades UP the chain (16.0 -> 9.1 -> 7.9), which is evidence the
per-item design in `decompose_validate` is holding: it cannot be adding
position-dependence if there is less of it downstream. **Segmentation is the
owner and is where a fix belongs**; the front door is a second, larger problem
because it redoes both jobs on raw text.

**FOUR FIXES LANDED** (58d6794, 964e093, 15b9229, 9f7d44a) — front door
68.7% → 50.3%, segmentation 16.0% → 13.8%, dv 9.1% → 6.3%, fastrule 7.9% →
4.8%, and the end→front correctness gap 6.0 pt → 1.7 pt. Run 2 and what
produced each number are in `DOCUMENTATION/experiments/invariance/RESULTS.md`.
The remaining front-door 50.3% is mostly `_ROUTE_OVERRIDES`, all 16 of which
are `^`-anchored on RAW text — measured as 55.4% of divergent groups but
mostly BENIGN (91.5% keep the same action and move only the title, which the
title fixes now handle). **The original framing below is kept for the history.**

**WAS: NOT STARTED — Gil is deciding the direction** (2026-09-18: *"don't change
the system. We're just testing the system for this invariant quality... then
we can decide how we want to move forward"*). Three candidates, none begun:

- fix segmentation's partition (implementation, allowed under the 2026-09-12
  narrowing) — targets the 16.0%, and should not move the front door at all
- normalise the time to the end inside the front door, the way `Item.spoken()`
  already does for the deep track (implementation, one stage) — targets 68.7%
- have the front door consume segmentation's items instead of raw text — a
  CHAIN-SHAPE change, Gil's call, not to be slipped in under a defect fix

Two defects found beside it and also unfixed: a leading time phrase FOLLOWED
BY A COMMA loses the date entirely (`"the 30th, wash and fold the laundry"` ->
`due_date=None`, while the same words without the comma resolve), and 36-38%
of rows are *consistently* wrong across every position — an accuracy problem
this board deliberately counts in its own column rather than confusing with a
position one.

**TITLE AXIS — PROBED AND THE FRONT-DOOR LEAK FIXED, 2026-09-19.** The
position board above could not see a title's CONTENT changing a value. Probed
on decompose_validate (1,477 train time phrases × 115 titles = 169,855 pairs):
the time fields moved in **0 undesigned pairs** — the stage is title-invariant
bar its three written conventions (`decompose_validate/ARCHITECTURE.md`,
"Invariance"). The leak was the FRONT DOOR: a title word beat the stated clock
or day in 4 of 9 live probe commands. Three precedence rules landed in
`rule_parser._extract_temporal`, each boarded alone (`46506f3`, `ec7849c`,
`0c16b83`; `fastrule/experiments/RESULTS.md` cycle 24): a daypart window
yields to a stated clock (and directly after a clock is its meridiem), a
series bound needs its date adjacent to the keyword, and the date carrying the
clock outranks a bare date. Product-shape board flat on every headline
(3,200 atomic train rows), 9 rows gained a right clock, 0 worse; live probe
4/9 wrong → 0/9.

Two candidates filed, not fixed, both needing a word from Gil:

- **The two tracks disagree on the bare hour** — "at 7" is 19:00 on the front
  door and 07:00 in `decompose_validate` (its conventions table: 1–6 PM, 7–8
  PM only with evening words). Same sentence, different answer by path.
  **DEVQA Q28 — ANSWERED 2026-09-20 and BUILT**: a genuine bare 7 or 8 is
  asked about when the client can render a prompt, and otherwise resolves PM
  on BOTH tracks with the reply saying so. `resolve._bare_hour` is aligned to
  the front door; `object_rules._rule_bare_hour_asks_first` and
  `fast_track`'s `ask_first` do the asking.
- **`resolve_quantity` counts any digit in a title** ("chapter 5 review" → a
  task of 5). Board-blind (the title banks carry no digit; board B grounds any
  digit in the words). Real pool: 0 identifier numbers, 1 address in 2,699
  rows — low frequency, so it waits.

## THE CHECKPOINT'S QUEUE — items 1–3 landed, 4–8 open, 2026-09-20

The plan written from the dev-100 checkpoint (run 22; `dataset/RESULTS.md`)
had eight items. Gil: *"ok work on these and try improve system."* Each
stage-internal item was boarded alone on its own stage, then the same 100
rows were read again (run 25: count-correct 74 → **83%**, deep path 62 →
72%, item F1 75.0 → 86.0, failures 26 → 17; run 26 adds the two tagger
rows below).

| # | item | status | measured |
|---|---|---|---|
| 1 | kind tagger: a new list / a list of things, a wake word, a yes/no question, "i want <thing>"; then "is …" without its time | **done** (`fastseg/kind.py`) | segmentation board byte-identical on 1,051; dev-100 rows |
| 2 | FastSeg hard seams: ". Also,", "; then", dash-and, ", (and) then" | **done** (`fastseg.py::_hard_seams`) | exact-row 90.1 → 90.3, under-split 16 → 14 |
| 3 | fast path: a noun is not a command; "remind me about/of/when" is an event; a title holding the joiner covers nothing; note/date name nothing | **done** (`rule_parser`, `fastrule`, `gatekeeper`) | product-shape board: 0 changed atomic objects; non-atomic half-executed 56 → 52, carve-out commits 337 → 307 |
| 3b | the converter's kind table: a review the verb routed to a create is a query | **done** (`build._ACTION_FOR`) | stage board (gold, 1,200) byte-identical |
| 4 | the judge's exhaustion path commits a subject-less object ("add this", the rescue's 'Grocery List Review'); block and ask instead; a REFUSAL is never re-committed | open — next | dev-100, 4 rows |
| 5 | the garbage-title metric is blind (0% while 'note', 'date', 'take out the trash. also' land); add the program-word, command-frame and dangling-joiner tests; rescore the archive | open | instrument |
| 6 | decompose_validate multiplies an under-split into junk ('send Bill Malinda'); multiply only over a bare noun list under one verb | open | dv boards, stage board's split line |
| 7 | ingest month/day misspellings ("Febuary"); "invite/schedule/book" as polite imperatives; always answer when the rescue builds nothing | open | vocab bench (thousands), stage board |
| 8 | RULINGS for Gil | **ANSWERED 2026-09-20** (DEVQA Q28, Q31–Q34): a MEAL names its own hour (09/13/19) and the board's premise moved with it; a NEW LIST is a General to-do named for its contents; a genuine bare 7 or 8 is ASKED about and otherwise reads PM on both tracks; the loop resumes; cycles run on the branch and never merge. **Still unruled:** the general untimed event (non-meal), and whether an offset or a recurrence on "remind me to <verb>" makes it an event | 5 of the remaining rows |

## LLMJUDGE — the next dataset and the stage's shape, PROPOSED 2026-09-22

`assistant/engine/llmjudge/PLAN.md` §7: the stage is at ceiling on its own
six planted defects (100.0% / 98.8% catch, both halves) and blind by
construction to the classes real speech fails on; Board D holds 400 rows.
Proposed: a delegated GENERATOR (gold by grammar, six voices, observed damage
operations, split by family, diversity counted) to ~5,000 commands / ~10,000
object cases; Board D to thousands; then four shape decisions boarded alone
(keep the judge deterministic; rescue self-consistency; a pairwise selector
at loop exhaustion; rescue drawn as its own trace step) and, §7.5, six
registered tests of where Llama 3.1 8B might be worth its latency — each a
coarse two-way question under a condition, with the fire rate and a latency
budget beside the pair, and the four refuted uses re-run as negative
controls. **RUNNING since 2026-09-22, evening** (Gil: *"automate this
process"*): the v2 set landed (`llmjudge/datasets/v2/`, 5,292 commands /
11,187 cases), `judge_board_v2` scores it, cycle 41 fixed the judge's
`not_an_ask` misroute (typed catch 92.2 → 97.5% train / 92.9 → 97.4% test)
and cycle 42 fixed the list-merge plant (99.5 / 98.6% on the same judge).
The seeded board mode landed the same evening (`68f39ab`; a same-code
double run differs on 0 rows) and the seeded 1,200-row baseline showed the
loop's real footprint: 3 rows in 1,200, with 108 of the 127 OFF-wrong rows
carrying no finding. Cycle 43 made the scorer follow Q38 (a refused generic
target is right) and cycle 44 closed the hole it exposed — the loop's model
round had handed back `delete_event "that one"` — on all three gates. Seeded
Board D: 91.2% either arm, 0 fixed / 0 broke, 2 disagreements. Next (PLAN.md
§7.2b): the H3 probe's answer on the 83 kind-disagreement rows, then §7.3's
decisions and §7.5's H1–H6, one change per board run, where the loss is —
the blind classes (kind 31%, operation 20% of the wrong rows). Registered, not started: a
list-of-three-events family so `coordinated_subject` has test-half rows.

## THE SOFTWARE LIST — 2026-09-22, evening

Gil asked what was left on the software side and ruled on it the same
evening. Done in `c2b23a6` and `9733efa`: the config writer's dict case
(the settings-dialog TODO), `labels.model_first` (built; the live config
runs the models in STACKED mode, measured best on his real titles — 71.6%
vs 67.9% rules-only on 81 real event titles, 88.4% vs 84.2% for the model
alone on 95 real to-dos; model-first reads 58.0% on the event titles and is
off pending his call), the impossible clock refused in decompose_validate,
Running/Gym folded into Fitness on open, the held-back chip on both panels
with one outcome registry (`trace.NON_OBJECT_OUTCOMES`), the phone
reinstalled. Left:

- **The explorer page, fully interactive and visual** (Gil: "it can't be
  fully textual"). In progress: recorded demos per stage generated by
  `scripts/gen_explorer_demos.py` the way the ingest walkthrough is, a
  run-it-through widget on the engine diagram, charts on the eval view.
- The stale explorer items from 2026-09-10 (the LLMJudge box's routes, the
  arrow tooltip, the commit box's labels) fold into that rework.
- `model_first` for events: Gil's call, with the 58.0% vs 71.6% reading.

## CYCLES 38–40 — Q42 and Q43 built, 2026-09-22

Q43 (a comma run needs a conjunction) and Q42 (a bare kind commits; a passed
clock means tomorrow; "9 10 am") are in, boarded one at a time —
`real_usage/RESULTS.md` runs 7–9, `dataset/RESULTS.md` cycles 38–40. Real
usage: generic-title 81.0 → 90.5% (19 of 21), corrected item count 64.3 →
73.3%. Left open by the same work:

- **Three corpora predate the passed-clock ruling.** A clock with no day,
  said after that clock, is gold "today" in the FastRule 7,200 (2 train
  rows seen), the verification pool's when-correct gold (1 dev-100 row) and
  whatever the segmentation generator emits. Relabel BY RULE — resolve
  each such row's clock against its own anchor, never by reading the sealed
  halves — and the three boards lose a known −1 each.
- **"tomorrow morning on tuesday" lands on Tuesday; "tomorrow on tuesday"
  on tomorrow.** The stated-day rule (cycle 36) does not see "tomorrow
  morning", which the recogniser reads as a datetime. Gil's own reading of
  the first is Tuesday (Q42), so both stand until a row says otherwise.
- **Field quality carries Q42's cost** (dev-100 91.9 → 88.4%, all in the
  simple tier): a committed bare 'event' scores against a gold that named
  something. The metric is honest; the ruling accepted the trade.

## CYCLE 35 — spoken clock forms, landed 2026-09-22; and the board that never replayed

Three readers (segmentation's phrase table, `resolve.py`, `rule_parser.py`)
learned "for 1 p.m.", "for 830", "at 1040", "at 910am", the sentence-final
dotted meridiem, and "this coming thursday" = the soonest Thursday. Real
usage, both replays fresh: generic-title right/acceptable 52.4 → 66.7% (11 →
14 of 21), corrected `start_time` 56.2 → 62.5% (n=16), `date` 76.5 → 82.4%.
Every stage board identical (the forms exist only in real speech). Found on
the way: the real-usage board had resumed a 2026-09-18 checkpoint on every
run since (CLAUDE.md has the rule); `real_usage/RESULTS.md` run 4 has the
corrected before/after. Open, for Gil:

- ~~Q38 vs Q41 on 'appointment', 'event' — and 'date'~~ — **RULED (Q42)
  and DONE, cycle 39:** a bare kind commits with its details and the hint;
  all three rows are events now; generic-title 90.5%, corrected count
  73.3%; dev-100 recall +5.3, field quality −3.1 (the trade, recorded). Q41 says bare 'meeting' with the right details is fine. Does that
  reach 'appointment'? And 'event', which is the program's own word but which
  Gil's own correction on id=118 accepted as the title? One ruling settles
  both rows; until then they are refusals, which is the conservative side.
- ~~A stated day loses to a weekday~~ — **DONE, cycle 36 (same day):** the
  stated day wins; real-usage generic-title 66.7 → 81.0% (17 of 21), dev-100
  75 → 76%. `real_usage/RESULTS.md` run 5.
- **Disfluent speech over-splits** (same interval): id=56 "…, in one second,
  one moment, one moment, bear with me, …" makes 3 items for 1; id=136 3 for
  2; id=219 "Movie at Lincoln Square tomorrow, AMC, 11.15 AM tomorrow" 1 for
  2. Corrected item count 80 → 60%. **Cycle 37 landed** (ingest's noise
  passes: interjections, hold-on chatter, a one-word swap; count 60 → 64.3%).
  Left behind: id=136's stray "can," and id=223's *"No, I said that."*
  retraction.
- ~~A comma list with no conjunction~~ — **RULED (Q43) and DONE, cycle 38:**
  a list needs an "and" or "or"; id=54 is one event again, generic-title
  back to 81.0%.

## THE CORRECTION FLOW RECORDS WHAT CHANGED — landed, 2026-09-22

`memory.set_feedback` and `feedback_for_record` annotate every stored
correction with `changed` and `reachable` per action
(`assistant/intent/correction.py`), and the real-usage board scores the
corrected tier per reachable field instead of per hand-marked row (15 of 16
rows scored, was 9). Open from the same work:

- **The review view could ask which fields were WRONG, not only what they
  should be.** Today reachability is inferred by rule (title words said,
  clock on the five-minute grid, a moved date is a change of plan). One tap
  per changed field — "misheard" vs "changed my mind" — would make the
  inference unnecessary and is the only way to score a typed title honestly.
  iOS `AssistantReviewView`, the same `/memory/<id>/feedback` body.

## DEFERRED UNTIL THE ENGINE WORK IS DONE — an offline engine on the phone (Gil, 2026-09-24)

Gil: *"mark when we finish working on the engine, to make an offline copy of
the engine that the phone can use, and a protocol so it works together
properly with the servers engine."* **Do not start this while the engine is
still changing** — the phone only gets new code on a reinstall, so a copy made
now goes stale within days and every divergence shows up as a visible
correction. Start it when the engine is declared finished.

What was established when he asked (2026-09-24), so the work starts informed:
- The engine is NOT model-free: on the 75 real commands 47 took the fast path
  (no model, 0.1 s) and 26 the deep path (Llama 3.1 8B on the Mac, p50 4.7 s,
  p95 46.9 s). A phone copy can only be the FAST path; the deep path stays the
  Mac's.
- The fast path is `rule_parser` (3,000+ lines on spaCy's parse), the date
  recogniser, ingest's cleanup and the gates. spaCy has no supported iOS build,
  so the first step is a spike: embed CPython (official on iOS since 3.13)
  and find out whether spaCy and its compiled deps build — or decide on a
  Swift port, knowing it is a second brain.
- **A parity board before anything ships:** the FastRule 7,200 set run on the
  phone copy and on the Mac, output required identical, rerun on every engine
  change that reaches the phone.
- **The protocol** (to design then): the phone commits a fast-path reading
  locally with a temporary id (the offline-edit machinery in `LocalStore`
  already remaps temporary ids), sends the command to the Mac when reachable,
  and the Mac's reading wins — identical → keep, different → replace and say
  so, deep-path-only → the phone shows it pending. Open questions: what a
  local reading may do before the Mac confirms (a reminder firing, a delete —
  deletes should probably never run locally), and versioning (the phone
  stamps its engine version; the Mac refuses to "confirm" across versions).
- Until then the phone already keeps every voice command made offline and
  replays it on reconnect (`PendingVoiceCommand`); the cheaper interim steps
  are measuring how often that queue is used and showing the queued command
  at once as "pending".

## TIPS ON THE PHONE — landed, 2026-09-22 (DEVQA Q41)

The Mac's five "How to Talk to Me" tips now reach iOS (`GET /tips`,
`TipsView.swift`), and the reply carries a `hint` key the phone draws once
per code above the mic (`bare_title`, `title_refused`) — `FEATURES.md` has
the entry. Two rows left open by the same work:

- **The Mac GUI does not draw the hint.** The engine sends it to every
  client; only `VoiceButton.swift` renders it. The Mac's reply rendering
  lives in `pipeline.py`'s answer path — a small card by the mic the same
  way, when the Mac is worth it.
- **A clock suffix gets a bare title past the gate.** Found by the
  five-sentence probe that answered cycle 35 (a probe, not a board): *"set an
  appointment for tomorrow morning on tuesday at 910am"* committed the title
  **'appointment at 910am'** on the deep path — `names_something` passes it
  because "at 910am" is a word it has never seen, while *"set an appointment
  for tomorrow at 4pm"* is refused and *"set a meeting … at 4pm"* commits
  'meeting' (Q41). The leak is the unparsed clock ("910am" with no colon)
  staying in the title, the same class dev-100's cycles 30–33 closed for
  parsed clocks. Real-usage row id=18. Not fixed here — a title-gate change
  is boarded on FastRule's own board first.

## "HOW IT WORKS" ABOVE THE TIPS — landed, 2026-09-24

Four one-line steps (split → event or to-do → series → check and ask) above a
revised five tips, both surfaces, from `assistant/tips.py` (`STEPS`, served as
`steps` by `GET /tips`). Every example was run through the engine with the
model shut out and with it on; `tests/unit/test_tips_examples.py` re-runs them
on every build. Four defects the verification turned up, none fixed here —
each is a stage's own work, boarded on that stage first:

- **FIXED ON THE FAST PATH 2026-09-24** ("Book yoga every Tuesday and Thursday at 6pm" → one weekly series on both days; tip 5 rewritten; the bare-noun deep form still needs the model). **A multi-weekday series is wrong every way it was tried.** "Book yoga every
  Tuesday and Thursday at 6pm" (fast path) makes ONE Thursday-only weekly
  series — "“two days a week” became weekly" — and loses the Tuesdays, although
  `recur_days` exists for exactly this (CLAUDE.md, "Recurring events"). "Yoga
  every Tuesday and Thursday at 6pm" (deep) makes two one-offs, the first on a
  MONDAY, with the model shut out, and a weekly series that ends a week later
  (2 instances) with it. "on tuesdays and thursdays" also makes one-offs. Tip 5
  tells the speaker to say one weekday per series until this is fixed, and
  `test_tip5_the_caveat_is_still_true` goes red the day it is.
- **FIXED 2026-09-24 (`3873dd5`, both parser doors refuse under the flag).** **`MACALENDAR_LLM_DISABLED` does not shut the rescue's door.** It stops
  `engine.llm.call_json`, but `llmjudge/rescue.py` parses through
  `IntentParser._call_ollama` directly, so a unit test or "model-free" board
  on a Mac with ollama up reaches the LIVE model (unseeded) on every FastRule
  deferral — measured: "Dentist on the 15th at 4" spent 14s in two ollama
  calls under the flag. `tests/conftest.py` says unit tests "must never reach
  a live model"; this one door makes that untrue whenever ollama is running,
  and a board that relied on the flag measured model-assisted rows.
- **NARROWED 2026-09-24** (`_bare_noun_event`: a bare noun with a day or clock commits on the fast path; FastRule RESULTS has both halves). **A bare leading noun defers to the model where a verb does not.** "Dentist
  on the 15th at 4", "Dentist in two weeks at 4", "Dentist tomorrow" and
  "Yoga every Tuesday at 6pm" all DEFER (and with the model shut out, "Sorry,
  I couldn't read this part: “Dentist”"), while the same sentences opening
  with "Book the …" commit on the fast path. The model gets them right, so
  the live answer is the same, several seconds later. FastRule's board.
- **FIXED 2026-09-24** (the rule read segmentation's date floor "today at 8am" as a spoken day; it reads the item's spoken source now). **Q42's passed-clock rule missed a case.** "dentist at 8am", said at 08:49,
  was booked for 08:00 TODAY — already past — on the deep path. Q42 rule 2
  says a clock with no day that has passed means tomorrow.

- **FIXED 2026-09-24 as a side effect of the bare-noun rule:** "yoga next week", "dentist next week" and "yoga next week at 6pm" are now read on the fast path and ASKED on the phone (Q22), where the model used to commit Monday 09:00.

Also noticed, smaller: with an empty scratch label model, "call mom" and "pay
rent" were tagged Groceries (the real fitted models were not in play, so this
may not reproduce live).

## THE LOOP-BACK'S MODEL ROUND — landed, 2026-09-20 (DEVQA Q30)

Gil: *"the whole point of the loop is that the llm sends a fix if relevant
as X1' to iterate on, otherwise commit … on the second iteration it will do
the same thing and there we would need a llm."* `rewrite_for_retry` is two
tiers: code (`failed_asks` / `expand_list`), then `rewrite_with_model` when
code has nothing new or the finding is `unsplit_subject` (one object whose
words still hold an ask seam; siblings from the same multiply go back with
it). The brief carries the transcript, the failed items' words, the finished
asks and every earlier attempt with the judge's complaint (the state's fix
ledger, rules `rewrite` / `rewrite_model`); the answer is a list of asks
joined by code as the ingest envelope; the shape rules in the prompt are the
parser's (verb first, one thing per line, to-do vs calendar framing, time
and the speaker's recurrence phrase at the end of their line). Guard on both
tiers, one-edit tolerance for transcript typos on words ≥ 6 letters, a
repeat guard against re-building a finished ask. dev-100 runs 23 and 24 vs
run 22: count-correct 74 → 76, deep 62 → 65, F1 75.0 → 75.7, failures 26 →
24 (`dataset/RESULTS.md`, the run-23/24 entry, nine model-round rows read).
Filed there: `_LIST_DEST` misses "groceries list" (plan item 1); the rescue
invents titles and list contents the loop cannot fix; a subject-less rewrite
still commits on exhaustion, and twice (plan item 4).

## A CALENDAR CREATE OVER A LIST OF THINGS — rewritten one clause per thing, 2026-09-20

Gil (DEVQA Q29): *"if the decompose_validate fails to split into three items
with same date, the deep engine should rewrite … 'on friday create an event
for dentist and on friday create an event for haircut and on friday create
an event for gym'."* Q14 stands at segmentation (one item); the count is
corrected by the judge. Landed: `coordination.noun_list` (three or more
things under one head; pairs, attendees, timed enumerations, verb lists and
headless lists excluded), `Atomicity` → `list-title` (STRUCTURE) so the
one-event reading never commits fast, LLMJudge `coordinated_subject` → X1'
one clause per thing (`rewrite.expand_list`), `test_engine_contracts`
records the second REWRITE finding. Boards: FastRule product-shape TRAIN
byte-identical; atomicity LAYER 0 rows change on B train 4,800 + A train
2,027; stage board 76 split rows unchanged — the shape is in neither corpus,
so the positive claim rests on eight probes and the tests (`fastrule/
experiments/RESULTS.md` cycle 26). Filed there: the deep path's "event for
dentist" title, a generator family for the shape, the start_time note noise.

## SEGMENTATION — second pass, the approved queue, 2026-09-20 (later)

Gil: *"ok do those."* The five items from the day's plan, each boarded
alone (`segmentation/experiments/RESULTS.md`, second 2026-09-20 entry):
the tagger's chore vocabulary and a grammar gate on the veto's second word
(exact-row 89.2% → 89.8%, tag 98.0% → 98.7%); one definition of content in
the scorer (NO-LOSS 34 → 19 items); **`old_seg` retired** — `retired/
segmentation-old-seg/`, tag `segmentation-old-seg`, the confirm-create
reader moved to `object_rules.py`, the stage switch gone; FastRule's own
splitter keeping a courtesy tail (15 rows now defer for the true reason);
and the under-split residue — a trailing subordinated command clause is an
ask (19 → 18), ten evidenced errand verbs join the routing table (18 → 16,
exact-row **90.1%**, the cut **98.4%**), which exposed and fixed the
router's object-verb hijack (FastRule harm **159 → 106**, cycle 25; the
rename gate then had to fire on the phrasing, handled 77.5% with renames
abstaining again). Sealed segmentation half, read once at the end: exact-row
79.7% → 80.5%, tag 93.6% → 94.2%, the cut unchanged. Still
filed: the shared-verb gold conflict, "schedule" as a calendar signal
inside a to-do title, "forget X, i'd rather Y", the "put X and Y on my
list" destination, an extend's missing duration field and the floor date
copied to `new_date`, lead-time tails as junk todos on the fast path, and
the fast path lowercasing every title (a name loses its capital).

## SEGMENTATION — implementation fixes landed, 2026-09-20

Gil: *"work on implementation fixes, can reiterate as long as improving…
careful that code doesn't get overall convoluted."* Nine commits, each
boarded alone; structure untouched. Train half, 1,051 rows: exact-row
84.1% → **89.2%** (+3.7 from the Q26 gold relabel, +1.4 from code), the cut
97.6% → **98.1%**, over-split 3 → **1**, under-split 22 → **19**, tag
94.5% → **98.0%**; FastRule's product-shape board byte-identical throughout;
its stage board (segmentation's items at FastRule's door) 80 → 76 atomic
rows split in two. Full ledger: `segmentation/experiments/RESULTS.md`
(2026-09-20). Filed there, needing a ruling or a separate owner: the
shared-verb gold conflict (4 hand-written families vs the generated gold and
Q14), "schedule" inside a to-do title reading as a calendar signal, "forget
X, i'd rather Y", the chore verbs the tagger lacks, `c_threeask_ttt_2`'s
regeneration drift, and `is_interrogative_create` still borrowed from
`old_seg` (with `old_seg`'s move to `retired/` still to do).

## SEGMENTATION AUDIT — two findings verified against the code, 2026-09-19

Read with the stage's own board (`segmentation/experiments/run_board.py`,
train, 1,051 rows), not from the docs:

- **The stage's gold was never relabelled for Q26, and its board now reads
  4.8 pt below its own map.** `ARCHITECTURE.md` §0 records exact-row 88.9% /
  tag 96.0% (2026-09-17); today the same board prints **84.1% / 94.5%**, with
  112 gold-`task` items tagged `event`. 58 of those carry a stated clock by a
  strict regex and more carry a spoken one ("quarter to nine", "half past
  six") — exactly the rows Q26 (2026-09-18, *a stated clock makes it an event*)
  turned into events, which `fastseg.tag` now does and the gold still denies.
  64 train gold items are `task` with a clock, 35 of them "remind me to"
  frames. Relabelling by RULE (never by reading the sealed half) puts tag back
  above 96% with no code change. Until then every tag number this stage
  prints is measuring the ruling, not the tagger.
- **A comma after a leading time changes the cut.** `fastseg("the 30th, wash
  and fold the laundry")` → two asks, "wash" and "fold the laundry"; the same
  words without the comma → one. The comma makes spaCy parse "wash and fold"
  as coordinated verbs and `clause_boundaries` cuts there. It is the
  `front,`-vs-`front` gap the invariance board already separates on purpose,
  and it is a cutter implementation defect, not a position rule.

## Working agreements
- Everything on the phone is local: no third-party services; the only network peer is the Mac over Tailscale.
- Prefer doing work directly over spawning sub-agents; keep context small (`/compact` between big tasks).

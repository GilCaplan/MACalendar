# MACalendar — System Overview

| Platform | Doc |
|----------|-----|
| **Mac App** (PyQt6 voice assistant) | [SYSTEM_MAC.md](SYSTEM_MAC.md) |
| **iPhone App** (SwiftUI + Flask API) | [SYSTEM_IPHONE.md](SYSTEM_IPHONE.md) |
| **Code map** (file + line pointers for every subsystem) | [CODE_MAP.md](CODE_MAP.md) |

## For AI Agents Working on This Repo

Before fixing a bug or adding a feature, **read `CODE_MAP.md`** — it has precise file+line pointers for every subsystem so you can jump straight to relevant code without broad codebase searches.

**When to update `CODE_MAP.md`:** After touching a file in a non-trivial way (new class, moved method, changed a key line), update the relevant table row. Do this only for the specific rows that changed — don't rewrite the whole file. Skip it for cosmetic or one-liner fixes.

**Don't over-document:** Only record things that are *surprising*, *non-obvious*, or *hard to find by name search*. Common patterns, obvious method names, and things grep finds in one try don't need a pointer.

## The shape of it — one brain, two clients

`assistant.api` is the front door and `assistant.engine` is the brain. **The
Mac GUI is a client of the API exactly as the phone is**: `assistant/pipeline.py`
records audio, transcribes it, and POSTs the transcript to
`http://127.0.0.1:<port>/voice/text` (`pipeline.py:469`) — it holds no parser of
its own (`pipeline.py:74`: *"Kept only for health_check(); this process does not
parse any more"*). `source` — `"mac"` or `"ios"` — is the only difference
between the two, and it only labels the trace, the vocabulary corrections and
the command memory.

Four processes run on the Mac, all started by `Launch Calendar.command`:

    ollama serve                      the model, localhost:11434   (line 75)
    python -m assistant.api           the brain, 0.0.0.0:8080      (line 97)
    python -m assistant.thinking_hud  the floating card            (line 104)
    python -m assistant.main          the calendar GUI             (line 119)

The HUD talks to none of them: it tails `trace_bus.jsonl`. That is what lets it
float over a full-screen app with the calendar closed.

**`confirmation_level` no longer has any effect.** The dialog belonged between
parse and execute, and both now happen in a process with no screen; the GUI
warns at startup if it is above 0 (`pipeline.py:81-88`). The Mac settings dialog
still renders an "Auto-approve actions (no confirmations)" checkbox bound to it
(`assistant/calendar_ui/settings_dialog.py:418-427`, persisted at `:555/:607`),
so today the setting is a control that changes nothing — worth knowing before
someone trusts it.

## Quick Facts
- **DB**: `~/.assistant_tools/calendar.db` (SQLite, Mac is source of truth)
- **GitHub**: `https://github.com/GilCaplan/MACalendar`
- **Mac launch**: `python -m assistant.main` or `Launch Calendar.command`
- **iPhone API**: `python -m assistant.api --tailscale` (auto-started by `Launch Calendar.command`)
- **Thinking HUD**: `python -m assistant.thinking_hud` (auto-started too) — an always-on-top card, deliberately its own app rather than part of the calendar window, so a command given from the phone is visible in whatever you were actually working in. Fed by `assistant/trace_bus.py`; never takes focus. Three views: the live timeline, **History**, and an **LLM console** (`assistant/llm_bus.py`, added 2026-09-13) that logs every Ollama call with its caller — see *The trace bus* below
- **LLM engine**: configured via `config.yaml` → `llm_engine` (ollama/openai/gemini/claude)
- **NLU Tracking**: `DOCUMENTATION/NLU_TRACKING.md` — auto-appended after every action (success + failure) from both Mac and iOS, labelled by parse path and source. Written by the engine (`assistant/engine/__init__.py:997 _log_nlu`, on a daemon thread) through `Pipeline._append_nlu_log`; `source == "test"` is skipped, because the audit's synthetic commands would drown the record of real usage
- **Scenario Bugs**: `DOCUMENTATION/SCENARIO_BUG.md` — **no longer written.** `Pipeline._append_scenario_bug` (`assistant/pipeline.py:565`) still exists but has no caller anywhere in `assistant/` (its only other mention is a docstring at `:617`), and the last entry in the file is dated 2026-09-04, from the old brain's self-check. Read it as an archive, not a live feed; failures are in NLU_TRACKING.md and the command memory
- **Cross-Platform Sync**: Tasks and recurring events synchronized between Mac (PyQt) and iOS (SwiftUI).
- **Customizable Appearance**: Persistent Dark/Light mode and granular font size controls for all calendar views (Month, Week, Day, Tasks).
- **Dynamic Density**: Interactive "stretch/tighten" Settings dialog on Mac with a dedicated "Compact Layout" toggle.
- **Smart Recurrence**: Edit whole series or single instances with an intuitive prompt.
- **Task Management**: Native drag-and-drop reordering on both platforms.

## Models

Three, all local: Whisper `base` for speech, spaCy `en_core_web_sm` for the
grammar the rule parser reads, and Llama 3.1 8B in Ollama for meaning. The 8B
model does six distinct jobs, only three of which are on the path between
speaking and seeing the result. No embedding model; no classifier model.
Full table, including which config key sets each and why the sizes were chosen:
`DOCUMENTATION/MODELS.md`.

## NLU Parse Path — the engine (`assistant/engine/`, contracts in [ENGINE.md](ENGINE.md))

`BRAIN_VERSION` is **`engine-v3`** (`assistant/trace.py:22`) — the 2026-09-08
rewire. The stage names below are `assistant/engine/state.py:26-34`, which is
the authoritative list; the orchestrator is `assistant/engine/__init__.py:95-160`
(construction) and `:285-404` (one run).

```
Voice command  (Mac GUI and iPhone both POST /voice/text — same brain, same path)
  → ingest              queued recordings coalesce; personal vocabulary repairs
    · transcript        the repair half. Runs ONCE, OUTSIDE the re-runnable
                        chain — re-running it would re-repair repaired words
       ├─ nothing said      → parse="ignored": not executed, not remembered
       └─ a doubted word    → parse="needs_edit": the client shows an editor
                              and resubmits; nothing runs on doubted text
  → fast track?         FastRule confident on the WHOLE input
                        (RULE_THRESHOLD 0.80, `assistant/intent/rule_parser.py:102`)
       ├─ yes → commit instantly, then a background review behind the answer
       └─ no  → deep track in the foreground, streamed to the HUD:
            segment              split into typed items (event / task / review)
            decompose_validate   resolve every field from the item's own words,
                                 repair, observance gate; FLAGS what it cannot
                                 settle rather than blocking
            fastrule             each atomic item → a calendar / to-do object
              └─ an interrogative create → parse="confirm_create": offered,
                                 not run (DEVQA Q9) — this gate sits between
                                 parse and judge, so nothing is judged that
                                 will only ever be proposed
            llmjudge             raw text vs. produced objects
  → commit              write AND label in one step, so a row cannot land
                        unlabelled (`assistant/engine/__init__.py:122-124`)
```

`parse` on the response is `"fast" | "deep" | "error" | "ignored"`
(`state.py:195`), plus `"needs_edit"` and `"confirm_create"` from the two gates
and `"oneshot"` from the parallel engine below. The old `"rule" / "hybrid" /
"llm"` vocabulary is pre-engine and no longer emitted anywhere.

**The judge's loop-back is wired but INERT.** `llmjudge.rewrite_for_retry`
(`assistant/engine/llmjudge/llmjudge.py:254`) returns `None` on purpose: FastSeg
is deterministic and LLMSeg is off, so re-entering segmentation with unchanged
text can only produce the same answer — real usage on 2026-09-08 looped three
times to an identical result and apologised after 30 seconds. No rewrite, no
loop. The contract and its single call site exist so implementing it later is
filling in one function.

**A parallel one-shot engine** lives at `assistant/engine/LLM_one_shot/` and is
off unless `MACALENDAR_ONESHOT=1` (`assistant/engine/__init__.py:322`). It
replaces the whole chain with one schema-constrained model call and commits
through the same `_commit`, so the only difference between the two runs is how
the objects were decided — which makes it an instrument for "does the six-stage
chain earn its complexity?". Measured 2026-09-13/14 by the checkpoint sweep:

- **sealed 300** (`dataset/inputs/test_split.json`), count-correctness:
  one-shot **66.0%** vs `main` **77.3%**
  (`dataset/runs/checkpoint-sweep-oneshot-sealed/manifest.json`,
  fingerprint `6dc8c8674e39:300`).
- **personas 300**, count-correctness: one-shot **50.3%** vs `main` **79.3%**
  (`dataset/runs/checkpoint-sweep-personas-v2/manifest.json`, fingerprint
  `1a3064b09c1c:300`).

Meaning: on the same rows, one model call gets the *number of things asked for*
right about 11 points less often than the chain on the sealed set and 29 points
less often on the persona voices. Both boards are `split:"test"` — they are
**retrospective only** and may never pick the next thing to work on.

## The trace bus — how the HUD sees a command it did not run

`~/.assistant_tools/trace_bus.jsonl` (override: `MACALENDAR_TRACE_BUS`) is a
small append-only file the three processes share: producers publish, the HUD
tails it. It carries two shapes of line —

    {"kind": "trace",  "run": …, "source": …, "steps": [...], "result": {}}
    {"kind": "begin",  …}  {"kind": "step", …}  {"kind": "result", …}

— and **since 2026-09-14 (`003330b`) every run writes both.** Before that the
streaming lines were hooked only when a caller supplied a `trace_run`, which
only the Mac GUI ever did: across the bus's entire eight-day recorded history
there was not one `begin` line, for any surface. A phone command published
nothing for its whole 4–40 seconds and then appeared, already finished, in a
single line. The engine now mints its own run id when the caller has none
(`assistant/engine/__init__.py:244-257`), so the card's live chain rail finally
fills in as the command runs.

The whole-run `trace` line is still written at the end, sharing **one** run id,
because `read_history` returns only that shape and the History view would
otherwise empty out; the HUD dedups on the id so a streamed run renders once.
`MAX_ENTRIES` moved 200 → 2000 with the change (`assistant/trace_bus.py:52`) —
the budget counts LINES, and a streamed run occupies about ten where it used to
occupy one.

The **LLM console** is a second, deliberately separate stream
(`assistant/llm_bus.py`, `~/.assistant_tools/llm_calls.jsonl`, override
`MACALENDAR_LLM_BUS`, its own 400-line budget): one line per Ollama call with
its caller, transport and duration. It is not in the trace bus because the HUD
holds one current run and one file offset, and interleaved model calls would
tear the timeline and evict finished runs from the shared trim budget. It logs
prompts and responses verbatim, so it is personal data — hence the separate
override, and `source: "test"` traffic is dropped (`llm_bus.py:58, 90`).

## Log prefixes
- `🖥️` — Mac app logs (pipeline, audio, STT, LLM, actions)
- `📱` — iPhone API logs (audio received, transcript, parsed actions, response)

## Personalisation layer (added 2026-08-26)

| Piece | File | What it does |
|---|---|---|
| Vocabulary | `assistant/stt/vocab.py` | Personal words (names, Hebrew, places). Fed to Whisper as `initial_prompt`; transcripts auto-corrected via learned aliases + fuzzy match (difflib ≥ 0.80, protected common words). Every fuzzy fix is remembered as an alias. Store: `~/.assistant_tools/vocab.json` (local only). |
| Onboarding | `assistant/stt/vocab_onboarding.py` | First-run interview (6 questions) + opt-in starter packs (prayer/Shabbat, holidays, Israeli life, family, life events). iOS `VocabOnboardingView`, Mac `VocabDialog › Set up…`. |
| Command memory (RAG) | `assistant/intent/memory.py` | Every command → executed intents → result → timings in `~/.assistant_tools/nlu_memory.db`. Edits/deletes of a voice-created record within 24 h become `corrected`/`rejected` feedback (hooked in `db.update_event/delete_event/update_todo/delete_todo`). `few_shot_block()` can inject the k most similar examples (dates masked) into the LLM system prompt — but **`nlu.memory_examples` is `0` in both the default (`assistant/config.py:237`) and `config.example.yaml:188`, so no few-shot block is injected today**. The config's own comment says why: *"run 7 measured no effect at k=4, so the engine ships with it off"* (`config.example.yaml:188-189`). Also holds the **pending queue** of commands that failed because the LLM was offline; the API server retries them every 30 s. |
| Trace | `assistant/trace.py` | Stage-by-stage "thinking" log with ms timings, plus the two things the review panel is pinned to: `BRAIN_VERSION` (stamped on every response) and `CHAINS`, the ordered `(stage, label)` spec per version. Returned in `/voice` responses, streamed live as NDJSON from `POST /voice/stream` (iOS `ThinkingView`, toggle in Settings › Voice), and published to the trace bus — see above. |
| Self-check | `assistant/engine/llmjudge/llmjudge.py` | The engine's cross-check: the LLM lists what the raw text mentions, code diffs that against what was produced, and a deterministic router blames the stage to re-run. Behind a fast commit it runs as a background review (`assistant/engine/__init__.py:565 _start_background_verify`) with three tiers: a placeholder title is **renamed in place**; a missing ask and an extra row are **advisory only** — they say *"Worth a look: …"* and change nothing — unless `self_check_apply` is on, and it is `false` in both `assistant/config.py:286` and `config.example.yaml:95`. That default is deliberate: the always-on verifier proposed far more than it fixed, and four commands were broken by confident duplicate adds ("add eggs" against an existing "buy eggs"). A `verify_token` is issued on every fast commit (`__init__.py:594`) and both clients poll `GET /voice/verify/<token>` for the outcome. |
| Benchmark | `scripts/benchmark_models.py` → `DOCUMENTATION/MODEL_BENCHMARK.md` | Accuracy + latency of Ollama models on real commands. |

New endpoints: `GET/POST /vocab`, `POST /vocab/alias`, `DELETE /vocab/<word>[?alias=]`, `PATCH /vocab/settings`, `POST /vocab/preview`, `GET/POST /vocab/onboarding`, `GET /memory`, `GET /memory/similar?q=`, `POST /memory/<id>/feedback`, `DELETE /memory/<id>`, `GET /pending`, `POST /pending/<id>/retry`, `DELETE /pending/<id>`, `POST /voice/stream`. `/health` now reports `llm_status` (`ok` / `offline` / model not pulled).

Speed: Ollama `keep_alive` (`-1` = keep loaded forever, or e.g. `"30m"`; `config.yaml` currently uses `30m`) + startup warm-up of Whisper, spaCy and the LLM (`warm_up_components`) remove the cold-start cost that made the first phone command take 10–20 s.

## Event categories & colours

`assistant/actions/calendar/categories.py` tags every new event (Work, Study, Meeting, Social, Family, Prayer, Fitness, Health, Errand, Meal, Travel, Personal) from its title/attendees/location with a keyword classifier — "Personal" when unsure — and picks the category colour. If the event immediately before or after on the same day already has that colour, the category's alternate shade is used, so two adjacent events never look the same. A colour chosen by hand is never overridden. Users add/remove categories, change colours and keywords from iOS → Settings → *Event colours* (stored in `~/.assistant_tools/categories.json`, local only). API: `GET/POST /categories`, `DELETE /categories/<name>`, `POST /categories/classify`, `POST /categories/recolor[?force=1]` (backfills existing events).

## Sync between Mac and phone

Both apps read and write the same SQLite file (`~/.assistant_tools/calendar.db`) — the phone through the Mac's API. The Mac app polls the DB's modification time every 5 s and reloads calendar, tasks and the Timer tab when it changes. The phone polls every 30 s while idle, and drops to **1 s for 45 s after a voice command** (10 s after a manual edit) via `APIClient.burstRefresh`, so both sides settle together; the Timer tab polls every 3 s while any timer is running.

## Guests and invitations

`attendees` on an event is a comma-separated list of names (the voice assistant fills it from "meeting with Noa"). On the phone, Edit Event → Guests looks up each name in the phone's own Contacts (permission asked once; nothing stored or uploaded) and offers Messages (`sms:`), WhatsApp (`wa.me`), Mail (`mailto:`) or a share sheet with an `.ics` file. There is no server-side mail/SMS integration and no online dependency.

## Recording controls (phone)

Recording stops on tap, on a stop word or after silence (Settings → Voice; the silence auto-stop can be turned off). The stop words are `execute · done · go · stop · submit · confirm` (`Voice/VoiceRecorder.swift:16`), of which `execute`, `submit` and `confirm` are treated as unambiguous and fire immediately (`:134`). With "Ask before sending" on, a Redo / Add more / Send bar appears for **3 s** (`Views/VoiceButton.swift:270`) — *Add more* resumes the same recording so a sentence cut off early can be finished. A **stop word skips the bar entirely** (`VoiceButton.swift:266`): saying "execute" is the decision, so making the speaker wait out a countdown they just talked past would be silly.

## Referring to events by voice

**This moved out of the API layer.** `_normalise_intents` no longer exists in
`assistant/api/server.py` — targeting is now a set of named rules inside the
engine, at `assistant/engine/decompose_validate/targeting.py`, which is where a
rule about *which existing record the speaker meant* belongs (`server.py` is
HTTP; the brain is `assistant/engine/`). Same three behaviours:

- "the one I just made / the last one" stays an **anaphor** and is never turned
  into a title guess (`targeting.py:102 _rule_anaphor_guard`); the anaphor is
  resolved against `ContextMemory.last_event_id`.
- a weekday named in the sentence fills `match_date` (`targeting.py:111-113`),
  so "fix the meeting on Sunday" cannot land on a different day's meeting.
- a sentence that asked to **remove** cannot come back as a create
  (`targeting.py:182 _rule_create_from_remove_guard`).

`_find_event` (`assistant/actions/calendar/action.py:371`) then scores only
distinctive title words: when every word left after stop-word filtering is in
`_GENERIC_TITLE_WORDS` — "meeting", "event", "call", a weekday, a month — the
title carries no identity signal and the lookup falls back to date/time instead
of picking an arbitrary row.

## Training plans around Shabbat and the chagim (added 2026-09-01)

| Piece | File | What it does |
|---|---|---|
| Observance rules | `assistant/observance.py` | Answers "may I train on this day, and when?" — distinct from `hebrew_calendar.py`, which answers "what is this day called?" for display. Classifies Shabbat, yom tov, chol hamoed and fasts, and returns the run-able `TimeWindow`s for a date. Sunset/nightfall via `astral` (pure Python, offline); location and buffers from `config.yaml › observance`. |
| Scheduler | `assistant/workout_plan.py` | Places `SessionSpec`s on legal dates and materialises them into calendar events. Holds *training policy* (the arguable half) as distinct from observance (the computed half). |
| Program content | `assistant/programs/` | Session content with *preferred* dates only. `autumn_5k.py` is the 2 Sep – 17 Oct 2026 base block ending in a 5K time trial. |
| AI entry point | `assistant/actions/schedule_workout/` | "add an easy 8k Thursday morning", "plan four more weeks". The LLM proposes dated sessions; every date is re-placed by the scheduler before it reaches the calendar. |
| Seeding | `scripts/seed_running_plan.py` | Previews a block by default; `--commit` writes it, `--replace` re-seeds without duplicating. |

**The distinction that makes this work.** `hebrew_calendar.enumerate_holidays()` collapses consecutive days sharing a name into one span, so Sukkot 2026 comes back as a single block from 25 Sep to 2 Oct. Scheduling against that would blank out all of chol hamoed — the freest training week of the autumn. `observance.py` instead uses `HebrewDate.festival(israel=True, include_working_days=False)`, which names a day only when work is forbidden and returns `None` on chol hamoed, Chanukah and Purim.

**The evening belongs to the next day.** A civil date is modelled as two independently governed slots: its daylight, governed by itself, and its evening, governed by the *following* date. That is why motzei Shabbat is available on Sat 3 Oct 2026 (Shmini Atzeret ends) but not on Sat 12 Sep 2026 (Rosh Hashanah II follows).

**Yom Kippur is both a festival and a fast.** pyluach files it under `festival()` and returns `None` from `fast_day()`; `observance.fast_day_name()` normalises it back so either question gets a true answer. Tisha B'Av is spelled `"9 of Av"`.

**Observance is computed, policy is arguable.** Only halacha lives in `observance.py`. "A minor fast is a full rest day", "motzei Shabbat is a last resort", "48 hours between hard sessions", "no heavy legs the day before a long run" are all `SchedulePolicy` in `workout_plan.py`, configurable and overridable. Keeping the line sharp is what lets the scheduler trust the observance answers absolutely — an LLM may propose dates, but placement is deterministic and re-validated.

**Running sessions.** `workout_template_sets` gained `distance_m` and `target_pace_sec_per_km` (set `type` `'distance'`), so an interval session reuses the existing block/set/session/log machinery — and the follow-along that rides on it — rather than duplicating it.

**The phone carries them too** (corrected 2026-09-14 — this paragraph used to
end "the iOS Swift models do not yet carry these fields", which was written at
14:35 on 2026-09-01 in `eb5ccb3` and was already false by 21:10 the same day,
when `d9ca532` shipped the other half). `SetType.distance` and the two fields
are in `MACalendar-iOS/MACalendar-iOS/Workout/WorkoutModels.swift:39,57,58` with
a `.distance(_:paceSecPerKm:)` constructor at `:91`, and they are not models-only:
`TemplateBuilderView.swift:412-442` builds distance sets, `LiveSessionView.swift:178-186`
runs them, `SessionHistoryView.swift:116-129` logs the actual distance and pace,
and `WorkoutStatsView.swift:75` charts them.

New endpoints: `GET /workout/plans`, `GET/DELETE /workout/plans/<id>`, `GET /workout/plan-items`, `PATCH /workout/plan-items/<id>`, `GET /observance?start_date=&end_date=` (per-day availability, so a client can show *why* a day is blocked without reimplementing the Hebrew calendar).

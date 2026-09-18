# Notifications — the plan

_2026-09-06, design panel. **Status, re-read against the code on 2026-09-14:
phases 1, 2 and 4 are SHIPPED and merged; phase 3 shipped its inline half
only; phase 5 is the live remainder.** Gil greenlit the build ("implement
when ready", same day) with one addition: per-category MUTE — `category_leads`
value 0 turns a whole category's notifications off, mirroring the event-level
0. Q4–Q6 were all answered later that same day and are recorded at the foot of
this file; the safe defaults the build shipped with survived all three. **One
design change since:** on 2026-09-11 Gil replaced the stream of pre-event
banners with a once-a-day DAY PANEL, so `notifications.pre_event` now ships
`false` and the per-event path is dormant rather than deleted (`4168dc4`) —
see "What changed after this plan was written". **The phone followed on
2026-09-17** (TASKS row 94): `ReminderScheduler` schedules panels instead of
per-event reminders, Settings shows one switch, and the phone lodges a WEEK of
panels ahead (`GET /digest/upcoming`) because iOS notifications are scheduled
rather than pushed — there is no server that can reach the phone at 07:00. The
per-event path is therefore dormant on the Mac and RETIRED on iOS:
`pre_event: true` would no longer bring the phone's banners back. Produced by a design panel (4 read-only code sweeps → 3
independent designs: iOS-first / server-first / UX-first → adversarial judge
+ synthesis). The winning skeleton is the UX-first design (thinnest client
data flow — `notify_at` embedded in event payloads, no second sync surface),
with the strongest mechanics grafted from the other two (motzei clamp,
`/changes`-token reschedule trigger, catch-up policy, NO_WARMUP gating)._

**Visual preview (what the user sees, both platforms + settings):**
https://claude.ai/code/artifact/07952f0f-f7cd-4390-891f-fedeb15a178c
_The preview shows some elements beyond this plan's v1 (morning digest,
night quiet, snooze) — those are tagged in the preview as later-phase or
proposals for Gil to keep or kill._ **One of the three landed:** the morning
digest is what shipped on 2026-09-11 as the day panel, and it did not stay a
later-phase extra — it replaced the headline feature. Night quiet and snooze
did not land, and snooze is still the one item in this file with no ruling
either way.

Line references in the DESIGN BODY below were verified read-only against both
trees on 2026-09-06 (recurrence instances are materialized rows; `PATCH
/config` exists; validate's `_EXCLUSIVE_END` regex reads a bare "before" as a
recurrence-end marker — which is why decompose must strip the reminder clause
first). Those references are eight days and 384 commits old
(`git rev-list --count 3e11b00..HEAD`) and several have moved; **the ledger in the next section carries the 2026-09-14 ones**,
and where the two disagree the ledger is the one that was re-read.

---

## Where this actually stands — verified 2026-09-14

Every row below was checked by opening the file, not by reading a tracker.
Line numbers are this checkout (`claude/codebase-ai-system-review-o2p8xu`,
36 commits ahead of `origin/main` and 3 behind it — `5623aba`, `4168dc4`,
`5561883`); the three facts that live only on `main` say so explicitly.

| Phase | State | Evidence re-read today |
|---|---|---|
| **1 — server policy core** | **SHIPPED** `a837345` (2026-09-06) | `assistant/notify.py`, 155 lines — `resolve_lead` :42, `notify_verdict` :108, `annotate` :144. `reminder_minutes` migration `db.py:128`; `reminder_log` table `db.py:253` with `log_reminder` :1082 / `reminder_logged` :1089; update allow-set `db.py:1182`. `NotificationsConfig` `config.py:210`, mirrored at `config.example.yaml:141`. Payloads annotated at `server.py:1227` and `:1236`; `"notifications"` is in `_ALLOWED_PATCH_KEYS` `server.py:1820`. |
| **2 — iOS lock screen** | **SHIPPED** `a0346b3` (2026-09-06) | `ReminderScheduler.swift`, 212 lines — `maxScheduled = 55` :29, `idPrefix = "evt-"` :34, `reconcile()` :51, `NotificationRouter: UNUserNotificationCenterDelegate` :188. Fields at `Models.swift:33,36,39` with coding keys :49-51. Reconcile is hooked where the plan said: `LocalStore.swift:119,162,183,189` (cache/insert/patch/remove), `ContentView.swift:341` (foreground) and `:430` (the `/changes` token branch), `SettingsView.swift:210`. Picker `EventDetailView.swift:124`; Reminders section `SettingsView.swift:199`. |
| **3 — voice** | **HALF SHIPPED** | The inline shape works; the standalone shape, the LLM schema field and the announced suppression do not. Detail under **Voice → "Which half shipped"** — this is the row the docs most often get wrong. |
| **4 — Mac banners** | **SHIPPED** `241f3c2` (2026-09-06) | `assistant/notifier.py`, 225 lines, started from `create_app()` at `server.py:428-429`. osascript delivery :81, optional `say` :89, catch-up window :153-154, trace-bus step published :96-112. Mac settings section `settings_dialog.py:220-333`, persisted :588-591. |
| **5 — hardening** | **PART DONE** | Live Activity shipped (`a4f1ee6`). Of the rest: the pre-Shabbat digest is CLOSED by ruling, and three items are genuinely open — `BGAppRefreshTask` (medium), the calendar-closed toggle + LaunchAgent (large, unblocked since 2026-09-06), and snooze (no ruling). See **Phase 5 — what is actually left**. |

### What changed after this plan was written

**The day panel replaced the pre-event stream (2026-09-11, `4168dc4`, on
`main`).** Gil: *"I want it to be more of a panel that nicely shows what i
have today and not when something is about to pop up."* One summary of today's
events and tasks at `notifications.digest_time` (07:00 local), on or off.

This is a real change to the feature's centre of gravity and it is not
optional reading for anyone working from this plan:

- `assistant/notify.py` grew `digest_time`, `digest_verdict`, `digest_lines`
  and `build_digest` (`main`:182-247+); the SERVER owns the wording, so the
  Mac banner and the phone would say the same sentence rather than each
  formatting its own.
- `GET /digest` exists (`main`, `server.py:1822`).
- `notifications.pre_event` ships **`false`** (`main`, `config.py:233`,
  `config.example.yaml`) and the notifier returns early when it is off
  (`main`, `notifier.py:264-265`). The per-event path is dormant, **not
  deleted**: `reminder_minutes` is still a frozen engine contract, "with a 15
  minute reminder" still parses and stores, and a test pins that flipping the
  flag restores the whole path.
- Held through Shabbat and yom tov on DEVQA Q6's ruling — a 07:00 panel on
  Shabbat morning is a notification on Shabbat whatever it summarises.
- **The iPhone half is not built** — TASKS row 84. The phone still schedules
  up to 55 per-event reminders and still shows lead-time controls; it needs to
  schedule ONE notification from `GET /digest` and show ONE toggle. The on/off
  already works through `PATCH /config`, so that is UI, not plumbing.
- **The Mac settings dialog does not expose it either**: `daily_digest` and
  `digest_time` appear nowhere in `settings_dialog.py` on `main`, so today
  they are config-file-only knobs.

One consequence for everything below: every per-event mechanism this plan
describes is still present and still correct, but it is **behind a flag that
ships off**. Read the pre-event sections as the design of a dormant path.

# SYNTHESIZED FINAL DESIGN — Pre-Event Notifications

**Design center:** the iPhone is the reliable ringer — it schedules absolute-time local notifications ahead from its offline event cache and fires with the app closed and the Mac asleep. The server (`assistant/notify.py`) is the single source of policy: it computes `notify_at` per event row and embeds it in every event payload. The Mac banner is a best-effort bonus while the calendar stack is up. No push, no internet, ever.

## Data model

**`events` table** (`assistant/db.py`, existing migration pattern near :108):
- `reminder_minutes INTEGER NULL` — `NULL` = inherit (category default, then global), `0` = explicitly none, `N>0` = fire N min before `start_time`. Events with no `start_time`: no reminder.
- Add `"reminder_minutes"` to the `update_event` allowed-set (db.py:1043 — unknown keys are silently dropped today). _Done; the set is now at `db.py:1182` in this checkout, `db.py:1149` on `main`._
- Series need nothing special: instances are rows (verified), each carries/inherits its own resolution.

**`reminder_log` table** (same DB — covered by `MACALENDAR_DB` override for free): `(event_id, fires_at, fired_at, outcome)` , unique `(event_id, fires_at)`, outcome ∈ `fired|suppressed|missed`. DB-backed because `--reload` restarts the API on every source edit; an in-memory fired-set re-fires constantly during development (C's insight).

**Intents** (`assistant/actions/calendar/intent.py`, `action.py:34-51`): `CalendarIntent.reminder_minutes: Optional[int]`, `UpdateEventIntent.new_reminder_minutes: Optional[int]`, mirrored into `CreateEventAction.parameters_schema` for the schema-constrained LLM path. Validate clamps to 0–1440. Pin the additions in `test_engine_contracts.py`'s field lists in the same change.
_Landed in part: `CalendarIntent.reminder_minutes` is `intent.py:28`. **`new_reminder_minutes` was never written** — `UpdateEventIntent` (`intent.py:193-209`) has no reminder field, and a repo-wide grep for the name hits only this document. **`CreateEventAction.parameters_schema` (`action.py:36-54`) does not carry it either**, so the schema-constrained LLM path cannot emit a reminder. And the contract pin never happened: `grep -i reminder tests/unit/test_engine_contracts.py` is empty._

**Config** (`assistant/config.py` `NotificationsConfig` beside `ObservanceConfig`; mirror into `config.example.yaml` next to `observance:` ~:123):

```yaml
notifications:
  enabled: true              # master switch; env MACALENDAR_NOTIFICATIONS=0 for harnesses
  default_lead_minutes: 0    # 0 = opt-in only (see Open Question 2)
  category_leads: {}         # e.g. Coursework: 60
  respect_observance: true   # quiet-window suppression/clamp
  catch_up_minutes: 10       # Mac: fire late if missed by <= this and event not started
  sound: true
  speak: false               # Mac only: also read via tts/speaker.py
```

_Shipped as designed (`config.py:210`, `config.example.yaml:141`), then
extended on 2026-09-11 by the day panel: `main` adds `daily_digest: true` and
`digest_time: "07:00"`, and adds `pre_event: false` in front of
`default_lead_minutes`/`category_leads`, which are now documented in the yaml
as "pre_event only"._

**iOS models** (`API/Models.swift`, `LocalStore.swift`): `CalendarEvent` gains `reminderMinutes: Int?`, `notifyAt: String?`, `notifySuppressedReason: String?` — all optional so existing `mc_events.json` caches decode unchanged.

## Endpoint contracts (all additive; run `python scripts/gen_api_reference.py` after)

- **`GET /events*`**: each event gains `reminder_minutes` (stored override, nullable), `notify_at` (ISO local datetime, or null when no effective lead / already started / suppressed), `notify_suppressed_reason` (`"shabbat" | "yom_tov:<name>" | null`). Computed by `assistant/notify.py` at serialization; `server.py` stays routes-only.
- **`POST /events` / `PATCH /events/{id}`**: accept `reminder_minutes` (null clears). Existing optimistic-concurrency and iOS `PendingChange` offline-queue machinery unchanged. Any write bumps the DB mtime → the `/changes` token flips → the phone re-pulls and reconciles, free.
- **`PATCH /config`** (exists, server.py:1599): carries the `notifications` section so iOS Settings can edit the global default and observance toggle.
- **No new scheduling endpoint.** Schedule is derived state; the event payload is the contract.

## Scheduling mechanics

**iOS — primary.** New `ReminderScheduler.swift` (manual `PBXFileReference`/`PBXBuildFile`/`PBXGroup` entries — classic pbxproj, no sync groups). `reconcile()` runs after `cacheEvents`/`insertEvent`/`patchEvent`/`removeEvent`, on the foreground `.task` sync, **and when the existing `/changes` token poll detects a change** (B's graft). It takes cached events with `notify_at > now`, nearest-first, schedules up to **55** `UNCalendarNotificationTrigger(dateMatching:, repeats: false)` requests with identifier `evt-<id>` (WorkoutStore :508-541 cancel-by-id precedent), removing stale `evt-*` ids first; headroom reserved for WorkoutStore rest timers and `APIClient.notify` under the shared 64 cap. Body: `In 30 min · 15:00 · <location>`; the event time in the content makes a stale fire self-evident (A). Tap deep-links `macalendar://event/<id>` via the existing `.onOpenURL`. Add a `UNUserNotificationCenterDelegate` (none exists) for foreground banners; lift `requestNotificationPermissionIfNeeded()` from WorkoutStore into a shared helper, requested when the user first enables reminders, not at launch. Offline-created events: naive local `start − lead` fallback, no observance check, repaired at next sync (fail-open, documented).

**Mac — best-effort.** `assistant/notifier.py` daemon thread started from `create_app()` (the `start_pending_retry_loop` idiom, server.py:105-146), **gated by `MACALENDAR_NO_WARMUP`** so tests never start it. Every 30s: select events with `notify_at` in `(watermark, now]` and no `reminder_log` row; deliver via `subprocess.run(["osascript", "-e", "display notification …"])` (loopback-free, no dependency; attribution to "Script Editor" accepted for v1 — signed-bundle upgrade deferred); optional `say` when `speak: true`. Late tick (wake from sleep): fire if within `catch_up_minutes` and event not started ("starting now" wording), else log `outcome=missed` silently. Every fire/suppress appends a trace-bus step (`{"stage":"notify","action":"fired|suppressed","reason":…}`, source `"mac"`) so HUD History explains why. Honest limit, stated in docs: the API dies with the GUI (`Launch Calendar.command` kills by PID) — Mac banners fire only while the calendar stack is up; the phone covers absence.

## Quiet-window rules (`assistant/notify.py`, evaluated on the **fire time**, mirroring `db._skip_for_observance`, db.py:498-560)

1. Gate: `notifications.respect_observance` **and** `observance.is_enabled()` — two kill switches.
2. Quiet iff fire time falls inside [`candle_lighting(erev)`, `tzeit(last day)`] using real clock boundaries, never date-only (Jerusalem candle lighting: 18:43 Sep, 16:20 Dec); evening-of-erev governed by the next day's status per `availability()`'s two-slot model.
3. **Event itself inside the window** (Shabbat lunch): reminder **suppressed**, reason recorded and surfaced (`notify_suppressed_reason`) — never silently.
4. **Event after the window, reminder inside it** (motzei event, lead lands before tzeit): **clamp** `fire_at` to `tzeit + motzei_buffer_minutes` (A's graft; buffer already in `ObservanceSettings`), reason notes the shift.
5. **Fasts**: no suppression — a reminder is not a booking; Yom Kippur covered by the yom-tov check (**verify by unit test**, per C, don't assume).
6. **Fail open**: any exception or `None` solar data → notify normally (`observance.py`'s stated philosophy verbatim).
7. Voice replies **announce** suppression/clamping at creation ("…note the Friday one falls after candle lighting, so it won't ring") — the recurrence-rounding convention applied here.

## Voice (engine hook)

Current misparse (all three designs agree, verified line refs): `_TASK_RE` (segment.py:39-41) needs "remind me **to**"; verb table `("remind", None) → create_todo` (rule_parser.py:208); clock-time reroute (:1257-1265) ignores relative durations → garbage todo.

- **Decompose strips the clause first** — `remind me (?:(\d+|a|an|half an) )?(minute|hour)s? (?:before|ahead of|earlier)` (+ "with a reminder") removed from item text into `slots["reminder_minutes"]` **before validate runs**, because validate's `_EXCLUSIVE_END` (validate.py:63, verified) would read the surviving "before" as a recurrence-end marker and corrupt until/through semantics (C's catch — the decisive implementation detail).
- Inline shape → `CalendarIntent.reminder_minutes`; standalone ("remind me 30 minutes before my meeting") → rule-parser pattern routing to `update_event` with `match_title` + `new_reminder_minutes`; no match → "I couldn't find…" — never guess (deletion-rule ethos). The duration+"before" anchor keeps "remind me to buy milk" on the todo path.
- No pipeline-shape change → **no `BRAIN_VERSION` bump, no `CHAINS`/panel edits**; but the intent-field additions touch contract pins, so file the TASKS.md design row first (CLAUDE.md rule).

### Which half shipped (re-read 2026-09-14)

**Shipped: the INLINE shape.** "book gym tomorrow at 7 with a 15 minute
reminder" parses, strips and stores.

- `_strip_reminder_clause` is `decompose_validate/decompose.py:151`, called
  only for `item.kind == "event"` (:173-174) — so the plan's decisive
  implementation detail held: the clause leaves the text before validate can
  read the surviving "before" as a recurrence-end marker.
- The clause pattern and the minute arithmetic were moved OUT into
  `assistant/intent/lead_time.py` on 2026-09-07 (`816cea7`) for the reason the
  file states: FastRule needs the same reader, and one copy cannot drift from
  the other.
- `resolve_lead_time` (`decompose_validate/resolve.py:525`) carries two bugs'
  worth of scar tissue that is worth keeping in view rather than tidying away:
  "half an hour before" returned 60 until the fraction was read before its
  unit (so every one of those fired an hour early), and a BARE NOUN PHRASE
  after "before" is now refused (:547-553) because "an hour before sales call"
  measures from a DIFFERENT event — reading it as a lead time attached the
  reminder to the wrong thing entirely.
- FastRule copies the slot onto the intent at `fastrule/objects.py:475-478`.

**Not shipped — three pieces, and they are not the same size:**

1. **The STANDALONE shape.** "remind me 30 minutes before my meeting" → a
   rule-parser pattern routing to `update_event` with `match_title` +
   `new_reminder_minutes`. Neither the field nor the pattern exists (see the
   Intents note above). Consequence: an existing event's reminder can be set
   on the phone and by `PATCH /events/{id}`, and **never by voice** — which is
   the one surface this project is actually for. Small-to-medium.
2. **The schema-constrained LLM path.** `CreateEventAction.parameters_schema`
   lists nine properties and `reminder_minutes` is not among them, so the deep
   track cannot produce a reminder even on an utterance whose lead time the
   deterministic reader would have caught. Small.
3. **The announced suppression.** Quiet-window rule 7 below, and
   `notify.py`'s own docstring ("announced at creation — never silent"), both
   promise the voice reply says when a reminder was suppressed or clamped.
   Nothing reads `notify_suppressed_reason` outside the payload builder
   (`notify.py:153`) and the iOS detail row (`EventDetailView.swift:55-64`).
   **The docstring is aspirational, not a description** — the phone is the
   only surface that tells the user, and only if they open the event.

_Caveat on all three: with `pre_event: false` since 2026-09-11, finishing them
buys parsing and storage that will not ring until the flag flips. The parse is
still worth having — the field is a frozen contract and the flag is one line —
but do not schedule these as "the reminders feature is broken" work._

## Settings

- **iOS `SettingsView`**: Reminders section — enable toggle (device-local), permission status row + request/deep-link, default lead picker (Off/5/10/15/30/60) and "Quiet on Shabbat & chagim" toggle written via `PATCH /config`. `EventDetailView`: reminder row (Inherit / None / N min) → `PATCH /events/{id}`.
- **Mac**: Notifications section built in **the worktree's `../MACalendar-app/assistant/calendar_ui/settings_dialog.py`** (never main's inline dialog — guaranteed merge collision otherwise); persists via `config_store.set_values({"notifications": {...}})` (auto-creates the section). Note: config.yaml is not under `assistant/`, so `--reload` does not pick edits up — v1 accepts an API restart.

## Phases

| # | Scope | Files | Effort | State 2026-09-14 |
|---|---|---|---|---|
| **1 — Server policy core** | `reminder_minutes` column + migration + allowed-set (`assistant/db.py`); `reminder_log`; `NotificationsConfig` (`assistant/config.py`, `config.example.yaml`); **new `assistant/notify.py`** (resolution chain → fire time → quiet-window suppress/clamp, pure functions); event serialization + `PATCH /config` section (`assistant/api/server.py`); `gen_api_reference.py`; unit tests incl. seasonal candle-lighting boundaries and the YK check | main repo | ~1 session | SHIPPED `a837345` |
| **2 — iOS lock screen (the headline)** | `ReminderScheduler.swift` (new + pbxproj entries), `Models.swift`/`LocalStore.swift` fields, `UNUserNotificationCenterDelegate` + deep-link route (`MACalendarApp.swift`), shared permission helper, reconcile hooks (`ContentView.swift` + `/changes` poll), `EventDetailView` picker, `SettingsView` section, 55-cap budget | MACalendar-app worktree | ~1.5–2 sessions | SHIPPED `a0346b3` |
| **3 — Voice** | TASKS.md design row → decompose stripping (`engine/decompose_validate/decompose.py`), rule-parser patterns (`intent/rule_parser.py`), intent/schema fields + contract-pin updates, update-path matching, announced-suppression replies, stage tests + audit rows, dev-fast run | main repo | ~1.5 sessions | **HALF** — inline only |
| **4 — Mac banners** | `assistant/notifier.py` thread (NO_WARMUP-gated), osascript delivery, catch-up policy, trace-bus steps, Mac settings section (worktree `settings_dialog.py`), FEATURES.md entries for shipped phases | both | ~1 session | SHIPPED `241f3c2` |
| **5 — Hardening (each behind an owner decision)** | ~~Live Activity "Up Next" card~~ **(done, see below)**; LaunchAgent detachment of `assistant.api` (weekly-review-agent precedent); `BGAppRefreshTask` + `UIBackgroundModes: fetch` (Info.plist verified clean today); snooze action; ~~pre-Shabbat digest mode~~ **(closed by DEVQA Q6, not deferred)** | both | ~1–2 sessions | **PART** — see below |

### Phase 5 — partially done: the "Up Next" Live Activity (2026-09-06)

Gil saw the pre-event banner fire on his lock screen and asked for the
Google-Maps / Starbucks experience: a persistent, self-updating card. Shipped
in the `MACalendar-app` worktree, **additive — the notification scheduling was
not touched.**

- **New target `MACalendarWidgets`** (app extension, `com.macalendar.app.widgets`,
  deployment target 16.2, embedded through an "Embed Foundation Extensions"
  copy phase). Sources: `MACalendarWidgetsBundle.swift`,
  `UpNextLiveActivity.swift`, plus the shared
  `MACalendar-iOS/Shared/UpNextActivityAttributes.swift` compiled into **both**
  targets. No asset catalog, no app-only imports — the extension links nothing
  of the app's.
- **The local-only trick.** Live Activities are normally kept alive by APNs,
  which this project will never use. It does not need to: the countdown is
  drawn by the *system* (`Text(timerInterval:)`, `ProgressView(timerInterval:)`)
  and ticks on the lock screen with the app not running. The app only pushes
  content when the *event* changes — a handful of updates a day.
- **The cost of no push**, stated honestly: those updates only happen when iOS
  gives the app execution time. `LiveActivityManager.sync()` is called from
  `ReminderScheduler.reconcile()` (so every cache write), ContentView's
  foreground handler, its `/changes` token branch, and its 30 s tick. Every
  card carries a `staleDate` at the exact moment it stops being true, so a
  transition missed while the phone is locked is **dimmed by iOS**, not shown
  as a stale countdown.
- **Policy:** starts only when reminders are enabled *and* something is running
  or starts within 8 h (the ActivityKit cap); ends when neither holds; an
  in-progress event wins over an upcoming one.

**Redesigned 2026-09-15: agenda, not a countdown.** Gil didn't want a
stopwatch on his lock screen — he wanted today's agenda, with the current (or
next) event picked out visually and current always outranking next. The
"local-only trick" above is now historical: `ContentState` carries an array
of today's remaining events (`items`, capped at 5) plus `currentId`, not one
event's `start`/`end`; the card is a static per-sync snapshot with **no
system-ticking element at all** — `Text(timerInterval:)` and
`ProgressView(timerInterval:)` are gone from `UpNextLiveActivity.swift`. The
lock-screen and Dynamic-Island-expanded views render every row through the
same `AgendaRow`, whose "current"/"next"/"later" emphasis is a coloured
shadow + background wash that steps down in that order (current strongest,
next lighter, everything else flat) — the "shadow/lighting" Gil asked for
standing in for the removed countdown number. `staleDate` still marks the
exact moment the snapshot goes wrong (the running event ends, or — if
nothing was running — the next one starts), same mechanism as before, just
computed from the headline row instead of the lone event.

**Still open in phase 5:** `BGAppRefreshTask` would let the card roll between
events while the phone is locked, and is the natural next increment — it is
also the one that makes the `staleDate` fallback rare rather than routine.

### Phase 5 — what is actually left (re-read 2026-09-14)

Three items, and they are not equal. One more was closed by ruling, and is not
work at all.

**1. `BGAppRefreshTask` + `UIBackgroundModes: fetch` — medium, needs Xcode.**
It lets the "Up Next" card roll between events while the phone is locked,
which is what makes the `staleDate` dimming rare rather than routine. **Not
started, and not started anywhere:** `grep -rniE
"BGAppRefresh|BGTaskScheduler|UIBackgroundModes"` over `MACalendar-iOS/`
returns zero hits in this checkout and zero on `origin/main`, **including both
`Info.plist` files** (`MACalendar-iOS/Info.plist`,
`MACalendarWidgets/Info.plist`). The plan's 2026-09-06 line "Info.plist
verified clean today" is still true eight days later.

**2. The "remind me even when the calendar is closed" toggle, and the
LaunchAgent detach behind it — LARGE, and UNBLOCKED since 2026-09-06.**
Gil ruled this IN on 2026-09-06 (DEVQA Q4, `DEVQA.md:178-180`): *"Mac reminders
with the calendar closed = a notification-settings OPTION. Settings toggle
first, the LaunchAgent detach ships behind it, default off."* So this is not
waiting on an answer and has not been since the day the plan was written —
any doc still calling it "blocked on Q4" is eight days stale.

Neither half exists. The Mac settings dialog has exactly four notification
controls plus the per-category grid — `notif_enabled_cb` (:225),
`notif_default_lead_combo` (:236), `notif_speak_cb` (:255),
`notif_observance_cb` (:260) — and none of them is this; and `find . -name
"*.plist"` turns up no launchd job for `assistant.api` (the only MACalendar
LaunchAgent installed on this Mac is `com.macalendar.weekly-review.plist`,
which is the precedent to copy, not this).

It is large because it changes the **launch model**, not because the toggle is
hard: `assistant.api` currently runs with `--reload` under `Launch
Calendar.command`, which kills the stack by PID, so detaching it moves who owns
reload, the HUD's lifetime and shutdown. That is exactly why Gil made it
opt-in and default-off rather than the new default. It also runs against his
standing preference on this project — *"i don't really want to make structural
changes if i don't have to"* — so it should be picked up because the
calendar-closed ring is wanted, never as tidying.

**3. Snooze — NO RULING EXISTS. Open question for Gil.** It sits in the same
phase-5 row as the other two but, unlike Q4/Q5/Q6, it has no DEVQA entry:
`grep -rni snooze` over every `.py` and `.swift` in the repo returns nothing,
and the only place it appears at all is the visual preview, where it is tagged
as a proposal to keep or kill. **Do not build it on the strength of it being
in this table.** Keep or kill is a one-line answer; see the open question at
the foot of this file.

**Closed, not deferred: the pre-Shabbat digest.** DEVQA Q6 (2026-09-06,
`DEVQA.md:186-187`) confirmed the shipped suppress-entirely default, and Gil
re-confirmed it on 2026-09-11 (`DEVQA.md:90-92`): *"NO reminders for events
inside Shabbat / yom tov… The alternative is closed, not deferred."* Nobody
owes a digest banner before candle lighting. (The 07:00 **day panel** that
shipped 2026-09-11 is a different thing and is itself held through Shabbat
and yom tov on the same ruling.)

### The device-provisioning question — settled, and not the way the doc said

This paragraph used to read *"the extension's bundle id has never been
provisioned: only `com.macalendar.app` has a profile on this Mac."* That was a
doc assertion nobody retested, and it is **wrong**. Decoding the profiles
embedded in the last device build settles it:

    ~/Library/Developer/Xcode/DerivedData/MACalendar-iOS-dyjhtd…/
        Build/Products/Debug-iphoneos/MACalendarWidgets.appex/embedded.mobileprovision

`security cms -D` on that file returns **"iOS Team Provisioning Profile:
com.macalendar.app.widgets"**, `application-identifier
HPMNWWG455.com.macalendar.app.widgets`, created 2026-09-06 17:13, **with
`com.apple.security.application-groups = group.com.macalendar.app` in its
entitlements**. The app's own profile from the same 17:13 build carries the
group too; the 13:06 build earlier that same day does not, because it predates
the entitlement. So the extension WAS provisioned, with the App Group, on the
day it was written — about four hours after the sentence claiming otherwise.

That matters beyond bookkeeping: `902e8a4`'s own commit message says that if
App Groups turn out to be unavailable, the home-screen widget *"placeholders
forever and the honest fix is dropping it."* A profile carrying the group was
issued, so that objection is answered and the widget should not be dropped on
those grounds.

**What is still true, for a different reason:** both profiles were valid for
exactly seven days and **expired 2026-09-13** (seven days is the free
personal-team signing window — an inference from the dates, not something the
profile states). Nothing is installed today:
`~/Library/Developer/Xcode/UserData/Provisioning Profiles/` is empty and
`~/Library/MobileDevice/Provisioning Profiles/` does not exist. So **one Run
from Xcode.app with the phone reachable is still the next step**, and after it
`xcrun devicectl device install app` works as usual — the reason is expiry,
not absence.

**Still genuinely unverified: the phone itself.** Simulator proof is complete
(start / flip to NOW / roll to next / end, plus the Dynamic Island rendering
the live countdown), but no commit after `902e8a4` records a device check, and
the newest entry under `~/Library/Developer/Xcode/DeviceLogs` for Gil's iPhone
is 2026-08-19. Whether the group container resolves and the card and widget
draw on real hardware is unknown — that is what the one Run buys.

Each shipped phase adds its `DOCUMENTATION/FEATURES.md` entry in the same change; branch, never commit to main.

## Test strategy

- **Offline test**: `tests/unit/test_offline.py` must stay green — `notify.py` is pure Python + `observance.py` (local), delivery is `subprocess`/osascript (no sockets). Add an explicit unit test asserting the notifier module opens no socket, and that `MACALENDAR_NO_WARMUP=1` prevents the thread from starting under `create_app()` (same reason as the Whisper warmup gate).
- **`notify.py` unit tests** (fast, no model): resolution-chain precedence (event > category > global; `0` beats a category default); September-vs-December Friday boundary cases; motzei clamp; fail-open on `None` solar data; Yom Kippur in the yom-tov set (C's verify-don't-assume); no-`start_time` events.
- **Harness hygiene**: any script exercising this sets all five env overrides (`MACALENDAR_DB/MEMORY_DB/VOCAB/CATEGORIES/TRACE_BUS`) and posts `source: "test"`.
- **Engine phase**: pin new intent fields in `test_engine_contracts.py`; stage tests in `test_engine_decompose.py`/`test_engine_generate.py` including "remind me to buy milk" staying a todo and an until/through sentence with a reminder clause keeping correct recurrence-end semantics; audit-corpus rows; dataset guard = dev-fast (`--limit 0 --max-rank 250`), hypothesis "garbage-titles rate drops on remind-before utterances; task-slice count-correct holds", logged in `dataset/RESULTS.md`. **Note (C):** the 3000-row ground truth has no reminder field — the audit floor + unit tests are the regression net for this phrasing.
- **Mac settings UI**: `QTest.mouseClick`/`keyClicks`, never handler calls (three HUD bugs shipped green that way).
- **iOS cap test**: reconcile with >55 upcoming reminders while a WorkoutStore rest timer is pending — assert the rest timer survives and `evt-*` count ≤ 55.
- **`--reload` dedupe**: touch a source file mid-test-window; assert `reminder_log` prevents a duplicate fire.

### Which of these exist (checked 2026-09-14, by reading the test files — nothing was run)

Three files carry the net: `tests/unit/test_notify.py`,
`tests/unit/test_notifier.py`, `tests/unit/test_settings_notifications.py`.

- **Built as specified:** the resolution chain in all five of its precedences
  (`test_notify.py:28-58`, including `0` beating a category default and a
  category `0` muting outright); the September-vs-December Friday pair (:82,
  :90 — the same clock time, one outside candles and one inside); the motzei
  clamp (:106); Yom Kippur present in the yom-tov set (:118 — verified, not
  assumed, as the design panel insisted); no-`start_time` (:70); the master
  switch (:75). The notifier side has the socket assertion
  (`test_notifier.py:237 test_a_tick_opens_no_sockets`) and the warmup gate
  (`:249 test_create_app_under_no_warmup_does_not_start_the_thread`), and
  dedupe is covered by `:85 test_due_reminder_fires_once_then_dedupes`.
- **The Mac settings UI rule held.** `test_settings_notifications.py` toggles
  with `QTest.mouseClick` and drives the combos with `QTest.keyClicks` (:164,
  :233-240) rather than calling handlers — the trap that shipped three HUD
  bugs green.
- **The engine-phase tests exist too, and one of them is the whole reason the
  strip lives in decompose:** `test_engine_decompose.py:134
  test_until_through_sentences_never_touched` asserts "run daily until the end
  of September" and two siblings keep their text and gain no slot.
  `test_bare_reminder_command_left_for_the_fallback` (:147) pins that a BARE
  "remind me 30 minutes before" is declined by the strip — note that the
  fallback its name points at (update_event + `new_reminder_minutes`) was never
  built, so what catches that utterance today is the ordinary parse path. I
  did not run it to see what that produces.
- **Not built:** the contract pin (`grep -i reminder
  tests/unit/test_engine_contracts.py` is empty, so the new intent field is
  not frozen by the test that freezes the rest), and **the iOS 55-cap test** —
  the repo has no XCTest target at all, so the "reconcile with >55 upcoming
  reminders while a rest timer is pending" assertion has no home. The 55-cap
  logic is therefore documented (`ReminderScheduler.swift:20-34`) and
  unexercised.
- **Superseded:** the dataset guard (a dev-fast run with a
  garbage-titles/task-count hypothesis) was never run, and should not be run
  now as written — the 3000-row ground truth has no reminder field, which the
  plan itself flagged, and the pre-event path it would guard ships off.

## Open questions for the product owner — all three ANSWERED 2026-09-06

These were the three the plan reserved. None of them is open; a doc still
calling this feature "blocked on Q4–Q6" is eight days behind the log.

1. **Do you want Mac reminders with the calendar closed?** That requires detaching `assistant.api` into a launchd LaunchAgent — a launch-model change affecting `--reload`, the HUD, and shutdown ownership. If no, Phase 5's biggest item disappears and the phone is officially the only always-on surface.
   → **RULED IN as a settings OPTION, default off** (DEVQA Q4, 2026-09-06,
   `DEVQA.md:178-180`): *"settings toggle first, the LaunchAgent detach ships
   behind it."* So phase 5's biggest item did NOT disappear — it is unblocked
   and unbuilt. See phase-5 item 2 for what exists (nothing) and why it is
   large (the launch model, not the checkbox).
2. **Global default lead: opt-in (`0`, reminders only where asked) or blanket (e.g. 30 min before everything)?** Ships as `0`; a blanket default changes the feature's character and its noise level on a dense calendar.
   → **RULED: PER CATEGORY** (DEVQA Q5, 2026-09-06, `DEVQA.md:182-184`). That
   matches the mechanism already built — `resolve_lead`'s event override →
   category lead/mute → global fallback — and makes the per-category grid in
   notification settings the primary surface, with the global default staying
   `0`. Shipped exactly so (`settings_dialog.py:267-333`).
3. **Reminders for events *inside* Shabbat/yom tov (e.g. Shabbat lunch): suppress entirely (shipped default), or roll into a single pre-candle-lighting digest banner?** This is an observance-lifestyle call, not an engineering one.
   → **RULED: SUPPRESS ENTIRELY, no digest** (DEVQA Q6, 2026-09-06,
   `DEVQA.md:186-187`), re-confirmed 2026-09-11 (`DEVQA.md:90-92`) in the
   words that close it: *"The alternative is closed, not deferred."*

## The one question that is actually open

**Snooze: keep or kill?** It appears in phase 5's scope cell and in the visual
preview, and **it has no ruling** — unlike Q4, Q5 and Q6 it has no DEVQA entry
at all, and `grep -rni snooze` over every `.py` and `.swift` in this repo
returns nothing. It arrived as a preview proposal and was never decided either
way.

Worth knowing before answering: snooze is a per-event action on an alert, so
it belongs to the **pre-event** path — the one that has shipped `false` since
the day panel replaced it on 2026-09-11. A day panel has nothing to snooze.
So "kill" may simply be recording what the 2026-09-11 decision already implied,
and "keep" is a decision to bring the pre-event path back for it. Either
answer is one line here; building it on the strength of a table row is not.
# The offline reader protocol

Gil, 2026-09-28 (DEVQA Q66): when the Mac can't be reached, the phone (or
any iOS device away from the server) reads a command itself with **Apple's
on-device model** (iOS 26 Foundation Models) and books it at once. When the
Mac is back, **the Mac's engine reads the same command and its reading
wins**. This file is the contract between the two, and the rules for
changing either side.

## Who does what

| | phone (offline) | Mac (on reconnect) |
|---|---|---|
| reads | the on-device recogniser's draft, with Apple's model, guided to the item shape | Whisper on the audio (or the edited text), then the whole engine, including its model pass |
| may book | **creates only**: events and to-dos, as provisional rows | anything the engine does |
| never | move, change, rename, delete or complete an existing row (they name a row, and a cache can be stale); those are marked `other` and wait | trust the phone's reading, which is compared but never executed |

## The flow

1. **Offline.** `VoiceButton` queues the command (`PendingVoiceCommand`), as
   before. If `OfflineReader.isAvailable` and the draft isn't empty, the model
   reads it (`OfflineReader.read`), the output is sanitised (bad kind, date or
   clock becomes `other` or empty; an event with no day becomes `other`), and
   `LocalStore.bookProvisional` inserts the creates as placeholder rows with
   temporary negative ids. These are **never queued as creates** to the Mac.
   The row is held (`heldForEdit`) while the model reads, so a reconnect
   mid-read can't send the command without its reading.
2. **Reconnect.** `syncPendingVoice` resends the command as before (audio, or
   text if edited, with the same `client_id`) and attaches the reading as
   `offline_reading`: a JSON body on `/voice/text`, a form field on `/voice`.
3. **The Mac runs the command** exactly as any other. Then
   `offline.reconcile.attach` reads back what the engine committed (the
   reply's `committed` row references), compares, logs, and adds an `offline`
   block to the reply. All of this happens inside `receipts.run_once`, so a
   resend neither logs twice nor loses the verdict.
4. **The phone settles** (`APIClient.settle`):

| verdict | meaning | phone does |
|---|---|---|
| `same` | every item the phone booked, the Mac booked: same kind, matching title, same day, start and repeat | removes its placeholders; the Mac's rows arrive with the refresh |
| `changed` | the Mac read it differently | the same, and notifies: "Your Mac read this differently" |
| `pending` | the Mac's own model was busy, so it queued the command (`pending_id`) | **keeps** its placeholders; the row goes `.waiting` and asks `GET /offline/pending/<id>` on each flush until the Mac has run it, then removes them |
| `deferred` | the phone booked nothing | as before |
| `unverified` | a `protocol` this Mac doesn't know | nothing is compared; the Mac's reading still wins |

Placeholders are removed whatever the verdict (except `pending`): the Mac's
rows are the truth. An `end` the phone left empty is not a disagreement, since
it's the Mac's default duration.

## Phone first, Mac behind (DEVQA Q87, 2026-10-09)

The same contract, used while the Mac IS reachable — and the phone does not
wait for it. With "Read on this phone first" on (the default; Settings ▸ How
it runs), `VoiceButton.runPhoneFirst`:

1. **Reads and does the command on the phone** — `LocalCommand.run`, the
   same reader as "This phone only" (rules, else Apple's model) — inside
   `PhonePreview`: every request fails as offline, so each write takes its
   offline road and changes the phone's copy (new rows get placeholder ids,
   edits and deletes patch the cache), and `LocalStore.enqueue` drops the
   queue entry. **Nothing the phone does reaches the Mac.** The reply is
   shown and spoken at once; the rows it made are held under the command
   (`LocalStore.holdLive`).
2. **The phone read nothing:** nothing to show, so the Mac's road, waited
   for, exactly as before.
3. **The Mac gets the command in the background** (`checkOnMac`) with the
   phone's reading as `offline_reading` (`reader` `phone-rules` or
   `apple-fm`, `live: true`; creates are items, anything else `other`).
4. **The Mac answers:** the held rows go (`dropLive`) and the refresh brings
   the Mac's rows — which also undoes any edit or delete the phone made that
   the Mac did not. `changed`, or a Mac that committed nothing where the
   phone changed something, is said ("Your Mac read it differently").
   `pending` keeps the rows up to 30 min. `needs_edit` / `confirm_create`
   bring up the edit sheet or the "add this?" prompt.
5. **The Mac turns out to be unreachable:** the command joins the offline
   queue, booked from the same reading (creates only, as offline).

Held rows are persisted with an expiry and swept at launch, so a crash
between the phone's answer and the Mac's cannot strand them. `live` is
logged; `GET /offline/agreement` reports agreement `by_reader`.

## Versions: how a fix reaches the phone

- **`spec_version`** is a hash of what the model is TOLD
  (`spec.INSTRUCTIONS`, `spec.EXAMPLES`, kinds, schema). It is **served**
  (`GET /offline/reader`) and cached on the phone (refreshed hourly while the
  Mac is reachable). **To improve the offline reader, edit `spec.py` on the
  Mac.** No reinstall and no version bump: the hash changes itself, and the
  log tells readings from each version apart.
- **`SCHEMA`** is the item SHAPE, compiled into the app as a `@Generable`
  struct (`OfflineReader.swift`). Changing it needs a new build: bump
  `SCHEMA` in both, and the phone ignores a served spec for another schema
  (it uses its bundled copy).
- **`PROTOCOL`** is the shape of `offline_reading` and of the `offline` block.
  Bump it in both when either changes; an old phone then gets `unverified`,
  which is safe because the Mac always re-reads.
- `tests/unit/test_offline_protocol.py` goes red if the Swift constants,
  kinds or recurrences stop matching `spec.py`.

The personal vocabulary (`names`) is sent with the spec as data, so the
model spells your names the way the Mac does; learning a word does not change
`spec_version`.

## Measuring it

Every comparison is one line in the per-user `offline_readings.jsonl`
(`MACALENDAR_OFFLINE_LOG`; scratched in tests): the phone's text and items,
the Mac's text and items, the verdict, which fields differed, the reader and
spec version, and how long the model took. `GET /offline/agreement` returns
counts by verdict, agreement over `same + changed`, the fields that differ
most, and the readers seen. It's real-usage data: read it before changing
`spec.py`, and judge a change by the next week of readings, not by a demo.

## Devices

Apple's model needs iOS 26, Apple Intelligence on, and an eligible device.
The iPhone 16e qualifies; the iPad (10th generation) does not, so it keeps
queueing as before. The framework is weak-linked, so the app still launches
on iOS 16–25, where the reader simply reports unavailable. Settings shows the
device's state.

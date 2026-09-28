"""The phone's offline reader, and the protocol that keeps it honest.

Gil, 2026-09-28: when the Mac cannot be reached, the phone reads the command
itself with Apple's on-device model (iOS 26 Foundation Models) and books it at
once — and when the Mac is back, the Mac's own engine reads the SAME command
and its reading wins. `PROTOCOL.md` in this folder is the whole contract; the
short version:

- The phone may only CREATE (an event or a to-do). A move, change, delete or
  complete is left for the Mac — it names an existing row, and a guess against
  a stale cache is how the wrong thing gets deleted.
- What the phone books is PROVISIONAL: placeholder rows with temporary ids,
  never sent to the Mac as creates. On reconnect the phone resends the
  command (audio or text, as before) with its reading attached as
  `offline_reading`; the Mac runs its engine, compares, and answers with an
  `offline` block — `same`, `changed`, `pending` or `deferred`. The phone then
  removes its placeholders and shows the Mac's rows.
- The instructions the phone's model follows are SERVED from here
  (`GET /offline/reader`) and cached on the phone, versioned by a hash of their
  text — so a fix to how the phone reads ships without a reinstall. Only the
  item SHAPE is compiled into the app (`SCHEMA`); a schema change is the one
  thing that needs a new build, and the phone refuses a served spec whose
  schema it was not built for.
- Every comparison is logged per user (`offline_readings.jsonl`), and
  `GET /offline/agreement` reads it back — how often the phone and the Mac
  agree is data, gathered from real use, not a claim.

Nothing here parses or executes: the engine does that, on the Mac, exactly as
for any other command. This package only describes the phone's reader and
compares two readings after the fact.
"""

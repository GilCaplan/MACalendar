# The sync protocol

*Written 2026-09-17, answering Gil's "do we need a protocol of some sort for
sync?" — the honest answer is that there already was one, it was just never
written down, and two of its gaps were what made the phone feel slow away from
the Mac.*

**The Mac is the only source of truth.** The phone is a cache with a queue in
front of it. Nothing here changes that, and nothing here should: the moment the
phone becomes a second authority, "which copy is right" is a question somebody
has to answer at 2 a.m. with a duplicated shopping list in front of them.

So the protocol is small, and every rule in it exists to keep that one sentence
true.

## The four channels

| channel | direction | when |
|---|---|---|
| `GET /sync/bootstrap` | Mac → phone | cold start, foreground |
| `GET /changes` | Mac → phone | every 2 s while the app is open |
| the individual `GET`s | Mac → phone | after the token moves, and per view |
| the pending queue | phone → Mac | on reconnect, on foreground, every 30 s |

### 1. Bootstrap — one round trip for a cold start

`GET /sync/bootstrap?year=&month=&israel=` returns, in one payload: the change
token, the server's clock, a three-month window of events (the named month plus
one either side, which is what month/week/day can reach without another fetch),
the open tasks, the tag palette, the tag classifier's table, the event
categories, the holidays for the same window, and the timers and counters.

It exists because a cold start was five to eight independent GETs run one after
another. Online that is merely wasteful. Offline it was the whole problem:
each one sat out its own timeout before falling back to a cache that had been
on disk the entire time, so the app opened on an empty calendar for tens of
seconds and then filled in all at once.

It is a **read aggregate**. It holds no logic of its own and calls the same
helpers the individual routes call — it is not a second way into the database,
and a client that never uses it still works exactly as before.

### 2. The change token — "has anything moved?"

`GET /changes` returns a few bytes derived from the database file's mtime and
size. The phone polls it every 2 s and does real work only when the answer
changes. This predates this document and is unchanged.

### 3. The offline circuit breaker — the phone's half

Every read on the phone falls back to its cache. The bug was that it fell back
*after* the request had spent its full 8 s timeout, and there were several such
requests per screen.

`APIClient` now remembers that the Mac was unreachable. While it does:

- ordinary requests throw `.offline` **immediately**, without touching the
  network. That is the same error a timeout produced, so every cache fallback
  and every offline-queue path is unchanged — it just happens instantly.
- `/health` and `/changes` still go out, on a 3 s leash. Something has to
  notice the Mac coming back, and these are the two cheap ways to ask.
- the gap between those probes grows 2 → 4 → 8 → 16 → 20 s, so a Mac that is
  off for an hour is asked about 300 times rather than 1,800.
- any successful response clears it, and the existing reconnect hook flushes
  the queues.

The voice uploads check it too. They build their own `URLRequest` with a 120 s
timeout — right for a Mac that is thinking, badly wrong for one that is not
there — so without this the phone sat on a finished recording for two minutes
before queueing it.

### 4. The pending queue — the phone's writes

Unchanged, and the part that was already a protocol:

- a write that cannot reach the Mac is applied to the local cache optimistically
  and appended to `mc_pending.json`;
- rows created offline get negative placeholder ids, and `remapTemporaryID`
  rewrites anything queued against one once the Mac assigns the real id;
- creates carry a `client_token`, so a replayed create returns the row the Mac
  already made instead of a second copy;
- edits carry `base_updated_at`, so an edit made from a stale copy is refused
  (409) rather than silently overwriting a newer one — and the user is told;
- a replay the Mac refuses outright (404, 400) is dropped rather than left at
  the head of the queue blocking everything behind it;
- recordings made offline are queued whole and replayed as audio, because the
  phone cannot understand them — the brain is on the Mac.

## What the phone is allowed to compute

Two things, and the rule for both is the same: **the phone may compute what it
can derive, never what it must decide.**

- **Hebrew dates** — computed on the phone from Foundation's Hebrew calendar,
  and always were. A date is derivable; there is nothing to decide.
- **Holidays** — decided by the Mac (`pyluach`, one implementation, so both
  devices agree) and now **cached** on the phone. They were the one part of the
  calendar with no cache at all: going offline emptied the holiday list out of
  every month view while the Hebrew dates beside them carried on, which looked
  exactly like a bug because it was one. A bootstrap covers three months; the
  cache keeps every window it has ever been told about.
- **Task tags** — see below.

## Task tags offline

`assistant/actions/todo/tagging.py` is *the* classifier. It runs where the
database is, so a task typed on the phone with the Mac away was created
untagged — and the Mac never re-tags a task it did not create, so when the
queued create replayed hours later it landed in the untagged pile for good.

`TagClassifier.swift` is that scorer running on the phone, over a table the Mac
serves at `GET /tags/rules`:

```json
{ "rev": "…",
  "keywords": {…},
  "order": ["Groceries", "Coursework", "Errands", "Work"],
  "never_infer": ["personal"],
  "palette": ["Groceries", …],
  "personal_labels": [{"word": "haxaga", "label": "Coursework"}] }
```

**`order` and the list-shaped `personal_labels` are not cosmetic.** `infer_tag`
keeps the best score with a strict `>`, so a tie goes to whichever tag is
scored first — and that order does not survive the trip: Flask sorts JSON keys,
and a Swift `Dictionary` has no order at all and is not stable between runs. A
comparison over 10,200 real strings found 20 disagreements, every one of them a
tie ("buy twelve eggs and book haircut" is Groceries 1.5, Errands 1.5), and a
different twenty on each launch. The order now travels with the table, and
`personal_labels` likewise arrives in the order `vocab.label_for` considers
them (longest word first) rather than as a dictionary the phone would have to
re-sort and guess the ties of.

Serving the table rather than shipping it is the whole design. A second keyword
list, in a second language, in a separate release cycle, is a list that drifts;
and the half that matters most could not be shipped at all — `personal_labels`
is the user's own vocabulary labels, the ones that know "Haxaga" is a course.
What lives in Swift is about forty lines of arithmetic. `rev` changes whenever
any of the data does, so a client knows in one comparison whether its copy is
current.

**Its answer is a preview, not a decision.** The tag is shown immediately, so
the task does not vanish out of the tag view you were looking at. The **queued
body is left alone** — it still says what the user said, which is usually
nothing — so on replay the Mac classifies the task itself and the Mac's answer
is the one that lands. When the phone's table is current the two agree by
construction; when it is stale, the Mac wins, which is the right way round.

## What this does not do (and why)

- **No two-way merge.** There is no vector clock, no CRDT, no last-writer-wins
  field merge. The Mac wins, except where `base_updated_at` makes the phone's
  edit visibly fail instead. For one person with one Mac and one phone, a merge
  algorithm buys nothing and costs a class of bug that is very hard to see.
- **No push.** The Mac never initiates. The phone polls a 40-byte token, which
  over a tailnet is cheaper than keeping a socket alive, and works after the
  phone has been asleep for six hours.
- **No offline event categorisation.** An event created on the phone offline
  keeps the colour the sheet gave it and is categorised by the Mac on replay.
  Unlike tags, nothing about the event *disappears* in the meantime, so the
  same treatment is available if it is ever wanted — but it is not needed.
- **No conflict UI beyond one notification.** A refused edit says so and the
  Mac's version stands. Anything more elaborate would need the phone to hold a
  second version, which is the thing this document exists to prevent.

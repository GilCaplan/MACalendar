# API reference

Generated from `assistant/api/server.py` and each integration's and feature's `routes.py` by `python -m scripts.gen_api_reference` — do not edit by hand.
All endpoints are served by the Mac at `http://<tailscale-ip>:8080`; the iOS app is the only client. Path parameters use Flask syntax (`<int:id>`).

## /health

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` |  |

## /heartbeat

| Method | Path | What it does |
|---|---|---|
| `POST` | `/heartbeat` | A device (the phone, another client) reports it is alive and |

## /voice

| Method | Path | What it does |
|---|---|---|
| `POST` | `/voice` | Accept a multipart audio file, transcribe via Whisper, then execute. |
| `POST` | `/voice/confirm` | Answer a confirm_create proposal: {"confirm_token", "accept": bool}. |
| `POST` | `/voice/stream` | Same as POST /voice but streams the thinking trace live as NDJSON. |
| `POST` | `/voice/text` | Accept a JSON transcript and execute directly (skips STT). |
| `POST` | `/voice/transcribe` | Audio in, words out. No parsing, no execution, nothing created. |
| `GET` | `/voice/verify/<token>` | Poll for background LLM verification of a rule-path voice command. |

## /devices

| Method | Path | What it does |
|---|---|---|
| `GET` | `/devices` | What has enrolled, when it last spoke, and whether it is revoked — |
| `POST` | `/devices/<device_id>/revoke` | Retire one device. It keeps working as an ISOLATED stream rather |
| `POST` | `/devices/enroll` | Issue this client a device id and a token. Called once, on first run. |

## /lexicon

| Method | Path | What it does |
|---|---|---|
| `GET` | `/lexicon` | Every editable word list: what the code ships, and what Gil added. |
| `POST` | `/lexicon/<name>` | Add one of your own words to a list. Additive only — a built-in can |
| `DELETE` | `/lexicon/<name>/<path:word>` | Remove one of YOUR words. A built-in is not removable by design. |

## /vocab

| Method | Path | What it does |
|---|---|---|
| `GET` | `/vocab` |  |
| `POST` | `/vocab` |  |
| `DELETE` | `/vocab/<path:word>` |  |
| `PATCH` | `/vocab/<path:word>` | Edit a word the settings screens are showing. |
| `POST` | `/vocab/alias` | Teach a correction: {"wrong": "Kyira", "right": "Kyra"}. |
| `POST` | `/vocab/bulk` | Add many words at once: {"words": ["Kyra", ...]} |
| `POST` | `/vocab/import` | Mine vocabulary candidates. Body: {"text": "..."} (WhatsApp export / notes) |
| `GET` | `/vocab/onboarding` |  |
| `POST` | `/vocab/onboarding` | {"answers": {"people": ["Kyra"], ...}, "presets": ["tefillah"], "done": true} |
| `POST` | `/vocab/preview` | Dry-run: what would the corrector do to this text? (no learning) |
| `PATCH` | `/vocab/settings` |  |

## /changes

| Method | Path | What it does |
|---|---|---|
| `GET` | `/changes` | A cheap "has anything changed?" token for the phone to poll. |

## /tips

| Method | Path | What it does |
|---|---|---|
| `GET` | `/tips` | The "How to Talk to Me" tips and the reply hints — one copy for every client. |

## /pending

| Method | Path | What it does |
|---|---|---|
| `GET` | `/pending` |  |
| `DELETE` | `/pending/<int:pending_id>` |  |
| `POST` | `/pending/<int:pending_id>/retry` |  |

## /memory

| Method | Path | What it does |
|---|---|---|
| `GET` | `/memory` |  |
| `DELETE` | `/memory/<int:example_id>` |  |
| `POST` | `/memory/<int:example_id>/feedback` | {"feedback": "approved"\|"corrected"\|"rejected", "correction": [...]?, "notes": "..."} |
| `GET` | `/memory/similar` |  |
| `GET` | `/memory/unreviewed` | Commands with no feedback yet, each with every row it touched |
| `POST` | `/memory/unreviewed/skip` | Dismiss the whole review backlog (e.g. stale seeded history). |

## /observance

| Method | Path | What it does |
|---|---|---|
| `GET` | `/observance` | Training availability per day: what is blocked, and which windows remain. |
| `DELETE` | `/observance/location` | Forget the reported position and go back to the configured place. |
| `GET` | `/observance/location` | Where sundown is currently computed for, and where that came from. |
| `POST` | `/observance/location` | A device reporting where it is. |
| `GET` | `/observance/windows` | When Shabbat and yom tov begin and end, to the second, over a range. |

## /digest

| Method | Path | What it does |
|---|---|---|
| `GET` | `/digest` | Today's day panel: when it fires, what it says, and the rows behind it. |
| `GET` | `/digest/upcoming` | The next few days' panels in one answer, for the phone to SCHEDULE. |

## /config

| Method | Path | What it does |
|---|---|---|
| `GET` | `/config` |  |
| `PATCH` | `/config` |  |

## /calendar_sources

| Method | Path | What it does |
|---|---|---|
| `GET` | `/calendar_sources` |  |
| `POST` | `/calendar_sources` |  |
| `DELETE` | `/calendar_sources/<int:source_id>` |  |
| `PATCH` | `/calendar_sources/<int:source_id>` |  |

## /calendar_sync

| Method | Path | What it does |
|---|---|---|
| `POST` | `/calendar_sync/<provider>/disconnect` | Sign out of google\|outlook. {"keep_events": true} keeps synced events as local. |
| `GET` | `/calendar_sync/flows/<flow_id>` | A sign-in's progress: pending \| done \| error. |
| `POST` | `/calendar_sync/google/client` | Store the Google Desktop OAuth client JSON: {"client_json": "..."}. |
| `POST` | `/calendar_sync/google/complete` | Finish a phone Google sign-in: {"flow_id", "callback_url"} or {"code", "state"}. |
| `POST` | `/calendar_sync/google/mirror` | Push one plain local event to Google from now on: {"event_id"}. |
| `POST` | `/calendar_sync/google/start` | Start a Google sign-in. {"platform": "mac"\|"ios"} → auth_url (+ callback_scheme on iOS). |
| `GET` | `/calendar_sync/guide` | The in-app "how to connect" walkthroughs (`calendar_sync/guide.py`). |
| `POST` | `/calendar_sync/outlook/start` | Start an Outlook device-code sign-in → user_code + verification_uri. |
| `PUT` | `/calendar_sync/setup` | Save client ids to config.yaml: {"outlook_client_id", "google_ios_client_id"}. |
| `GET` | `/calendar_sync/status` | Everything Settings shows: providers, accounts, last sync, errors, ICS links. |
| `POST` | `/calendar_sync/sync` | Sync every connected calendar now. {"wait": true} blocks and returns the results. |

## /jude

| Method | Path | What it does |
|---|---|---|
| `POST` | `/jude/chat` | Ask Jude a question; stream the answer back as NDJSON. |
| `GET` | `/jude/chats` | List past conversations, newest first. |
| `DELETE` | `/jude/chats/<chat_id>` | Forget one conversation. |
| `GET` | `/jude/chats/<chat_id>/history` | Every message in one conversation. |
| `PUT` | `/jude/chats/<chat_id>/topic` | Confirm a topic pivot. |
| `GET` | `/jude/status` | Never an error — a client draws whatever this says. |

## /categories

| Method | Path | What it does |
|---|---|---|
| `GET` | `/categories` |  |
| `POST` | `/categories` | {"name": "Volunteering", "color": "#…", "alt": "#…", "keywords": [...], "add_keywords": [...]} |
| `DELETE` | `/categories/<path:name>` |  |
| `POST` | `/categories/classify` |  |
| `POST` | `/categories/recolor` | Apply categories/colours to existing events. ?force=1 re-does everything. |

## /events

| Method | Path | What it does |
|---|---|---|
| `GET` | `/events` |  |
| `POST` | `/events` | Create an event. |
| `DELETE` | `/events/<int:event_id>` |  |
| `GET` | `/events/<int:event_id>` |  |
| `PATCH` | `/events/<int:event_id>` |  |
| `GET` | `/events/<int:event_id>.ics` | Share/export one event as an .ics file (import's symmetric half). |
| `DELETE` | `/events/<int:event_id>/series` | Delete the whole series, or `?scope=future` for this one and later. |
| `GET` | `/events/<int:event_id>/series` | Every instance of the series this event belongs to, plus its rule. |
| `PATCH` | `/events/<int:event_id>/series` | Edit the SERIES through one of its instances. |
| `GET` | `/events/<int:event_id>/todo` | The to-do that is this event, or `{"todo": null}`. |
| `POST` | `/events/<int:event_id>/todo` | Also put this event on the to-do list, linked. Returns the existing |

## /search

| Method | Path | What it does |
|---|---|---|
| `GET` | `/search` | Substring search over events and tasks for the toolbar/search UIs. |

## /sync

| Method | Path | What it does |
|---|---|---|
| `GET` | `/sync/bootstrap` | Everything a client needs to draw itself, in ONE round trip. |

## /holidays

| Method | Path | What it does |
|---|---|---|
| `GET` | `/holidays` |  |

## /courses

| Method | Path | What it does |
|---|---|---|
| `GET` | `/courses` |  |
| `POST` | `/courses` |  |
| `DELETE` | `/courses/<int:course_id>` |  |
| `PATCH` | `/courses/<int:course_id>` |  |
| `GET` | `/courses/<int:course_id>/assignments` |  |

## /assignments

| Method | Path | What it does |
|---|---|---|
| `GET` | `/assignments` | Return all assignments across every course. |
| `POST` | `/assignments` |  |
| `DELETE` | `/assignments/<int:asgn_id>` |  |
| `PATCH` | `/assignments/<int:asgn_id>` |  |
| `PATCH` | `/assignments/<int:asgn_id>/toggle` |  |
| `DELETE` | `/assignments/completed` |  |

## /todos

| Method | Path | What it does |
|---|---|---|
| `GET` | `/todos` |  |
| `POST` | `/todos` | Create a task. Idempotent on `client_token` — a repeat returns 200 + the existing id. |
| `DELETE` | `/todos/<int:todo_id>` |  |
| `PATCH` | `/todos/<int:todo_id>` |  |
| `POST` | `/todos/<int:todo_id>/event` | Put this to-do on the calendar as its linked event — on `date` (else its |
| `DELETE` | `/todos/<int:todo_id>/link` |  |
| `PUT` | `/todos/<int:todo_id>/link` | Link this to-do to `event_id`: from now on they are one thing (see |
| `PATCH` | `/todos/<int:todo_id>/toggle` |  |
| `DELETE` | `/todos/completed` |  |
| `POST` | `/todos/reorder` |  |
| `POST` | `/todos/sync` |  |

## /tags

| Method | Path | What it does |
|---|---|---|
| `GET` | `/tags` |  |
| `POST` | `/tags` |  |
| `DELETE` | `/tags/<path:name>` |  |
| `GET` | `/tags/rules` | The task-tag classifier, as data, so a client can run it offline. |
| `GET` | `/tags/suggestion` | A new-tag proposal mined from the user's untagged history, or {}. |
| `POST` | `/tags/suggestion/answer` | {"name": "...", "accept": true\|false} — yes adds the class to the |
| `GET` | `/tags/suggestions/history` | Every past suggestion + verdict, newest first, incl. hidden flags — |
| `POST` | `/tags/suggestions/revise` | {"name": ..., "accept": bool} changes a past verdict (un-accepting |

## /labels

| Method | Path | What it does |
|---|---|---|
| `POST` | `/labels` | {"kind": "event", "text": "...", "label": "Fitness"} — or `labels` |
| `GET` | `/labels/next` | Items worth labelling, hardest-first. |
| `POST` | `/labels/retrain` | Refit now. The gate still applies — a model that is not better than |

## /timers

| Method | Path | What it does |
|---|---|---|
| `GET` | `/timers` |  |
| `POST` | `/timers` |  |
| `DELETE` | `/timers/<int:tid>` |  |
| `PATCH` | `/timers/<int:tid>` |  |
| `GET` | `/timers/<int:tid>/sessions` |  |
| `POST` | `/timers/<int:tid>/sessions` | Log a session that already happened ("I forgot to start the timer"). |
| `POST` | `/timers/<int:tid>/start` | Start the clock. `start_time` optional — WHEN it started, if not now. |
| `POST` | `/timers/<int:tid>/stop` | Stop the clock. `end_time` optional — WHEN it stopped, if not now. |

## /timer_sessions

| Method | Path | What it does |
|---|---|---|
| `DELETE` | `/timer_sessions/<int:sid>` |  |
| `PATCH` | `/timer_sessions/<int:sid>` |  |

## /counters

| Method | Path | What it does |
|---|---|---|
| `GET` | `/counters` |  |
| `POST` | `/counters` |  |
| `DELETE` | `/counters/<int:cid>` |  |
| `PATCH` | `/counters/<int:cid>` |  |
| `POST` | `/counters/<int:cid>/cashout` |  |
| `GET` | `/counters/<int:cid>/payouts` |  |
| `POST` | `/counters/<int:cid>/press` | One tap. `pressed_at` optional — WHEN it was tapped, if not now. |
| `GET` | `/counters/<int:cid>/presses` |  |

## /counter_presses

| Method | Path | What it does |
|---|---|---|
| `DELETE` | `/counter_presses/<int:pid>` |  |

## /workout

| Method | Path | What it does |
|---|---|---|
| `GET` | `/workout/exercises` |  |
| `POST` | `/workout/exercises` |  |
| `GET` | `/workout/plan-items` | Scheduled sessions in a date range — what the phone's day view asks for. |
| `PATCH` | `/workout/plan-items/<item_id>` |  |
| `GET` | `/workout/plans` |  |
| `DELETE` | `/workout/plans/<plan_id>` |  |
| `GET` | `/workout/plans/<plan_id>` |  |
| `GET` | `/workout/sessions` |  |
| `POST` | `/workout/sessions` |  |
| `DELETE` | `/workout/sessions/<session_id>` |  |
| `PATCH` | `/workout/sessions/<session_id>` |  |
| `GET` | `/workout/templates` |  |
| `POST` | `/workout/templates` |  |
| `DELETE` | `/workout/templates/<template_id>` |  |
| `PATCH` | `/workout/templates/<template_id>` |  |
| `PATCH` | `/workout/templates/<template_id>/approve` |  |

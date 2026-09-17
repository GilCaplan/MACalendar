# Jude — the map

Jude is a Judaic study assistant: ask about Torah, Talmud, halacha, midrash or
machshava and get a cited answer drawn from ~289,000 Sefaria passages, where
every source links back to Sefaria. It is
[its own repository](https://github.com/GilCaplan/JudeTheJudaicChatBot).

**It is not vendored here, and we do not edit it.** It carries a ~1.2 GB corpus
and a ~2 GB vector index and is still being worked on separately; copying it in
would make this repository unclonable and would fork that one. Everything in
this folder is WIRING — how its checkout is found, how its server is started,
how its model calls are made to obey this project's protocol, and the two
clients that talk to it.

This folder is the first consumer of `assistant/integrations/`, the convention
for hosting an external app. What is generic lives there; what is Jude lives
here. See `assistant/integrations/CONVENTION.md`.

## The shape

```
 iPhone ──tailnet──┐
                   ├──> MACalendar API :8080  /jude/*  ──> Jude FastAPI :8000
 Mac Jude.app ─────┘         routes.py, SSE→NDJSON            │
                                                              │ OLLAMA_HOST
                                                              v
                                    integrations/ollama_gate  :11435
                                    model_protocol.hold() per call
                                                              │
                                                              v
                                                  ollama serve :11434
```

| file | what |
|---|---|
| `integration.py` | where the checkout is, how to start it, what environment it gets |
| `routes.py` | the `/jude/*` blueprint — proxy only, no parsing, no execution |
| `app.py` + `ui/` | the standalone Mac app |
| `assets/` | the app icon |
| `build_app.sh` | builds `Jude.app` |

The iOS half is `MACalendar-iOS/MACalendar-iOS/Features/Jude/`.

## Two rules make it part of this system

### 1. Its model calls go through our gate

Jude makes five model calls per question — router, filter, summary, synthesis,
tools — plus an embedding per retrieval, and synthesis alone is 30-90 seconds.
Unarbitrated, that is a fifth door onto the one ollama this machine has, and
`assistant/model_protocol.py` exists precisely because unarbitrated callers
turned a five-token call into 43.9 seconds of queueing.

We cannot put the lock inside Jude, so it goes in front of ollama:
`integrations/ollama_gate.py` takes `hold()` around every generating call and
forwards. `OLLAMA_HOST` points Jude at it.

`OLLAMA_HOST` alone is not enough — Jude hardcodes ollama's address for its
ChromaDB embedding function (`backend/retriever.py:37`), so the retrieval path
would stay ungated. Since we do not edit Jude, the patch rides in as a
`sitecustomize` on the child's `PYTHONPATH`: `integrations/shim/`. With both in
place the gate sees 100% of Jude's ollama traffic.

Priority is **background** by default, which makes Jude YIELD the model to
voice commands. `hold()` is asymmetric — live waits 50ms then goes anyway — so
marking Jude live would have it race the user rather than queue behind them.
`jude.priority: live` overrides.

### 2. It never reaches the internet

Jude defaults to a cloud cascade (Gemini → LLMod → ollama). Every role is
pinned to local ollama on `ollama.model`, so Jude and the assistant share ONE
resident model, and the cloud keys are blanked in the child's environment. A
`.env` in the checkout cannot re-enable them, because Jude's
`_get_fallback_chain` reads the explicit per-role provider first.

`jude.allow_cloud: true` hands that back as a deliberate, named choice. The
gate stays either way — arbitration is about this machine's ollama, not privacy.

## The wire contract

Both clients speak exactly this, and nothing else. `GET /jude/status` never
errors; every other route answers 503 with a `reason` sentence when Jude cannot
serve.

**`GET /jude/status`**

```json
{"name":"jude","label":"Jude","enabled":true,"installed":true,"running":false,
 "ready":true,"path":"…","port":8000,"repo":"…","reason":"",
 "model":"llama3.1:8b","cloud":false,"gated":true,"priority":"background"}
```

`ready` = installed and switched on. `reason` is the sentence to show when
`ready` is false — it is never empty in that case, and always empty otherwise.

**`POST /jude/chat`** → `application/x-ndjson`, one JSON object per line.

```json
{"prompt":"…","chat_id":null,"mode":"qa|study|sources",
 "lang":"en|he","top_k":25,"skip_clarification":false}
```

| event | payload | client must |
|---|---|---|
| `stage` | `{name}` | show it — this is the only progress signal for 30-90s |
| `meta` | `{chat_id, sources[], steps[], mode, study_pool_size, halachic_topic, halachic_label, halachic_seder}` | keep `chat_id`; draw sources + topic badge |
| `token` | `{text}` | append; **batch before rendering** |
| `tool_call` | `{tool, args, result_summary, new_sources[]}` | append to the trace, merge `new_sources` |
| `clarification` | `{chat_id, question, options[]}` | offer the options; re-ask with `skip_clarification:true` to bypass |
| `topic_pivot` | `{previous_topic, candidate_topic}` | offer confirm/dismiss; **non-blocking**, the answer keeps streaming |
| `done` | `{timing{route_ms, retrieve_ms, filter_ms, synth_first_token_ms, synth_total_ms, total_ms}}` | finalise |
| `error` | `{message}` | show it and stop |

A **source**:

```json
{"ref":"Shabbat 25b","book":"Shabbat","category":"Talmud",
 "en_text":"…","he_text":"…","score":0.31,"is_primary":true}
```

`is_primary` is present only for a detected halachic topic, where retrieval is
dual: primary sources come from the topic's canonical hierarchy (Torah →
Mishnah → Talmud → Rambam → Shulchan Arukh) and are cited first.

A **step** (for the trace): `{module, duration_ms, result{…}}`.

**Other routes.** `GET /jude/chats` → `[{id, title, mode, created_at, user}]`.
`GET /jude/chats/<id>/history` → `[{role, content, …}]`.
`DELETE /jude/chats/<id>`. `PUT /jude/chats/<id>/topic` `{topic}`.

**Sefaria links.** Strip surrounding brackets; split off the trailing section;
`Book Name` → `Book_Name`, `1:2:3` → `1.2.3`, giving
`https://www.sefaria.org/Book_Name.1.2.3`. **Talmud is the exception** — our
coordinates are chapter-based and Sefaria uses daf notation (2a, 3b), so a
Talmud ref links to the tractate overview, `https://www.sefaria.org/Shabbat`.
Anything unparseable falls back to a Sefaria search URL.

## The surfaces

**macOS — its own app.** `python -m assistant.jude.app`, or `Jude.app`.
Separate from the calendar for the same reason the thinking HUD is: studying a
sugya is not a thing you do inside a calendar, and the window should outlive
the calendar window. It talks to `127.0.0.1:8080/jude/*` — the same endpoint
the phone uses — rather than to Jude directly, so there is one client protocol
rather than two that drift.

**iOS — a tab**, toggled in Settings like Coursework, Workout and Timer, and
off by default: it needs a checkout on the Mac, and a tab that can only say
"not installed" is not a feature. There is deliberately no offline cache and no
queue — the corpus is gigabytes, and unlike "add lunch at 1", a question
replayed three hours later is answered to nobody.

## Three things that will bite

- **Batch the tokens.** The previous Mac app inserted every token into a
  `QTextBrowser` through a cursor, so a 2,000-token answer triggered 2,000 full
  document relayouts. That was the lag. Accumulate and repaint on a timer.
- **`stage` is the only thing the user has for up to 90 seconds.** A surface
  that hides it looks hung. This is the reason the trace is not an afterthought.
- **`ready` is not `running`.** An integration that autostarts is ready before
  it is running — the first question is what starts it, and that first question
  can take two minutes while the index loads.

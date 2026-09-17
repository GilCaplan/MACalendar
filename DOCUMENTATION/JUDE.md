# Jude — the Judaic study assistant

*Integrated 2026-09-17.*

Jude answers questions about Torah, Talmud, halacha, midrash and machshava
from ~289,000 Sefaria passages: a five-stage pipeline (route → retrieve →
filter → synthesise → tools) over a ChromaDB index, streaming a cited answer
where every source links back to Sefaria. It is
[its own repository](https://github.com/GilCaplan/JudeTheJudaicChatBot).

## It is NOT vendored here, and that is the design

Jude carries a ~1.2 GB corpus and a ~2 GB vector index, and it is still being
worked on separately. Copying it into this repository would make this one
unclonable and would fork that one. So it stays where it is, and this project
points at a checkout:

```bash
# beside your MACalendar checkout
git clone https://github.com/GilCaplan/JudeTheJudaicChatBot
cd JudeTheJudaicChatBot
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# the corpus + index (see that repo's README — they are on Hugging Face)
```

then in `config.yaml`:

```yaml
jude:
  enabled: true
  path: "../JudeTheJudaicChatBot"   # relative to this repo, or absolute
```

`MACALENDAR_JUDE_PATH` overrides the path. A directory only counts as a Jude
checkout when it contains `backend/main.py`, so pointing at the wrong folder
says "that isn't Jude" rather than failing later inside uvicorn.

**Nothing here requires it.** Without a checkout, `jude.enabled` stays false,
the Mac toolbar button is not drawn, the iOS tab is off, and `/jude/status`
answers with a sentence naming the repository. That is the whole degradation.

## Two rules make it part of this system

### 1. Its LLM calls are this project's LLM calls

Jude ships a cloud fallback cascade: Gemini, then LLMod, then local Ollama.
That default is wrong here in a way that matters — this project does not touch
the internet (`tests/unit/test_offline.py` blocks every non-loopback socket and
fails the build if that stops being true), and a question about one's own
practice is not a thing to hand to someone else's server by accident.

So `jude.bridge.environment()` starts Jude's server with every role pinned to
local Ollama:

```
ROUTER_PROVIDER=ollama   ROUTER_MODEL=<ollama.model>
FILTER_PROVIDER=ollama   FILTER_MODEL=…
SUMMARY_PROVIDER=ollama  SUMMARY_MODEL=…
SYNTH_PROVIDER=ollama    SYNTH_MODEL=…
TOOLS_PROVIDER=ollama    TOOLS_MODEL=…
GEMINI_API_KEY=  LLMOD_API_KEY=  LLM_API_KEY=  OPENAI_API_KEY=
OLLAMA_HOST=<ollama.base_url>
```

The model is `ollama.model` unless `jude.model` overrides it — so Jude and the
assistant share **one** resident model rather than making a laptop hold two.
A `.env` in the Jude checkout cannot re-enable the cloud, because Jude's
`_get_fallback_chain` reads the explicit per-role provider first.

`jude.allow_cloud: true` hands all of that back: Jude is then started with the
environment it would have had on its own. A deliberate, named choice — and from
then on the traffic is Jude's, not the assistant's.

### 2. It is reached through this API

The phone never talks to Jude. It POSTs to `http://<mac>:8080/jude/chat` with
the same `X-API-Key`, over the same tailnet hop as everything else, and the
server proxies to Jude on localhost.

| route | what |
|---|---|
| `GET /jude/status` | enabled / installed / running / ready, the model, and `reason` — the sentence to show when it is not ready. Never an error. |
| `POST /jude/chat` | `{prompt, chat_id?, mode?, lang?, top_k?}` → **NDJSON** |
| `GET /jude/chats` | past conversations |
| `GET /jude/chats/<id>/history` | one conversation |
| `DELETE /jude/chats/<id>` | forget one |

Three reasons for the proxy rather than a second address:

- the phone keeps one host, one key, one hop, and learns nothing new;
- Jude's own port never has to leave the machine — it binds 127.0.0.1 and has
  no auth of its own, so a tailnet-wide FastAPI would be a hole;
- Jude streams Server-Sent Events, and every client here already renders the
  NDJSON `/voice/stream` uses. Translating once, in the server, beats writing
  a second wire format into each client.

The event types pass through unchanged: `stage`, `meta`, `token`, `tool_call`,
`clarification`, `topic_pivot`, `done`, `error`.

**The brain is untouched.** These routes are HTTP plumbing; nothing in them
parses or executes anything (CLAUDE.md's rule for `server.py`). Jude is not
wired into `assistant/engine/` and cannot be asked to create an event.

## The surfaces

**macOS — its own app.** `python -m assistant.jude_app`, started by
`Launch Calendar.command` when `jude.enabled` is on, and reachable from the
calendar toolbar's 📖 button. Separate for the same reason the thinking HUD is
separate: studying a sugya is not something you do inside a calendar, and the
window should outlive the calendar window. It talks to `127.0.0.1:8080/jude/*`
— the same endpoint the phone uses — rather than to Jude directly, so there is
one client protocol rather than two that drift.

**iOS — a tab**, toggled in Settings › Tabs like Coursework, Workout and Timer,
and **off by default**: it needs a checkout on the Mac, and a tab that can only
say "not installed" is not a feature. When the Mac is away it says so. There is
deliberately no offline cache and no queue — the corpus is gigabytes, and
unlike a voice command ("add lunch at 1"), a question replayed three hours
later is answered to nobody.

## Starting and stopping

`bridge.ensure_running()` starts `uvicorn backend.main:app` inside the checkout
— with the checkout's own `.venv/bin/python` if it has one, since Jude needs
chromadb, fastapi and ollama and this project does not depend on any of them.
It waits up to 90 s, because loading the index on a cold page cache genuinely
takes that long, and it watches for the process dying so "it failed" is never
said about something that is still starting. Output goes to `server.log` inside
the checkout — which is where that repo's own launcher puts it.

A Jude that was already listening when we found it is somebody else's, and
`stop()` leaves it alone.

**A standalone launcher, like the HUD's.** `Jude.app` — `scripts/build_jude_
app.sh [--install]`, same osacompile-wrapper-around-a-shell-script shape as
`scripts/build_hud_app.sh`, same reason: a double-clickable icon beside
`MACalendar.app` and `MACalendar HUD.app` for the two cases that keep coming
up once this is a window you actually use — it was closed and you want it
back without restarting the API and the calendar GUI underneath it, or it is
running old code (`launch_jude.sh` kills a running one first, same as the
HUD's script). It does not start the assistant API or check `jude.enabled` —
`assistant.jude_app` already talks to whatever API is running on
`127.0.0.1:$MACALENDAR_API_PORT` and reports "not available" itself, exactly
like the iOS tab does. Both `.app` bundles are gitignored build artifacts,
rebuilt from `launch_jude.sh`/`launch_hud.sh` so the AppleScript inside them
stays reviewable like any other source file.

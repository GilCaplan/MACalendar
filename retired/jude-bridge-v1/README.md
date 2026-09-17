# jude-bridge-v1 — the first Jude integration

*Retired 2026-09-17, replaced by `assistant/integrations/` + `assistant/jude/`.*

The first attempt at wiring Jude in. Its design was sound in two places and
wrong in three, and all five are why the replacement looks the way it does.

## What it got right, and the replacement kept

- **Not vendoring Jude.** A checkout beside this repo, found by a marker file,
  with every "it isn't here" message naming the repository to clone.
- **Reached through this API, not directly.** One host, one key, one tailnet
  hop; Jude's own port never leaves the machine.
- **Pinned to local ollama**, with the cloud keys blanked so a stray `.env` in
  the checkout could not re-enable the cascade.

## What was wrong

**1. It was a fifth door onto ollama.** `bridge.environment()` set
`OLLAMA_HOST` and stopped there, so Jude's five model calls per question —
router, filter, summary, synthesis, tools — took no part in
`assistant/model_protocol.py`. Synthesis alone is a 30-90 second call, and it
ran alongside voice commands rather than queueing with them. This is precisely
the contention that module was written to end.

Worse, `OLLAMA_HOST` did not even cover what it appeared to: Jude hardcodes
ollama's address for its ChromaDB embedding function
(`backend/retriever.py:37`), so the retrieval path was never redirected at all.
The setting looked like a gate and was a partial redirect.

**2. The Mac window relayed the whole document per token.** `jude_app.py`
inserted every token into a `QTextBrowser` through a cursor, so a 2,000-token
answer triggered 2,000 full document relayouts. Markdown was never rendered —
the code says the answer is "markdown-ish" and gives up — and `_on_finished`
fired another HTTP round trip. This was the reported lag.

**3. Both clients were a fraction of Jude.** `jude_app.py` was 321 lines and
`JudeView.swift` 266, against a 2,484-line web UI. Missing: the chat list,
source cards, primary/secondary grouping, the Hebrew toggle, Sefaria links, the
pipeline trace, clarification prompts, topic-pivot confirmation, the top-k
slider and the language toggle. `PUT /api/chats/<id>/topic` had no proxy route
at all, so a topic pivot could be shown but never confirmed.

## What replaced it

`assistant/integrations/` — a general convention for hosting an external app
(`CONVENTION.md`), with `ollama_gate.py` taking `model_protocol.hold()` around
every call in front of ollama, and `shim/sitecustomize.py` closing the
hardcoded-address hole without editing Jude. `assistant/jude/` is that
convention's first consumer and holds everything Jude: integration, routes, Mac
app, UI, icon, build script.

The last commit that ran this version is tagged `jude-bridge-v1`.

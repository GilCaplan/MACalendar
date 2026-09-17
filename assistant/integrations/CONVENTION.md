# Integrating another program into this assistant

An **integration** is an external app — its own repository, its own
dependencies, its own server — that this assistant starts, gates and proxies,
**without vendoring it and without editing it**. Jude
(`assistant/jude/`) is the first; this file is how to add the second.

The rule underneath all of it: *the assistant hosts the program; it does not
absorb it.* A program that has been absorbed has been forked, and the fork
starts drifting the week it is made.

## Why not just vendor it

Because the two failure modes are worse than the plumbing:

- **Copy it in** and this repository carries somebody else's corpus, index and
  dependency tree. Jude alone is ~3.2 GB of data and needs chromadb, fastapi
  and uvicorn, none of which this project depends on. And the copy is a fork:
  the upstream keeps moving and yours does not.
- **Run it beside** with no wiring and it is a second system sharing this
  machine's ollama, this machine's ports and this user's attention, arbitrated
  by nothing. That is measurably bad — see "the fifth door" below.

## The five promises

An integration must:

1. **Be optional.** Not installed, not enabled, or refusing to start are NORMAL
   states. Each produces a sentence a person can act on — never a traceback,
   never a surface that silently does nothing. Nothing in the assistant may
   require it.
2. **Be found, not assumed.** `marker` is a file that must exist inside the
   checkout. Pointing `path` at the wrong folder then says "that isn't Jude"
   instead of failing later, deep inside someone else's import.
3. **Obey the model protocol.** If it touches ollama it goes through
   `ollama_gate`. See below.
4. **Be reached through this API.** Clients get one host, one key, one tailnet
   hop; the integration's own port stays on loopback, because it almost
   certainly has no authentication of its own.
5. **Keep the brain out of it.** An integration's routes are HTTP plumbing.
   They do not parse and do not execute — `assistant/engine/` is not involved
   and the integration cannot be asked to create an event. This is CLAUDE.md's
   rule for `server.py`, and it is the reason an integration's blueprint lives
   in the integration's folder rather than in that file.

## The fifth door

`assistant/model_protocol.py` exists because four processes on this Mac share
one ollama, and nothing arbitrated it: a trivial five-token call took **2.0s,
then 42.5s, then 43.9s**, none of it inference. Every caller in this repository
now takes `hold()`, and a test reads the tree to prove there is no fourth door.

An integration is a fifth door, and it is one you cannot lock from the inside —
it is somebody else's code. **So the lock goes outside the process, in front of
ollama.** `ollama_gate.start(port, upstream, priority)` runs a proxy that
speaks ollama's own HTTP API, takes `hold()` around each generating call, and
forwards. You point the child at it with `OLLAMA_HOST` and it needs to know
nothing.

Two details that decide whether the gate actually works:

- **Default the priority to `background`.** `hold()` is asymmetric: live waits
  50ms then proceeds ANYWAY, so two live callers do not arbitrate at all. An
  integration marked live therefore RACES the user's voice commands instead of
  queueing behind them, which is the contention the gate exists to remove.
  Background makes it yield. An integration's answer is tens of seconds of
  inference, so yielding costs it nothing perceptible; a voice command queued
  behind a synthesis is the whole difference between working and broken.
- **Check for hardcoded addresses.** `OLLAMA_HOST` only helps for calls that
  read it. Jude hardcodes ollama's URL for its ChromaDB embedding function, so
  the gate had a hole in the retrieval path — and a gate with a hole reads as
  covered, which is worse than no gate. Since we do not edit the child, the fix
  rides in as `shim/sitecustomize.py` on its `PYTHONPATH`. **Grep the child for
  `11434` before you believe the gate is complete.**

## Adding one

### 1. A config block

In `assistant/config.py`, beside `JudeConfig`. `enabled`, `path`, `port`,
`autostart` are the minimum; add `gate_port` and `priority` if it uses ollama.
Mirror it into `config.example.yaml` — `config.yaml` is gitignored.

### 2. A folder, holding everything

```
assistant/<name>/
  __init__.py
  integration.py     the Integration subclass
  routes.py          the Flask blueprint, url_prefix="/<name>"
  app.py + ui/       a Mac app, if it has one
  assets/            its icon
  build_app.sh       builds <Name>.app
  ARCHITECTURE.md    the map, and the wire contract the clients build against
```

Everything about the integration lives here — the same rule the engine's stage
folders follow (CLAUDE.md: *"Each STAGE owns a FOLDER, and everything about it
lives there"*). Nothing about it leaks into `server.py`, `pipeline.py` or the
calendar UI.

### 3. The subclass

```python
class ThingIntegration(Integration):
    name = "thing"
    label = "Thing"
    repo = "https://github.com/…"
    marker = os.path.join("server", "main.py")   # proves it's the right checkout

    def config(self):
        return load_config().thing

    def command(self, python):
        return [python, "-m", "uvicorn", "server.main:app",
                "--host", "127.0.0.1", "--port", str(self.port())]

    def environment(self):      # only if it needs pinning or the gate
        ...

    def blueprint(self):
        from assistant.thing.routes import blueprint
        return blueprint
```

You inherit `root()`, `status()`, `enabled()`, `port()` and the env override
`MACALENDAR_THING_PATH`. `process.ensure_running()` handles spawn, wait-for-port
and "it died while starting" — it never imports your module, it just calls
those methods.

### 4. One line in the registry

Add it to the tuple in `registry.all_integrations()`. That is the only file
under `integrations/` that learns your name; `base` and `process` stay generic
on purpose, which is what makes the next one cheap.

### 5. Clients

`GET /integrations` already reports it — one status shape means a client that
can draw one can draw yours. Write `ARCHITECTURE.md`'s wire contract FIRST and
build both clients against it; that is what stops the Mac app and the iOS app
becoming two dialects.

## Things that have already bitten

- **The client is not the protocol.** The Mac app talks to
  `127.0.0.1:8080/<name>/*` — this project's API — and not to the integration
  directly, even though it is on the same machine. Talking straight to it
  because it is local is how you get two clients of two protocols that drift.
- **`ready` is not `running`.** An integration that autostarts is ready before
  it is running; the first request is what starts it, and that request can take
  two minutes while an index loads. Clients must distinguish these or they
  report a healthy integration as broken.
- **Stream with `read1`, not `read`.** `read(n)` blocks until it has all n
  bytes, which holds tokens back until enough pile up. It turns a live stream
  into a stuttering one and is the most common way a streaming proxy ruins the
  thing it is proxying.
- **Don't forward hop-by-hop headers.** Forwarding `Content-Length` or
  `Transfer-Encoding` makes client and proxy disagree about framing, which
  looks like an answer truncating at random.

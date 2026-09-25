"""Flask REST API — exposes calendar, todos, voice, and config endpoints.

Start with:
    python -m assistant.api           # localhost:8080
    python -m assistant.api --lan     # 0.0.0.0:8080  (iPhone access over LAN)
"""

from __future__ import annotations

import hashlib
import re

import datetime
import logging
import os
from typing import Any

import yaml

from assistant import model_protocol as _mp
from flask import Flask, jsonify, request

from assistant.config import AppConfig, ConfigError, load_config as _load_config_file


def load_config(path: str = "config.yaml") -> AppConfig:
    """config.yaml is local-only (gitignored); fall back to the example, then defaults (CI)."""
    try:
        return _load_config_file(path)
    except ConfigError:
        try:
            return _load_config_file("config.example.yaml")
        except ConfigError:
            return AppConfig()
from assistant.db import get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_stt = None

# ---------------------------------------------------------------------------
# iOS background verification store
# {token: {"correction": dict|None, "ready": bool, "expires": float}}
# ---------------------------------------------------------------------------
import threading as _threading
import time as _time
_verify_store: dict = {}
_verify_lock = _threading.Lock()

# ---------------------------------------------------------------------------
# Confirm-create store (DEVQA Q9): an interrogative create the engine parsed
# but did not run. {token: {"proposal": [...], "expires": float,
#                          "memory_id": int|None, "source": str,
#                          "result": dict|None}}
# `result` is filled on the first answer and replayed on any repeat, so a
# double-tapped Add creates once — the same intent as the todo client_token,
# extended to events, which have no idempotency key of their own.
# ---------------------------------------------------------------------------
_confirm_store: dict = {}
_confirm_lock = _threading.Lock()
#: Long enough to read a proposal and decide, short enough that an answer given
#: an hour later doesn't book something the speaker has forgotten asking about.
CONFIRM_TTL_SEC = 600


def _confirm_sweep(now: "float | None" = None) -> None:
    """Drop expired proposals. Called on every touch of the store — there is no
    timer here on purpose: a handful of dicts does not deserve a thread."""
    now = _time.time() if now is None else now
    with _confirm_lock:
        for tok in [t for t, e in _confirm_store.items() if e.get("expires", 0) <= now]:
            _confirm_store.pop(tok, None)


def change_token() -> str:
    """The body of `GET /changes`, as a plain string.

    A module-level function rather than only the route, because
    `/sync/bootstrap` quotes the same token and now lives in
    `assistant/features/calendar/routes.py` — a blueprint cannot call a view
    closure defined inside `create_app()`, and re-deriving the token there
    would be a second definition of "has anything changed?" free to drift from
    this one.
    """
    import os as _os
    path = get_db().path
    try:
        st = _os.stat(path)
        return f"{st.st_mtime:.6f}-{st.st_size}"
    except OSError:
        return "0"


def create_event_from_body(data: dict) -> "tuple[dict, int]":
    """POST /events' body → the created event. Shared with /voice/confirm so an
    accepted proposal is created by exactly the code a client's own POST would
    have run — one create path, no second way into db.py."""
    required = {"title", "date", "start_time", "end_time"}
    missing = required - data.keys()
    if missing:
        return {"error": f"Missing fields: {missing}", "code": 400}, 400
    return {"id": get_db().create_event_from_dict(data)}, 201


def create_todo_from_body(data: dict) -> "tuple[dict, int]":
    """POST /todos' body → the created task, idempotent on `client_token`.
    Shared with /voice/confirm (see create_event_from_body)."""
    title = data.get("title", "").strip()
    if not title:
        return {"error": "Missing 'title' field", "code": 400}, 400
    db = get_db()
    # Creation is idempotent on `client_token`: the client mints one token
    # per task the user asked for and sends it on the live POST and on every
    # replay of the same queued create. Without this a create that reached
    # the Mac but whose reply was lost — or one flushed twice by overlapping
    # sync passes — landed as another copy of the task; that is how 32
    # "buy groceries" rows accumulated in the Today list (2026-09-04..06).
    token = str(data.get("client_token") or "").strip()
    if token:
        already = db.get_todo_by_client_token(token)
        if already is not None:
            return {"id": already["id"], "duplicate": True}, 200
    # A count typed into the title works the same as one spoken: "pasta x5"
    # is one task for five, not a task literally called "pasta x5".
    from assistant.intent.quantity import split_quantity
    title, parsed_qty = split_quantity(title)
    try:
        quantity = max(1, int(data.get("quantity") or parsed_qty))
    except (TypeError, ValueError):
        quantity = parsed_qty
    list_name = data.get("list_name", "today")
    todo_cfg = load_config().todo
    # Second net, for callers that send no token at all. `client_token` is
    # the precise key, but the partial unique index only referees non-empty
    # tokens — so a token-less client (the HUD's revert POST, a curl, a
    # script) could still stack copies of one task. When the same open task,
    # spelled the same, in the same list, was created seconds ago, read the
    # repeat as a replay of that create and hand back the row it made.
    # Completed rows never match, so re-adding a task you ticked off still
    # works; the window is config'd (todo.duplicate_window_seconds, 0=off).
    if not token:
        recent = db.find_recent_open_todo(
            title, list_name, int(getattr(todo_cfg, "duplicate_window_seconds", 120)))
        if recent is not None:
            logger.info("POST /todos: token-less repeat of open todo %s (%r) "
                        "inside the duplicate window — returning it",
                        recent["id"], title)
            return {"id": recent["id"], "duplicate": True,
                    "reason": "recent-identical"}, 200
    tags = data.get("tags") or []
    if not tags:
        # Client didn't say — server-side "tag mode", else infer from the
        # title, the same order of precedence voice creation uses.
        if todo_cfg.auto_tag:
            tags = [todo_cfg.auto_tag]
        elif getattr(todo_cfg, "auto_tag_infer", True):
            from assistant.actions.todo.tagging import suggest_tags
            tags = suggest_tags(title, [r["name"] for r in db.get_tags()])
    todo_id = db.create_todo(
        title=title,
        list_name=list_name,
        priority=data.get("priority", "none"),
        due_date=data.get("due_date", ""),
        notes=data.get("notes", ""),
        tags=tags,
        quantity=quantity,
        client_token=token,
    )
    return {"id": todo_id}, 201


def build_stt(cfg):
    """STT provider per config.stt_engine (shared with the Mac pipeline)."""
    if cfg.stt_engine == "mlx":
        from assistant.stt.mlx_whisper_stt import MlxWhisperSTT
        return MlxWhisperSTT(cfg.mlx_whisper)
    if cfg.stt_engine == "google":
        from assistant.stt.google_stt import GoogleSTT
        return GoogleSTT(cfg.google_stt)
    from assistant.stt.whisper_stt import WhisperSTT
    return WhisperSTT(cfg.whisper)


def _get_stt():
    global _stt
    if _stt is None:
        cfg = load_config()
        _stt = build_stt(cfg)
    return _stt


def warm_up_components() -> None:
    """Load Whisper, spaCy and the LLM model up front (in a daemon thread) so
    the first phone command doesn't pay 10–20 s of cold starts."""
    def _go() -> None:
        import time as _t
        from assistant.engine import load_config as _engine_cfg
        from assistant.engine import llm as _gen
        t0 = _t.perf_counter()
        for name, fn in (("rule parser", _gen.get_rule_parser),
                         ("whisper", _get_stt),
                         ("llm parser", lambda: _gen.get_parser(_engine_cfg()))):
            try:
                fn()
            except Exception as e:
                logger.warning("Warm-up of %s failed: %s", name, e)
        try:
            rp = _gen.get_rule_parser()
            if rp is not None:
                rp.analyze("meeting tomorrow at 3pm")  # forces spaCy + datetime models
        except Exception:
            pass
        logger.info("Warm-up finished in %.1fs", _t.perf_counter() - t0)
    _threading.Thread(target=_go, daemon=True, name="warm-up").start()


def retry_pending_once(run_transcript, mem, budget: int) -> int:
    """One pass of the pending queue. Returns how many batches were run.

    Extracted from the daemon loop so it can be TESTED — the rule it enforces is
    a correctness rule and a rule with no test is a rule that regresses. Driving
    the thread from a test instead meant hooking `sleep`, which is flaky.

    ONE STREAM PER SOURCE (Gil, 2026-09-10). Commands are only ever concatenated
    with others from the SAME device. Merging across sources is silent and
    expensive three ways: a `test` sandbox's words would execute as the user's
    real command; the Mac's queue and the phone's would parse as one utterance;
    and the whole batch would be attributed to one source, defeating
    `weekly_review.py`'s test-traffic filter — the filter that had been
    inflating real-usage accuracy to 83%.

    `pending.source` was already recorded on every row and simply never read.
    """
    from assistant.engine.ingest.coalesce import coalesce_groups, wrap

    def _field(row, name, default):
        """A pending row is a dict here and a `sqlite3.Row` in production, and
        neither `.get` nor `in` works on both — `sqlite3.Row` has no `.get`, and
        a bare `in` on it tests VALUES. `keys()` is the one thing both answer."""
        try:
            return row[name] if name in row.keys() else default
        except (AttributeError, TypeError):
            return row.get(name, default)

    rows = mem.pending()
    if not rows:
        return 0
    live = []
    for row in rows:
        if row["attempts"] >= 5:
            mem.resolve_pending(row["id"], "failed", "gave up after 5 attempts")
        elif (row["transcript"] or "").strip():
            live.append(row)          # empties would desync the batch map
    # ONE STREAM PER DEVICE, not per source KIND (2026-09-10). This grouped on
    # `row["source"]` — "mac"|"ios"|"test" — so every iPhone on the tailnet was
    # the SAME stream and two phones' queued commands were concatenated into one
    # utterance. `model_protocol.stream_key` is the identity; it falls back to
    # source-only for rows a client wrote without an id.
    from assistant.model_protocol import stream_key
    from assistant.model_protocol import priority_for as stream_priority
    by_source: dict = {}
    for row in live:
        # The stream was RESOLVED AT THE DOOR, where the token was available.
        # Re-deriving it here would have to assume a trust level this code
        # cannot check, and assuming "trusted" is exactly the mistake. Rows
        # written before the column existed fall back to source-only grouping.
        key = (_field(row, "stream", "")
               or stream_key(row["source"], _field(row, "device", "")))
        by_source.setdefault(key, []).append(row)

    ran = 0
    # REAL DEVICES FIRST (Gil, 2026-09-10: *"real device takes precedence over
    # test, so push real device to the front of the queue of requests"*).
    #
    # A flush can run many batches back to back, and each one holds the engine's
    # run lock for the length of a parse. Iterating a dict meant a `test`
    # sandbox's backlog could sit in front of a person's — the phone's commands
    # waiting behind a sandbox's, which is exactly backwards. Ordering by
    # priority costs nothing and cannot starve the test rows: every stream still
    # runs in this same pass, just later.
    ordered_streams = sorted(
        by_source.items(),
        key=lambda kv: (stream_priority(kv[1][0]["source"]) != "live",
                        _field(kv[1][0], "ts", 0.0)))
    for stream, src_rows in ordered_streams:
        # A ROW THAT HAS ALREADY FAILED ONCE RUNS ALONE (2026-09-10).
        #
        # A batch is all-or-nothing: `parse == "error"` bumps EVERY row in it.
        # So one unparseable command took its batch-mates down with it — five
        # passes, five collective failures, and four perfectly good commands
        # marked `failed` having never once been tried on their own. The user
        # loses commands they gave, because of a command they also gave.
        #
        # Coalescing is an OPTIMISATION (one parse instead of five). Retrying
        # is CORRECTNESS. So the optimisation is dropped the moment it starts
        # costing correctness: first attempt batches, every attempt after that
        # is individual, which guarantees each command its own chance before
        # anything is given up on.
        src_rows = sorted(src_rows,
                          key=lambda r: (r["attempts"] > 0, _field(r, "ts", 0.0)))
        # The KEY identifies the stream; the SOURCE is what the engine wants.
        # `EngineState.source` is "mac"|"ios"|"test" and a key like "ios:A1B2"
        # is not one of them — passing the key through would put an unknown
        # source on every trace, vocabulary correction and memory row, and
        # `weekly_review.py` filters on exactly that value.
        src = src_rows[0]["source"] or "ios"
        taken = 0
        # `coalesce_groups`, not `coalesce`: the group IS the row mapping.
        # Re-deriving it by counting ")and(" in the rendered string
        # desynchronises the moment a transcript contains that literal, and
        # then the wrong row gets marked done.
        fresh = [r for r in src_rows if r["attempts"] == 0]
        alone = [r for r in src_rows if r["attempts"] > 0]
        groups = (coalesce_groups([r["transcript"] for r in fresh], budget)
                  + [[r["transcript"]] for r in alone])
        ordered = fresh + alone
        for group in groups:
            batch_rows = ordered[taken:taken + len(group)]
            taken += len(group)
            batch = wrap(group)
            logger.info("📱 Retrying %d queued command(s) from %s: %s",
                        len(batch_rows), stream, batch[:80])
            result = run_transcript(batch, source=src)
            ran += 1
            for row in batch_rows:
                if result.get("parse") == "error":
                    mem.bump_pending(row["id"])
                else:
                    mem.resolve_pending(row["id"], "done", result.get("message", ""))
    return ran


def start_pending_retry_loop(run_transcript, interval: float = 30.0) -> None:
    """Daemon: whenever the LLM is reachable, re-run queued commands (max 5
    tries each). Queued inputs are the engine's step-0 case in the flesh —
    several commands parked while the model was away — so they are coalesced
    into ("…")and("…") batches under the token budget, PER SOURCE, and each
    batch costs one parse; overflow batches run sequentially."""
    def _loop() -> None:
        from assistant.intent.memory import get_memory
        while True:
            _time.sleep(interval)
            try:
                cfg = load_config()
                from assistant.engine import llm as _llm
                if not _llm.is_reachable(cfg):
                    continue
                budget = int(getattr(cfg.engine, "coalesce_max_tokens", 300))
                retry_pending_once(run_transcript, get_memory(), budget)
            except Exception as e:
                logger.warning("📱 Pending retry loop error: %s", e)
    _threading.Thread(target=_loop, daemon=True, name="pending-retry").start()


def create_app() -> Flask:
    app = Flask(__name__)
    _no_bg = os.environ.get("MACALENDAR_NO_WARMUP") == "1"   # tests
    # Under --reload, Werkzeug runs this module twice: once in the watcher that
    # does nothing but restart the child, and once in the child that serves. The
    # watcher has no use for 5.8 GB of llama, a Whisper model and spaCy, and
    # loading them there doubles both memory and startup. WERKZEUG_RUN_MAIN is
    # set only in the child; it is absent entirely when the reloader is off, so
    # the normal path is unaffected.
    _is_reload_watcher = (
        os.environ.get("WERKZEUG_RUN_MAIN") is None
        and os.environ.get("MACALENDAR_RELOADING") == "1"
    )
    if not _no_bg and not _is_reload_watcher:
        warm_up_components()

    # ------------------------------------------------------------------
    # Optional API-key auth — enforced via before_request so every route is
    # covered automatically (a per-route @decorator is easy to forget on a
    # new endpoint; this can't be skipped by accident). /health stays open
    # so external monitoring doesn't need the key.
    # ------------------------------------------------------------------

    @app.before_request
    def _enforce_api_key():
        if request.path == "/health":
            return None
        cfg = load_config()
        expected = cfg.api.key
        if expected:
            provided = request.headers.get("X-API-Key", "")
            if provided != expected:
                return jsonify({"error": "Unauthorized", "code": 401}), 401
        return None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/health")
    def health():
        cfg = load_config()
        db = get_db()
        llm_status = "ok"
        if cfg.llm_engine == "ollama":
            try:
                import requests as _rq
                r = _rq.get(f"{cfg.ollama.base_url}/api/tags", timeout=1.5)
                names = [m.get("name", "") for m in r.json().get("models", [])]
                llm_status = "ok" if any(n.startswith(cfg.ollama.model.split(":")[0]) for n in names) \
                    else f"model {cfg.ollama.model} not pulled"
            except Exception:
                llm_status = "offline"
        return jsonify({
            "status": "ok",
            "llm": f"{cfg.llm_engine} ({getattr(cfg, cfg.llm_engine).model}) — {llm_status}",
            "llm_engine": cfg.llm_engine,
            "llm_status": llm_status,
            "db": db.path,
        })

    @app.post("/heartbeat")
    def heartbeat():
        """A device (the phone, another client) reports it is alive and
        connected. `assistant doctor` reads the last beat per source to tell a
        connected surface from a silent one. Records server-side under the
        source name so no client needs shared-filesystem access."""
        body = request.get_json(silent=True) or {}
        src = (body.get("source") or "unknown").strip().lower()[:32]
        try:
            from assistant.heartbeat import beat
            beat(f"client-{src}", device=body.get("device"))
        except Exception:
            pass
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # Background verification polling (iOS)
    # ------------------------------------------------------------------

    @app.get("/voice/verify/<token>")
    def voice_verify(token: str):
        """Poll for background LLM verification of a rule-path voice command.

        iOS calls this once ~5 s after receiving a voice response with a
        'verify_token'. Returns immediately with {"pending": true} if not ready yet.

        When ready, returns {"ok": true} or a correction object:
          • minor: {"ok": false, "severity": "minor", "patch": {...}, "speech": "...", "refresh": "..."}
          • major: {"ok": false, "severity": "major", "action": "...", "parameters": {...},
                    "speech": "...", "refresh": "..."}

        A destructive correction (the check undid a row it decided you didn't
        ask for) also carries a "revert" list — ready-to-POST bodies that
        re-create what was removed, one per removed row:
          "revert": [{"kind": "event"|"todo", "body": {...POST /events|/todos...}}]
        so the client can offer one-tap revert (re-POST the body). Absent when
        nothing was removed.

        iOS re-executes major corrections via the normal REST endpoints
        and plays the speech string via AVSpeechSynthesizer.
        The token is consumed on first ready response.
        """
        with _verify_lock:
            entry = _verify_store.get(token)
        if entry is None:
            return jsonify({"error": "Unknown or expired token", "code": 404}), 404
        if not entry["ready"]:
            return jsonify({"pending": True})
        # Consume the token
        with _verify_lock:
            _verify_store.pop(token, None)
        return jsonify(entry["correction"])

    # ------------------------------------------------------------------
    # Voice endpoints
    # ------------------------------------------------------------------

    def _run_transcript(transcript: str, trace: "Trace | None" = None,
                        source: str = "ios", device: str = "",
                        stream: str = "", current_view: str = "month",
                        trace_run: str | None = None,
                        supports_edit: bool = False,
                        supports_confirm: bool = False) -> dict[str, Any]:
        """The brain lives in assistant.engine now — the 7-step deep track
        (DOCUMENTATION/ENGINE.md). This wrapper exists so every voice route
        and the pending-retry loop share one entry point.

        It also parks a `confirm_create` proposal in the token store on the way
        out, so every voice route offers the prompt identically — the token and
        its TTL are HTTP bookkeeping, which is what this layer is for."""
        from assistant.engine import run_transcript as _engine_run
        resp = _engine_run(transcript, trace=trace, source=source, device=device,
                           stream=stream,
                           current_view=current_view, trace_run=trace_run,
                           supports_edit=supports_edit,
                           supports_confirm=supports_confirm)
        if resp.get("parse") == "confirm_create" and resp.get("proposal"):
            import uuid as _uuid
            _confirm_sweep()
            token = str(_uuid.uuid4())
            with _confirm_lock:
                _confirm_store[token] = {
                    "proposal": resp["proposal"],
                    "memory_id": resp.get("memory_id"),
                    "source": source,
                    "expires": _time.time() + CONFIRM_TTL_SEC,
                    "result": None,
                }
            resp["confirm_token"] = token
        return resp

    def _flag(name: str, body: "dict[str, Any] | None" = None) -> bool:
        """Does the caller declare it can render one of the round-trips?

        `supports_edit` (the needs_edit editor) and `supports_confirm` (the
        confirm-create prompt) are both read this way. `/voice/text` sends them
        as JSON bools; the audio routes carry them as multipart form fields
        ("true"), so accept either. Absent (an older client) → False, and it
        never sees that response shape — the reason the flags exist.
        `supports_edit` was once read only on `/voice/text`, so the edit
        round-trip could never fire on a real voice command, which arrives as
        audio on `/voice/stream`; both flags are read on every route now."""
        wren = (body or {}).get(name) if body is not None \
            else request.form.get(name)
        return str(wren).strip().lower() in ("1", "true", "yes", "on")

    def _supports_edit(body: "dict[str, Any] | None" = None) -> bool:
        return _flag("supports_edit", body)

    def _supports_confirm(body: "dict[str, Any] | None" = None) -> bool:
        return _flag("supports_confirm", body)

    if not _no_bg:
        start_pending_retry_loop(_run_transcript)
        # Pre-event notifications: best-effort Mac banners while the calendar
        # stack is up (the phone is the reliable ringer). NO_WARMUP-gated so
        # tests building the app never start the thread.
        from assistant.notifier import start_notifier_loop
        start_notifier_loop()

    @app.post("/voice")
    def voice_audio():
        """Accept a multipart audio file, transcribe via Whisper, then execute."""
        if "audio" not in request.files:
            return jsonify({"error": "Missing 'audio' file field", "code": 400}), 400

        audio_bytes = request.files["audio"].read()
        logger.info("📱 Audio received: %.1f KB", len(audio_bytes) / 1024)
        try:
            from assistant.api.audio_utils import audio_bytes_to_numpy
            audio_np = audio_bytes_to_numpy(audio_bytes)
        except Exception as e:
            logger.error("📱 Audio decode failed: %s", e)
            return jsonify({"error": f"Audio decode failed: {e}", "code": 422}), 422

        from assistant.trace import Trace, STT
        trace = Trace(source="ios")
        try:
            stt = _get_stt()
            transcript = stt.transcribe(audio_np)
        except Exception as e:
            return jsonify({"error": f"Transcription failed: {e}", "code": 500}), 500

        if not transcript.strip():
            return jsonify({"message": "I didn't catch that.", "actions": [], "refresh": "",
                            "parse": "error", "trace": trace.to_list()})

        logger.info("📱 Transcript: %s", transcript)
        trace.step(STT, "Heard", transcript, transcript=transcript)
        return jsonify(_run_transcript(transcript, trace, source="ios",
                                       supports_edit=_supports_edit(),
                                       supports_confirm=_supports_confirm()))

    @app.post("/voice/transcribe")
    def voice_transcribe():
        """Audio in, words out. No parsing, no execution, nothing created.

        `POST /voice` transcribes AND runs the engine, which is right when the
        words are a command. Jude's are a question — they are going to a
        different brain — so it needs the Whisper half on its own.

        The personal vocabulary is applied (`learn=False`), because that is
        precisely where it earns its keep here: Whisper is trained on English
        and mangles exactly the words a Judaic question is made of. It is not
        asked to LEARN from this, since nobody is confirming the result.
        """
        if "audio" not in request.files:
            return jsonify({"error": "Missing 'audio' file field", "code": 400}), 400
        audio_bytes = request.files["audio"].read()
        try:
            from assistant.api.audio_utils import audio_bytes_to_numpy
            audio_np = audio_bytes_to_numpy(audio_bytes)
        except Exception as e:                      # noqa: BLE001
            return jsonify({"error": f"Audio decode failed: {e}", "code": 422}), 422
        try:
            transcript = _get_stt().transcribe(audio_np)
        except Exception as e:                      # noqa: BLE001
            return jsonify({"error": f"Transcription failed: {e}", "code": 500}), 500
        raw = (transcript or "").strip()
        if not raw:
            return jsonify({"text": "", "raw": "", "corrections": []})
        fixed, fixes = get_vocab().correct(raw, learn=False)
        return jsonify({
            "text": fixed,
            "raw": raw,
            # `Correction.to_dict()` rather than a hand-rolled shape: it is what
            # every other vocabulary surface returns, down to `reason` and
            # `score`, and a second spelling of the same record is how the two
            # drift.
            "corrections": [c.to_dict() for c in fixes],
        })

    @app.post("/voice/stream")
    def voice_audio_stream():
        """Same as POST /voice but streams the thinking trace live as NDJSON.

        Each line is a JSON object: {"type": "step", ...TraceStep} while the
        request is processed, then a final {"type": "result", ...response}.
        The iOS app renders the steps as a timeline as they arrive.
        """
        from flask import Response, stream_with_context
        import json as _json
        import queue as _queue
        from assistant.trace import Trace, STT, ERROR

        # Read anything off the request here, in the request context — the
        # worker below runs on a bare thread where `request` is gone.
        if "audio" in request.files:
            audio_bytes = request.files["audio"].read()
            text_cmd = None
            edit_ok = _supports_edit()
            confirm_ok = _supports_confirm()
        else:
            body = request.get_json(silent=True) or {}
            text_cmd = (body.get("transcript") or "").strip()
            audio_bytes = b""
            edit_ok = _supports_edit(body)
            confirm_ok = _supports_confirm(body)
            if not text_cmd:
                return jsonify({"error": "Missing 'audio' file or 'transcript'", "code": 400}), 400

        q: "_queue.Queue[dict | None]" = _queue.Queue()
        trace = Trace(source="ios")
        trace.on_step(lambda st: q.put({"type": "step", **st.to_dict()}))

        def work() -> None:
            try:
                if text_cmd is not None:
                    transcript = text_cmd
                    trace.step(STT, "Typed", transcript, transcript=transcript)
                else:
                    logger.info("📱 Audio received (stream): %.1f KB", len(audio_bytes) / 1024)
                    from assistant.api.audio_utils import audio_bytes_to_numpy
                    audio_np = audio_bytes_to_numpy(audio_bytes)
                    q.put({"type": "step", "stage": STT, "title": "Listening",
                           "detail": "Transcribing with Whisper…", "ms": 0, "at_ms": 0, "ok": True})
                    transcript = _get_stt().transcribe(audio_np)
                    if not transcript.strip():
                        trace.step(ERROR, "Nothing heard", "The recording was silent", ok=False)
                        q.put({"type": "result", "message": "I didn't catch that.", "actions": [],
                               "refresh": "", "parse": "error", "trace": trace.to_list()})
                        return
                    logger.info("📱 Transcript: %s", transcript)
                    trace.step(STT, "Heard", transcript, transcript=transcript)
                result = _run_transcript(transcript, trace, source="ios",
                                         supports_edit=edit_ok,
                                         supports_confirm=confirm_ok)
                q.put({"type": "result", **result})
            except Exception as e:  # never leave the stream hanging
                logger.exception("📱 Stream pipeline failed: %s", e)
                trace.step(ERROR, "Failed", str(e), ok=False)
                q.put({"type": "result", "message": f"Error: {e}", "actions": [], "refresh": "",
                       "parse": "error", "trace": trace.to_list()})
            finally:
                q.put(None)

        _threading.Thread(target=work, daemon=True).start()

        def gen():
            while True:
                item = q.get()
                if item is None:
                    break
                yield _json.dumps(item, ensure_ascii=False) + "\n"

        return Response(stream_with_context(gen()), mimetype="application/x-ndjson",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------
    # Devices — a name the server ISSUED, not one the caller asserted
    # ------------------------------------------------------------------

    @app.post("/devices/enroll")
    def devices_enroll():
        """Issue this client a device id and a token. Called once, on first run.

        **Enrolment is as protected as the API is**: `_enforce_api_key` runs
        before every route except `/health`, so when a key is configured only a
        caller holding it can enrol. Without a key the tailnet is the boundary,
        which is the same trust model the rest of the API already has — this
        endpoint does not widen it.

        The alternative — letting clients choose their own ids — is what this
        replaces: two devices could collide by accident, and any caller could
        elect to be your phone.
        """
        body = request.get_json(silent=True) or {}
        src = (body.get("source") or "").strip().lower()
        if src not in ("ios", "mac", "test"):
            return jsonify({"error": "source must be ios|mac|test", "code": 400}), 400
        got = _mp.enroll(src, (body.get("label") or "").strip())
        if not got.get("token"):
            # No secret means no trust is possible. Say so rather than issuing a
            # token that will never verify and look like an attack later.
            return jsonify({"error": "device secret unavailable", "code": 503}), 503
        logger.info("🔑 Enrolled %s device %s (%s)", src, got["device_id"], got["label"])
        return jsonify(got)

    @app.get("/devices")
    def devices_list():
        """What has enrolled, when it last spoke, and whether it is revoked —
        so the user can SEE what is talking to their assistant."""
        return jsonify({"devices": _mp.devices()})

    @app.post("/devices/<device_id>/revoke")
    def devices_revoke(device_id: str):
        """Retire one device. It keeps working as an ISOLATED stream rather
        than being cut off — it simply can never rejoin the stream it owned.
        That is what makes a leaked token survivable instead of catastrophic,
        and it is why revocation does not need to be raced against the thief."""
        ok = _mp.revoke(device_id)
        if not ok:
            return jsonify({"error": "unknown device", "code": 404}), 404
        logger.info("🔑 Revoked device %s", device_id)
        return jsonify({"revoked": device_id})

    @app.post("/voice/text")
    def voice_text():
        """Accept a JSON transcript and execute directly (skips STT)."""
        body = request.get_json(silent=True) or {}
        transcript = body.get("transcript", "").strip()
        if not transcript:
            return jsonify({"error": "Missing 'transcript' field", "code": 400}), 400
        # `source` is the only thing that differs between the two surfaces: it
        # labels the trace, the vocabulary corrections and the command memory.
        # The Mac GUI posts here too — this route is the brain for both.
        # Unidentified means synthetic. Both real clients say who they are —
        # the GUI posts "mac", the iOS app posts "ios" — so anything that does
        # not is a curl, a script or a smoke check, and belongs in the history
        # only when you ask for it.
        #
        # This defaulted to "ios", which is how an afternoon of my own testing
        # ended up indistinguishable from commands actually given to the phone.
        # Defaulting the other way makes forgetting to label a test harmless
        # and forgetting to label a real client obvious.
        src = (body.get("source") or "test").strip().lower()
        if src not in ("ios", "mac", "test"):
            src = "test"
        # WHICH client, where `source` is only what KIND (Gil, 2026-09-10).
        # Opaque to the server and never parsed — it is a grouping key, so the
        # only thing that matters is that one device sends the same one every
        # time and two devices never send the same one. Bounded and stripped of
        # anything but id characters because it reaches a log line and a SQL
        # parameter, and an unbounded client-supplied string in a group key is
        # a cheap way to be handed a 10MB one.
        dev = re.sub(r"[^A-Za-z0-9_.:-]", "", (body.get("device_id") or ""))[:64]
        # VERIFY, then resolve the identity ONCE, here, where the token is.
        #
        # A caller can assert any `device_id` it likes, so the id alone is a
        # claim and not a fact. `X-Device-Token` is the server's own HMAC over
        # (source, device_id), issued by POST /devices/enroll. An unverified
        # claim is NOT rejected — rejecting would break every old client — it is
        # ISOLATED: `stream_key` puts it in a separate namespace, so an imposter
        # presenting your phone's exact id gets its own queue and never joins
        # your phone's. Spoofing buys nothing.
        tok = (request.headers.get("X-Device-Token") or body.get("device_token") or "")
        _trusted = _mp.verify(src, dev, tok) if dev else False
        if _trusted:
            _mp.seen(dev)
        # An anonymous caller is identified by where it came from, so two
        # unlabelled clients on different machines are still two entities.
        _anon = hashlib.sha256(
            (request.remote_addr or "?").encode()).hexdigest()[:12]
        stream = _mp.stream_key(src, dev, trusted=_trusted, anon=_anon)
        view = (body.get("current_view") or "month").strip().lower()
        logger.info("%s Text command: %s", "🖥️" if src == "mac" else "📱", transcript)
        run = (body.get("trace_run") or "").strip() or None
        # A client that can show the "edit the transcription" round-trip says
        # so; older clients never see a needs_edit response.
        edit_ok = bool(body.get("supports_edit"))
        # Likewise the confirm-create prompt: a client that can show it says so,
        # and only then does an interrogative create come back as a proposal
        # instead of deep's own verdict (DEVQA Q9).
        confirm_ok = _supports_confirm(body)
        # The round-trip's second half: `edited_from` carries the transcript
        # the gate doubted. A changed word teaches the vocabulary an alias (so
        # the same mishearing auto-corrects next time); an untouched resubmit
        # earns each doubted word a confirmation toward being whitelisted.
        # Either way the gate is bypassed for THIS resubmission — asking twice
        # about the same words would be nagging.
        edited_from = (body.get("edited_from") or "").strip()
        if edited_from:
            from assistant.engine.ingest import repair as _engine_transcript
            if edited_from.strip().lower() != transcript.lower():
                learned = _engine_transcript.learn_from_edit(edited_from, transcript, src)
                if learned:
                    logger.info("Learned from a transcript edit: %s",
                                ", ".join(f"{w}→{r}" for w, r in learned))
            else:
                promoted = _engine_transcript.confirm_unchanged(transcript)
                if promoted:
                    logger.info("Whitelisted after repeated confirmation: %s",
                                ", ".join(promoted))
            edit_ok = False
        return jsonify(_run_transcript(transcript, source=src, device=dev,
                                       stream=stream, current_view=view,
                                       trace_run=run, supports_edit=edit_ok,
                                       supports_confirm=confirm_ok))

    @app.post("/voice/confirm")
    def voice_confirm():
        """Answer a confirm_create proposal: {"confirm_token", "accept": bool}.

        An interrogative create ("should I add yoga tomorrow?") comes back from
        `/voice*` as `parse: "confirm_create"` with a `proposal` list and a
        `confirm_token`, having executed nothing. This is the answer:

          accept true  → each proposal body is created through exactly the code
                         POST /events / POST /todos runs, and the command memory
                         records an approval.
          accept false → nothing is created; the memory record is marked
                         rejected, so the proposal feeds the review flows like
                         any other bad answer.

        Answering twice is safe: the first answer's result is stored against the
        token and replayed (with "duplicate": true), so a double-tapped Add
        creates once. An unknown or expired token is a 404 that says so — the
        proposal is genuinely gone and re-asking is the honest fix.
        """
        body = request.get_json(silent=True) or {}
        token = str(body.get("confirm_token") or "").strip()
        if not token:
            return jsonify({"error": "Missing 'confirm_token'", "code": 400}), 400
        _confirm_sweep()
        with _confirm_lock:
            entry = _confirm_store.get(token)
        if entry is None:
            return jsonify({"error": "Unknown or expired confirmation — ask again",
                            "code": 404}), 404
        if entry.get("result") is not None:
            return jsonify({**entry["result"], "duplicate": True})

        accept = bool(body.get("accept"))
        created: list = []
        refresh: set = set()
        errors: list = []
        if accept:
            for spec in entry.get("proposal") or []:
                kind = spec.get("kind")
                data = dict(spec.get("body") or {})
                make = create_event_from_body if kind == "event" else create_todo_from_body
                payload, status = make(data)
                if status >= 400:
                    errors.append(payload.get("error") or "could not create it")
                    continue
                created.append({"kind": kind, "id": payload.get("id")})
                refresh.add("events" if kind == "event" else "todos")

        summaries = "; ".join(s.get("summary", "") for s in (entry.get("proposal") or []))
        if accept and created:
            message = f"Added {summaries}."
        elif accept:
            message = "I couldn't add it: " + ("; ".join(errors) or "nothing to create")
        else:
            message = "Okay — I didn't add it."

        mem_id = entry.get("memory_id")
        if mem_id is not None:
            try:
                from assistant.intent.memory import (
                    FEEDBACK_APPROVED, FEEDBACK_REJECTED, get_memory,
                )
                get_memory().set_feedback(
                    int(mem_id),
                    FEEDBACK_APPROVED if (accept and created) else FEEDBACK_REJECTED,
                    notes="confirmed at the create prompt" if accept
                          else "declined at the create prompt")
            except Exception as e:
                logger.warning("Confirm feedback not recorded: %s", e)

        result = {
            "ok": not errors,
            "accepted": accept,
            "created": created,
            "refresh": ("both" if len(refresh) > 1
                        else (refresh.pop() if refresh else "")),
            "message": message,
        }
        with _confirm_lock:
            if token in _confirm_store:
                _confirm_store[token]["result"] = result
        return jsonify(result)

    # ------------------------------------------------------------------
    # Personal vocabulary (STT auto-correct)
    # ------------------------------------------------------------------

    @app.get("/lexicon")
    def lexicon_list():
        """Every editable word list: what the code ships, and what Gil added.

        `built_in` is READ-ONLY fact sourced from the module that uses it — the
        "linked to what's in the code" half of the request. `source` names that
        module so the screen can say where a word actually takes effect.
        """
        from assistant.intent.lexicon import get_lexicon
        return jsonify({"lexicons": get_lexicon().describe()})

    @app.post("/lexicon/<name>")
    def lexicon_add(name: str):
        """Add one of your own words to a list. Additive only — a built-in can
        never be removed, so no edit can break a command that used to work."""
        from assistant.intent.lexicon import LEXICONS, get_lexicon
        if name not in LEXICONS:
            return jsonify({"error": f"no such lexicon {name!r}"}), 404
        word = (request.get_json(silent=True) or {}).get("word", "")
        if not str(word).strip():
            return jsonify({"error": "word is required"}), 400
        added = get_lexicon().add(name, str(word))
        return jsonify({"ok": True, "added": added,
                        "words": get_lexicon().added(name)})

    @app.delete("/lexicon/<name>/<path:word>")
    def lexicon_remove(name: str, word: str):
        """Remove one of YOUR words. A built-in is not removable by design."""
        from assistant.intent.lexicon import LEXICONS, get_lexicon
        if name not in LEXICONS:
            return jsonify({"error": f"no such lexicon {name!r}"}), 404
        removed = get_lexicon().remove(name, word)
        return jsonify({"ok": True, "removed": removed,
                        "words": get_lexicon().added(name)})

    @app.get("/vocab")
    def vocab_get():
        from assistant.stt.vocab import get_vocab
        return jsonify(get_vocab().to_dict())

    @app.post("/vocab")
    def vocab_add():
        from assistant.stt.vocab import get_vocab
        body = request.get_json(silent=True) or {}
        word = str(body.get("word", "")).strip()
        if not word:
            return jsonify({"error": "Missing 'word'", "code": 400}), 400
        aliases = [str(a) for a in body.get("aliases", []) if str(a).strip()]
        entry = get_vocab().add_word(
            word, aliases,
            label=str(body.get("label", "") or ""),
            expands_to=str(body.get("expands_to", "") or ""),
        )
        return jsonify(entry.to_dict()), 201

    @app.patch("/vocab/<path:word>")
    def vocab_update(word: str):
        """Edit a word the settings screens are showing.

        Only the fields present in the body are changed; an empty string
        clears one. That distinction is what lets a screen offer "remove this
        label" without a second endpoint, and stops a client that predates a
        field from wiping it by omission.
        """
        from assistant.stt.vocab import get_vocab
        body = request.get_json(silent=True) or {}
        fields = {}
        for key in ("label", "expands_to"):
            if key in body:
                fields[key] = str(body.get(key) or "")
        if "aliases" in body:
            fields["aliases"] = [str(a).strip() for a in body.get("aliases") or []
                                 if str(a).strip()]
        if not fields:
            return jsonify({"error": "Nothing to change", "code": 400}), 400
        entry = get_vocab().update_word(word, **fields)
        if entry is None:
            return jsonify({"error": f"No such word: {word}", "code": 404}), 404
        return jsonify(entry.to_dict())

    @app.post("/vocab/alias")
    def vocab_alias():
        """Teach a correction: {"wrong": "Kyira", "right": "Kyra"}."""
        from assistant.stt.vocab import get_vocab
        body = request.get_json(silent=True) or {}
        wrong = str(body.get("wrong", "")).strip()
        right = str(body.get("right", "")).strip()
        if not wrong or not right:
            return jsonify({"error": "Need 'wrong' and 'right'", "code": 400}), 400
        entry = get_vocab().add_alias(wrong, right)
        return jsonify(entry.to_dict())

    @app.delete("/vocab/<path:word>")
    def vocab_delete(word: str):
        from assistant.stt.vocab import get_vocab
        alias = request.args.get("alias")
        store = get_vocab()
        ok = store.remove_alias(word, alias) if alias else store.remove_word(word)
        if not ok:
            return jsonify({"error": "Not found", "code": 404}), 404
        return jsonify({"ok": True})

    @app.patch("/vocab/settings")
    def vocab_settings():
        from assistant.stt.vocab import get_vocab
        body = request.get_json(silent=True) or {}
        store = get_vocab()
        store.update_settings(
            auto_correct=body.get("auto_correct"),
            learn_aliases=body.get("learn_aliases"),
            threshold=body.get("threshold"),
        )
        return jsonify(store.to_dict())

    @app.get("/changes")
    def changes_token():
        """A cheap "has anything changed?" token for the phone to poll.

        Refetching every list on a timer is expensive, so the phone did it only
        every 30 s — meaning something added on the Mac could sit invisible on
        the phone for half a minute. This returns a few bytes derived from the
        database file, so the phone can ask every couple of seconds and only do
        real work when the answer changes. The Mac's own window has always
        watched the same mtime (CalendarWindow._auto_refresh_if_db_changed);
        this is that signal, shared.

        The database runs in rollback-journal mode, so every commit touches the
        main file — mtime and size together move on any write.
        """
        return jsonify({"token": change_token()})

    @app.get("/tips")
    def tips_get():
        """The "How to Talk to Me" tips and the reply hints — one copy for every client."""
        from assistant import tips
        return jsonify(tips.payload())

    @app.get("/vocab/onboarding")
    def vocab_onboarding_get():
        from assistant.stt.vocab import get_vocab
        from assistant.stt import vocab_onboarding
        return jsonify(vocab_onboarding.payload(get_vocab()))

    @app.post("/vocab/onboarding")
    def vocab_onboarding_post():
        """{"answers": {"people": ["Kyra"], ...}, "presets": ["tefillah"], "done": true}"""
        from assistant.stt.vocab import get_vocab
        from assistant.stt import vocab_onboarding
        body = request.get_json(silent=True) or {}
        return jsonify(vocab_onboarding.apply(
            get_vocab(), body.get("answers"), body.get("presets"), bool(body.get("done", True))))

    @app.post("/vocab/import")
    def vocab_import():
        """Mine vocabulary candidates. Body: {"text": "..."} (WhatsApp export / notes)
        or {"source": "calendar"} or {"names": ["Rocky Caplan", ...]} (phone contacts).
        Returns candidates only — nothing is added."""
        from assistant.stt.vocab import get_vocab
        from assistant.stt import vocab_import
        body = request.get_json(silent=True) or {}
        known = {e.word for e in get_vocab().entries}
        if body.get("names"):
            cands = vocab_import.from_names([str(n) for n in body["names"]], known)
        elif body.get("source") == "calendar":
            cands = vocab_import.from_calendar(known)
        else:
            text = str(body.get("text", ""))
            if len(text) > 5_000_000:
                return jsonify({"error": "Text too large", "code": 413}), 413
            cands = vocab_import.extract(text, known)
        return jsonify({"candidates": cands})

    @app.post("/vocab/bulk")
    def vocab_bulk():
        """Add many words at once: {"words": ["Kyra", ...]}"""
        from assistant.stt.vocab import get_vocab
        body = request.get_json(silent=True) or {}
        store = get_vocab()
        added = 0
        for w in body.get("words", []):
            w = str(w).strip()
            if w and store._find(w) is None:
                store.add_word(w); added += 1
        return jsonify({"added": added, "total": len(store.entries)})

    @app.post("/vocab/preview")
    def vocab_preview():
        """Dry-run: what would the corrector do to this text? (no learning)"""
        from assistant.stt.vocab import get_vocab
        body = request.get_json(silent=True) or {}
        text = str(body.get("text", ""))
        fixed, fixes = get_vocab().correct(text, learn=False)
        return jsonify({"original": text, "corrected": fixed,
                        "corrections": [c.to_dict() for c in fixes]})

    # ------------------------------------------------------------------
    # Pending commands (failed because the LLM was offline/slow)
    # ------------------------------------------------------------------

    @app.get("/pending")
    def pending_list():
        from assistant.intent.memory import get_memory
        return jsonify({"pending": get_memory().pending(include_done=request.args.get("all") == "1")})

    @app.post("/pending/<int:pending_id>/retry")
    def pending_retry(pending_id: int):
        from assistant.intent.memory import get_memory
        mem = get_memory()
        row = mem.get_pending(pending_id)
        if row is None:
            return jsonify({"error": "Not found", "code": 404}), 404
        result = _run_transcript(row["transcript"])
        if result.get("parse") == "error":
            mem.bump_pending(pending_id)
        else:
            mem.resolve_pending(pending_id, "done", result.get("message", ""))
        result["pending_id"] = pending_id
        return jsonify(result)

    @app.delete("/pending/<int:pending_id>")
    def pending_dismiss(pending_id: int):
        from assistant.intent.memory import get_memory
        get_memory().resolve_pending(pending_id, "dismissed")
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # Command memory (RAG personalisation + feedback)
    # ------------------------------------------------------------------

    @app.get("/memory")
    def memory_list():
        from assistant.intent.memory import get_memory
        limit = int(request.args.get("limit", 50))
        return jsonify({"examples": get_memory().recent(limit), "stats": get_memory().stats()})

    @app.get("/memory/unreviewed")
    def memory_unreviewed():
        """Commands with no feedback yet, each with every row it touched
        (`assistant/intent/review.py` has the shape and the why)."""
        from assistant.intent import review
        rows = review.unreviewed(int(request.args.get("limit", 30)))
        return jsonify({"examples": rows, "count": len(rows)})

    @app.post("/memory/unreviewed/skip")
    def memory_skip_unreviewed():
        """Dismiss the whole review backlog (e.g. stale seeded history)."""
        from assistant.intent.memory import get_memory
        return jsonify({"skipped": get_memory().skip_unreviewed()})

    @app.get("/memory/similar")
    def memory_similar():
        from assistant.intent.memory import get_memory
        q = request.args.get("q", "")
        return jsonify(get_memory().retrieve(q, k=int(request.args.get("k", 4))))

    @app.post("/memory/<int:example_id>/feedback")
    def memory_feedback(example_id: int):
        """{"feedback": "approved"|"corrected"|"rejected", "correction": [...]?, "notes": "..."}"""
        from assistant.intent.memory import get_memory
        body = request.get_json(silent=True) or {}
        try:
            ok = get_memory().set_feedback(example_id, body.get("feedback", "approved"),
                                          body.get("correction"), body.get("notes", ""))
        except ValueError as e:
            return jsonify({"error": str(e), "code": 400}), 400
        if not ok:
            return jsonify({"error": "Not found", "code": 404}), 404
        return jsonify(get_memory().get(example_id))

    @app.delete("/memory/<int:example_id>")
    def memory_delete(example_id: int):
        from assistant.intent.memory import get_memory
        if not get_memory().delete(example_id):
            return jsonify({"error": "Not found", "code": 404}), 404
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # The feature surfaces used to live here — they now own their routes
    # ------------------------------------------------------------------
    #
    # Each tab ships its own Flask blueprint from its own folder, per
    # assistant/features/CONVENTION.md, and this file went back to being HTTP
    # plumbing. What was here, and where it went:
    #
    #   timers & counters .......... assistant/features/timer/routes.py
    #   event categories, events,
    #     /search, /sync/bootstrap,
    #     /holidays ................ assistant/features/calendar/routes.py
    #   todos, tags, tag
    #     suggestions .............. assistant/features/tasks/routes.py
    #   the labelling game ......... assistant/features/teach/routes.py
    #   courses + assignments ...... assistant/features/coursework/routes.py
    #   workout .................... assistant/features/workout/routes.py
    #
    # They are mounted at the bottom of this function, beside the integrations.
    # ------------------------------------------------------------------

    @app.get("/observance/location")
    def observance_location_get():
        """Where sundown is currently computed for, and where that came from."""
        from assistant import observance as ob
        here = ob.get_location()
        settings = ob.current_settings()
        return jsonify({
            "in_use": {"latitude": settings.latitude, "longitude": settings.longitude,
                       "timezone": settings.timezone, "city": settings.city},
            "source": "device" if here else "config",
            "reported": here,
        })

    @app.post("/observance/location")
    def observance_location_set():
        """A device reporting where it is.

        Sundown moves by hours between places, so a repeating event that skips
        Shabbat is wrong the moment you travel — the boundary it is avoiding is
        computed for somewhere you are not. The device that knows its position
        says so, and everything downstream follows without being told.
        """
        from assistant import observance as ob
        body = request.get_json(silent=True) or {}
        try:
            settings = ob.set_location(
                latitude=body["latitude"], longitude=body["longitude"],
                timezone=body.get("timezone") or "",
                city=body.get("city", ""),
                source=(body.get("source") or "device"),
            )
        except (KeyError, TypeError):
            return jsonify({"error": "latitude, longitude and timezone are required",
                            "code": 400}), 400
        except ValueError as exc:
            return jsonify({"error": str(exc), "code": 400}), 400
        logger.info("📍 Location set to %s (%.4f, %.4f)",
                    settings.city or "an unnamed place", settings.latitude, settings.longitude)
        return jsonify({"latitude": settings.latitude, "longitude": settings.longitude,
                        "timezone": settings.timezone, "city": settings.city})

    @app.delete("/observance/location")
    def observance_location_clear():
        """Forget the reported position and go back to the configured place."""
        from assistant import observance as ob
        settings = ob.clear_location()
        return jsonify({"latitude": settings.latitude, "longitude": settings.longitude,
                        "timezone": settings.timezone, "city": settings.city,
                        "source": "config"})

    @app.get("/observance/windows")
    def observance_windows():
        """When Shabbat and yom tov begin and end, to the second, over a range.

        What the calendars draw their yellow lines from. Computed here, once,
        with the settings the recurring-series skip uses — `current_settings()`,
        which follows a device's reported position — so the line on the phone,
        the line on the Mac and the minute the calendar starts refusing to book
        are the same instant. `?start=&end=` are ISO days (at most 400 apart);
        `?israel=0` for the Diaspora yom tov schedule. A window whose boundary
        cannot be computed is left out, never guessed.
        """
        from assistant import observance as ob
        try:
            start = datetime.date.fromisoformat(request.args["start"])
            end = datetime.date.fromisoformat(request.args["end"])
        except (KeyError, ValueError):
            return jsonify({"error": "start and end are required (YYYY-MM-DD)",
                            "code": 400}), 400
        if end < start:
            return jsonify({"error": "end precedes start", "code": 400}), 400
        if (end - start).days > 400:
            return jsonify({"error": "range must be 400 days or fewer", "code": 400}), 400
        israel = request.args.get("israel", "1") not in ("0", "false", "False")
        return jsonify(ob.holy_windows_payload(start, end, israel=israel))

    @app.get("/observance")
    def observance_range():
        """Training availability per day: what is blocked, and which windows remain.

        Lets a client show *why* a day is unavailable without reimplementing
        the Hebrew calendar — the phone renders what the Mac decided.
        """
        from assistant import observance as ob
        from assistant.actions.schedule_workout.action import observance_settings

        try:
            start = datetime.date.fromisoformat(request.args["start_date"])
            end = datetime.date.fromisoformat(request.args["end_date"])
        except (KeyError, ValueError):
            return jsonify({
                "error": "start_date and end_date are required (YYYY-MM-DD)",
                "code": 400,
            }), 400
        if end < start:
            return jsonify({"error": "end_date precedes start_date", "code": 400}), 400
        if (end - start).days > 400:
            return jsonify({"error": "range must be 400 days or fewer", "code": 400}), 400

        settings = observance_settings(load_config())
        out = []
        cur = start
        while cur <= end:
            av = ob.availability(cur, settings)
            out.append({
                "date": cur.isoformat(),
                "status": av.status,
                "reason": av.reason,
                "holiday": av.holiday_name,
                "is_chol_hamoed": ob.is_chol_hamoed(cur),
                "is_fast_day": ob.is_fast_day(cur),
                "windows": [
                    {
                        "start": w.start.strftime("%H:%M"),
                        "end": w.end.strftime("%H:%M"),
                        "label": w.label,
                        "fallback": w.fallback,
                    }
                    for w in av.windows
                ],
            })
            cur += datetime.timedelta(days=1)
        return jsonify(out)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    # `MACALENDAR_CONFIG` FIRST, like `config.py:428` and
    # `features/settings.py:53`. This one endpoint did not honour it, so
    # `PATCH /config` wrote the repo's real config.yaml whatever the environment
    # said — which is the one file the suite's isolation exists to protect and
    # the one file that is gitignored, so there is nothing to restore from.
    # Found 2026-09-18 by writing `theme: light` into Gil's live config from a
    # scratch-sandboxed script that had set the override correctly.
    _CONFIG_PATH = (os.environ.get("MACALENDAR_CONFIG")
                    or os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"))
    #: Widened 2026-09-18 (Gil: "mac and ios should have same settings,
    #: everything should be synchronized"). The Mac already STORED theme, the
    #: accent colour, the Hebrew conventions and show-completed; the phone just
    #: kept private copies of all four and neither knew about the other.
    #:
    #: NOT here, and each for a reason rather than an omission: the server
    #: address and API key describe the phone's route to this Mac and mean
    #: nothing on it; `followMyLocation` is about THIS device's position; the
    #: font sizes are deliberately per-device (a phone and a 27-inch screen want
    #: different numbers, and `AppSettings` has said so since they were added);
    #: and the tab filters, list scope and fold state are UI chrome, not
    #: preferences about the calendar.
    #:
    #: `events` joined 2026-09-25 (DEVQA Q51): the default event length and the
    #: gap between chained events, which the engine reads through
    #: `assistant/event_defaults.py` and both apps edit.
    _ALLOWED_PATCH_KEYS = {"llm_engine", "tts", "confirmation_level",
                           "notifications", "theme", "ui", "todo",
                           "hebrew_calendar", "events"}

    @app.get("/digest")
    def digest():
        """Today's day panel: when it fires, what it says, and the rows behind it.

        One surface rather than "events plus todos plus work it out", because
        the wording is policy too — the phone's notification and the Mac's
        banner must say the same thing, and two clients formatting their own
        drift the moment one learns about all-day events and the other does
        not. `?date=` for any other day; defaults to today.
        """
        from assistant import notify as _notify

        raw = request.args.get("date")
        try:
            day = datetime.date.fromisoformat(raw) if raw else datetime.date.today()
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        cfg = load_config().notifications
        return jsonify(_notify.build_digest(day, cfg, get_db()))

    #: How many days ahead /digest/upcoming will build. A week covers a phone
    #: left off the tailnet over a trip; past that the content is stale enough
    #: that not firing is the more honest answer.
    _DIGEST_HORIZON = 7

    @app.get("/digest/upcoming")
    def digest_upcoming():
        """The next few days' panels in one answer, for the phone to SCHEDULE.

        iOS local notifications are scheduled ahead of time, not pushed: the
        phone must already hold tomorrow's panel before tomorrow's 07:00, and
        it cannot ask for it at 06:59 because it may be asleep, in a pocket,
        or off the tailnet. One round trip per sync rather than seven, because
        this is called on every foreground.

        Days whose panel is suppressed (Shabbat, yom tov) are INCLUDED with
        `fires_at: null` and the reason, rather than omitted — the client
        schedules nothing for them either way, and a caller reading the answer
        can tell "held" apart from "not asked about".
        """
        from assistant import notify as _notify

        try:
            days = int(request.args.get("days", _DIGEST_HORIZON))
        except (TypeError, ValueError):
            return jsonify({"error": "days must be a whole number"}), 400
        days = max(1, min(days, _DIGEST_HORIZON))

        cfg = load_config().notifications
        db = get_db()
        today = datetime.date.today()
        return jsonify({"days": [
            _notify.build_digest(today + datetime.timedelta(days=i), cfg, db)
            for i in range(days)
        ]})

    @app.get("/config")
    def config_get():
        cfg = load_config()
        return jsonify({
            "llm_engine": cfg.llm_engine,
            "tts": cfg.tts.model_dump(),
            "confirmation_level": cfg.confirmation_level,
            "todo": cfg.todo.model_dump(),
            "notifications": cfg.notifications.model_dump(),
            # Shared with the phone so both screens show one value rather than
            # two copies that drift (see `_ALLOWED_PATCH_KEYS`).
            "theme": cfg.theme,
            "ui": cfg.ui.model_dump(),
            "hebrew_calendar": cfg.hebrew_calendar.model_dump(),
            "events": cfg.events.model_dump(),
        })

    @app.patch("/config")
    def config_patch():
        data = request.get_json(silent=True) or {}
        path = os.path.normpath(_CONFIG_PATH)
        with open(path) as f:
            current = yaml.safe_load(f) or {}

        # Edited as TEXT, one line at a time. `yaml.dump` here rewrote the
        # whole document and destroyed every comment in it — the notes saying
        # what each block is for and which values are safe to change. Every
        # VALUE survived, which is why it went unnoticed; config.yaml is
        # gitignored, so there was nothing to restore from. It also reordered
        # the file, because that dump had no `sort_keys=False`.
        from assistant.features import yaml_text
        with open(path) as f:
            text = f.read()

        # The two event defaults are NUMBERS the engine computes with, so this
        # request shape is checked before a byte is written: "90" or 0 stored
        # here would be clamped on read and the setting would silently not be
        # what the client showed.
        events = data.get("events")
        if events is not None:
            from assistant.config import MAX_EVENT_MINUTES, MIN_EVENT_LENGTH
            if not isinstance(events, dict):
                return jsonify({"error": "events must be an object", "code": 400}), 400
            lows = {"event_length_minutes": MIN_EVENT_LENGTH, "chain_gap_minutes": 0}
            for sub, value in events.items():
                if sub not in lows:
                    return jsonify({"error": f"events.{sub} is not a setting",
                                    "code": 400}), 400
                if (isinstance(value, bool) or not isinstance(value, int)
                        or not lows[sub] <= value <= MAX_EVENT_MINUTES):
                    return jsonify({"error": f"events.{sub} must be a whole number of "
                                    f"minutes from {lows[sub]} to {MAX_EVENT_MINUTES}",
                                    "code": 400}), 400

        for key, wren in data.items():
            if key not in _ALLOWED_PATCH_KEYS:
                continue
            if isinstance(wren, dict):
                for sub, value in wren.items():
                    if isinstance(value, (dict, list)):
                        return jsonify({"error": f"{key}.{sub} is not a scalar; "
                                        "edit config.yaml by hand", "code": 400}), 400
                    text = yaml_text.set_nested(text, key, sub, value)
            elif isinstance(wren, list):
                return jsonify({"error": f"{key} is a list; edit config.yaml "
                                "by hand", "code": 400}), 400
            else:
                text = yaml_text.set_top(text, key, wren)

        # It must still parse, or the assistant cannot boot next time.
        try:
            yaml.safe_load(text)
        except yaml.YAMLError:
            return jsonify({"error": "refusing to write config.yaml: the edit "
                            "did not read back as valid YAML", "code": 500}), 500
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, path)

        return jsonify({"status": "ok"})

    # ------------------------------------------------------------------
    # Integrations (Jude, and whatever comes next)
    # ------------------------------------------------------------------
    #
    # External apps — their own repositories, their own servers — that this
    # assistant hosts, gates and proxies. Each one owns a folder and brings its
    # own blueprint, so this file stays HTTP and never accumulates a second
    # app's parsing the way it once accumulated Jude's ~120 lines of proxying.
    #
    # `GET /integrations` lists them all in one shape; `/jude/*` is Jude's own.
    # See assistant/integrations/CONVENTION.md.
    from assistant.integrations import registry as _integrations
    _integrations.register(app)

    # ------------------------------------------------------------------
    # Features (this assistant's own surfaces — the tabs and panels)
    # ------------------------------------------------------------------
    #
    # Not the same thing as an integration, and deliberately a separate
    # registry: a Feature is a tab of ours, an Integration is somebody else's
    # program. `GET /features` is the visibility map both clients read; each
    # feature's own routes ride in on its blueprint.
    # See assistant/features/CONVENTION.md.
    from assistant.features import registry as _features
    _features.register(app)

    # ------------------------------------------------------------------
    # Connected calendars (ICS subscriptions, Outlook and Google two-way)
    # ------------------------------------------------------------------
    # The CRUD for source rows is below. Signing in, status, disconnect and
    # "sync now" are `/calendar_sync/*`, and the periodic sync is a thread the
    # brain owns (so it runs with the calendar window closed) — both live in
    # assistant/calendar_sync/, mounted by this one line.
    from assistant.calendar_sync import routes as _calendar_sync
    _calendar_sync.register(app, background=not _no_bg and not _is_reload_watcher)

    @app.get("/calendar_sources")
    def calendar_sources_list():
        return jsonify(get_db().get_calendar_sources())

    @app.post("/calendar_sources")
    def calendar_source_create():
        data = request.get_json(silent=True) or {}
        kind = data.get("kind", "")
        if kind not in ("ics_url", "outlook"):
            return jsonify({"error": "kind must be 'ics_url' or 'outlook'", "code": 400}), 400
        if kind == "ics_url" and not data.get("url", "").strip():
            return jsonify({"error": "Missing 'url'", "code": 400}), 400
        source_id = get_db().create_calendar_source(
            kind=kind,
            label=data.get("label", ""),
            url=data.get("url", ""),
            color=data.get("color", "#0078d4"),
            two_way=bool(data.get("two_way", False)),
        )
        return jsonify({"id": source_id}), 201

    @app.patch("/calendar_sources/<int:source_id>")
    def calendar_source_update(source_id: int):
        data = request.get_json(silent=True) or {}
        get_db().update_calendar_source(source_id, **data)
        return jsonify({"id": source_id})

    @app.delete("/calendar_sources/<int:source_id>")
    def calendar_source_delete(source_id: int):
        get_db().delete_calendar_source(source_id)
        return jsonify({"deleted": source_id})

    return app

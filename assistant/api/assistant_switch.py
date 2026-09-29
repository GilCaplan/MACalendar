"""The assistant's on/off switch — HTTP only (Gil, 2026-09-29: *"an option to
turn assistant i.e engine off so it can't be used"*).

    GET /assistant           {enabled}
    PUT /assistant           {enabled} — from this Mac, or a signed-in admin

Off, every route that hands a command to the engine answers 503 with
``assistant_off: true`` and a sentence saying where to turn it back on; the
calendar, to-dos and every other route work as before. The setting is
``engine.enabled`` in config.yaml, read per request, so the Mac's Settings,
the phone's Settings and a hand edit all take effect at once.
"""

from __future__ import annotations

from flask import jsonify, request

#: The routes that run the engine on a command. Transcribing alone
#: (/voice/transcribe) is left open: it books nothing.
ENGINE_ROUTES = frozenset({"/voice", "/voice/stream", "/voice/text", "/voice/confirm"})
OFF_MESSAGE = "The assistant is switched off — turn it on in Settings ▸ Assistant."


def enabled() -> bool:
    from assistant.config import load_config
    try:
        return bool(getattr(load_config().engine, "enabled", True))
    except Exception:
        return True                       # a config that cannot load must not lock the user out


def register(app) -> None:
    @app.before_request
    def _assistant_switch():
        if request.path in ENGINE_ROUTES and not enabled():
            return jsonify({"error": OFF_MESSAGE, "code": 503, "assistant_off": True}), 503
        return None

    @app.get("/assistant")
    def assistant_get():
        return jsonify({"enabled": enabled()})

    @app.put("/assistant")
    def assistant_put():
        from assistant.pairing.routes import is_local
        from assistant.users import registry
        if not is_local() and registry.exists():
            from assistant.users.routes import _need_admin
            _uid, err = _need_admin()
            if err:
                return err
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("enabled"), bool):
            return jsonify({"error": "enabled must be true or false", "code": 400}), 400
        from assistant.config_store import set_values
        if not set_values({"engine": {"enabled": body["enabled"]}}):
            return jsonify({"error": "config.yaml is missing", "code": 500}), 500
        return jsonify({"enabled": enabled()})

"""The list of integrations, and the one line `server.py` calls.

This is the ONLY module in the generic layer that knows which integrations
exist. `base` and `process` stay ignorant of them on purpose — they take an
integration object and call methods on it — so adding a second one touches
this file and nothing else underneath it.

`server.py` gets one line (`registry.register(app)`) and keeps its rule from
CLAUDE.md: it is HTTP — routes, request shapes, CRUD — and an integration's
routes live in the integration's own folder, not interleaved into it. The
~120 lines of Jude proxying that used to sit in the middle of `server.py` are
now `assistant/jude/routes.py`.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_cache: "dict[str, object]" = {}


def all_integrations() -> "list":
    """Every integration this assistant can host.

    Imported lazily and defensively: an integration whose module fails to
    import must not take the API server down with it — it is optional by
    definition, and the right failure is that it is missing from the list.
    """
    if not _cache:
        from assistant.jude.integration import JudeIntegration
        for factory in (JudeIntegration,):
            try:
                inst = factory()
                _cache[inst.name] = inst
            except Exception as exc:      # noqa: BLE001
                logger.warning("integration %s failed to load: %s", factory, exc)
    return list(_cache.values())


def get(name: str):
    """One integration by name, or None."""
    all_integrations()
    return _cache.get((name or "").strip().lower())


def register(app) -> None:
    """Mount every integration's blueprint, plus the generic status route."""
    from flask import jsonify

    for integration in all_integrations():
        try:
            blueprint = integration.blueprint()
        except Exception as exc:          # noqa: BLE001
            logger.warning("integration %s has no usable routes: %s",
                           integration.name, exc)
            continue
        if blueprint is not None:
            app.register_blueprint(blueprint)

    @app.get("/integrations")
    def list_integrations():
        """What is plugged in, and whether each one can answer right now.

        One shape for every integration (see `base.Integration.status`), so a
        client that can draw one can draw the next without a new code path.
        """
        return jsonify([i.status() for i in all_integrations()])


def shutdown() -> None:
    """Stop every child we started. Called when the API server goes down."""
    from assistant.integrations import process
    process.stop_all()

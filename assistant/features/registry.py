"""The list of features, and the one line `server.py` calls.

The ONLY module that knows which features exist. `base` stays ignorant of them
— it takes a feature object and calls methods on it — which is what makes
adding the next one a folder plus one line here, rather than an edit in three
iOS lists, five Mac wiring sites and the middle of `server.py`.

That count is not hypothetical: registration having been three hand-synced
lists on the phone is exactly why Timer had no bounce-off handler and hiding it
left a blank screen.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_cache: "dict[str, object]" = {}


def all_features() -> "list":
    """Every feature, in display order.

    Imported lazily and defensively: one feature whose module fails to import
    must not take the API server down with it — the right failure is that it is
    missing from the list, not that the calendar will not start.
    """
    if not _cache:
        from assistant.features.calendar import CalendarFeature
        from assistant.features.coursework import CourseworkFeature
        from assistant.features.jude import JudeFeature
        from assistant.features.tasks import TasksFeature
        from assistant.features.teach import TeachFeature
        from assistant.features.timer import TimerFeature
        from assistant.features.workout import WorkoutFeature

        for factory in (CalendarFeature, TasksFeature, CourseworkFeature,
                        WorkoutFeature, TimerFeature, TeachFeature, JudeFeature):
            try:
                inst = factory()
                _cache[inst.name] = inst
            except Exception as exc:          # noqa: BLE001
                logger.warning("feature %s failed to load: %s", factory, exc)
    return sorted(_cache.values(), key=lambda f: f.order)


def get(name: str):
    all_features()
    return _cache.get((name or "").strip().lower())


def visible() -> "list":
    return [f for f in all_features() if f.visible()]


def register(app) -> None:
    """Mount every feature's blueprint, plus the two visibility routes."""
    from flask import jsonify, request

    for feature in all_features():
        try:
            blueprint = feature.blueprint()
        except Exception as exc:              # noqa: BLE001
            logger.warning("feature %s has no usable routes: %s", feature.name, exc)
            continue
        if blueprint is not None:
            app.register_blueprint(blueprint)

    @app.get("/features")
    def list_features():
        """Every surface this assistant has, and whether it is switched on.

        Clients declare their own features in code and read only VISIBILITY
        from here — see `features/base.py`. That is what lets the phone draw
        its tab bar before the Mac has answered, or when it never will.
        """
        return jsonify([f.manifest() for f in all_features()])

    @app.patch("/features/<name>")
    def patch_feature(name: str):
        feature = get(name)
        if feature is None:
            return jsonify({"error": f"No feature called {name!r}.", "code": 404}), 404
        data = request.get_json(silent=True) or {}
        if "visible" not in data:
            return jsonify({"error": "Missing 'visible'", "code": 400}), 400
        try:
            feature.set_visible(bool(data["visible"]))
        except ValueError as e:
            # A pinned feature. 409 rather than 403: the request is understood
            # and well-formed, it just conflicts with what this feature is.
            return jsonify({"error": str(e), "code": 409}), 409
        return jsonify(feature.manifest())

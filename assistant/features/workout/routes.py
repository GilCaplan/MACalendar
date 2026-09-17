"""Workout's HTTP surface: `/workout/*` — exercises, templates, sessions, plans.

A Flask blueprint rather than lines in `server.py`, per
`assistant/features/CONVENTION.md`: a surface owns a folder, declares itself
once to a registry, ships its own routes, and the generic layer never learns
its name. CLAUDE.md's rule for `server.py` is that it stays HTTP plumbing — the
feature CRUD belongs with the feature.

| route | what |
|---|---|
| `GET/POST /workout/exercises` | the exercise catalogue |
| `GET/POST /workout/templates` | routines; `PATCH/DELETE /workout/templates/<id>` and `/approve` |
| `GET/POST /workout/sessions` | logged workouts; `PATCH/DELETE /workout/sessions/<id>` |
| `GET /workout/plans` | generated plans; `GET/DELETE /workout/plans/<id>` |
| `GET /workout/plan-items` | scheduled sessions in a date range; `PATCH /workout/plan-items/<id>` |

No `url_prefix`: the paths above are already absolute and carry their own
`/workout`, and prefixing them again would move every one of them.
"""

from __future__ import annotations

import sqlite3

from flask import Blueprint, jsonify, request

from assistant.db import get_db

blueprint = Blueprint("workout", __name__)

# ------------------------------------------------------------------
# Workout
#
# Client-generated UUID primary keys end-to-end (unlike events/todos'
# autoincrement-Int + temp-id-remap scheme) — the client always sends
# its own `id`, the server just stores it. JSON keys are snake_case,
# matching the SQL columns 1:1 (same convention as /events and /todos;
# the iOS API layer translates snake_case -> camelCase via CodingKeys,
# see API/Models.swift).
# ------------------------------------------------------------------

@blueprint.get("/workout/exercises")
def workout_exercises_list():
    return jsonify(get_db().get_workout_exercises())


@blueprint.post("/workout/exercises")
def workout_exercise_create():
    data = request.get_json(silent=True) or {}
    exercise_id = data.get("id")
    name = (data.get("name") or "").strip()
    if not exercise_id or not name:
        return jsonify({"error": "Missing 'id' or 'name'", "code": 400}), 400
    get_db().create_workout_exercise(id=exercise_id, name=name, created_at=data.get("created_at"))
    return jsonify({"id": exercise_id}), 201


@blueprint.get("/workout/templates")
def workout_templates_list():
    include_drafts = request.args.get("include_drafts", "false").lower() == "true"
    return jsonify(get_db().get_workout_templates(include_drafts=include_drafts))


@blueprint.post("/workout/templates")
def workout_template_create():
    data = request.get_json(silent=True) or {}
    template_id = data.get("id")
    name = (data.get("name") or "").strip()
    if not template_id or not name:
        return jsonify({"error": "Missing 'id' or 'name'", "code": 400}), 400
    db = get_db()
    if db.get_workout_template(template_id) is not None:
        return jsonify({"error": "Template already exists", "code": 409}), 409
    try:
        db.create_workout_template(data)
    except (sqlite3.IntegrityError, KeyError) as e:
        return jsonify({"error": f"Invalid template: {e}", "code": 400}), 400
    return jsonify({"id": template_id}), 201


@blueprint.patch("/workout/templates/<template_id>")
def workout_template_update(template_id: str):
    data = request.get_json(silent=True) or {}
    db = get_db()
    if db.get_workout_template(template_id) is None:
        return jsonify({"error": "Template not found", "code": 404}), 404
    try:
        db.replace_workout_template(template_id, data)
    except (sqlite3.IntegrityError, KeyError) as e:
        return jsonify({"error": f"Invalid template: {e}", "code": 400}), 400
    return jsonify({"id": template_id})


@blueprint.delete("/workout/templates/<template_id>")
def workout_template_delete(template_id: str):
    db = get_db()
    if db.get_workout_template(template_id) is None:
        return jsonify({"error": "Template not found", "code": 404}), 404
    db.delete_workout_template(template_id)
    return jsonify({"deleted": template_id})


@blueprint.patch("/workout/templates/<template_id>/approve")
def workout_template_approve(template_id: str):
    db = get_db()
    if db.get_workout_template(template_id) is None:
        return jsonify({"error": "Template not found", "code": 404}), 404
    db.approve_workout_template(template_id)
    return jsonify({"id": template_id, "status": "saved"})


@blueprint.get("/workout/sessions")
def workout_sessions_list():
    limit = request.args.get("limit", type=int)
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    rows = get_db().get_workout_sessions(limit=limit, start_date=start_date, end_date=end_date)
    return jsonify(rows)


@blueprint.post("/workout/sessions")
def workout_session_create():
    data = request.get_json(silent=True) or {}
    session_id = data.get("id")
    started_at = data.get("started_at")
    if not session_id or not started_at:
        return jsonify({"error": "Missing 'id' or 'started_at'", "code": 400}), 400
    db = get_db()
    if db.get_workout_session(session_id) is not None:
        return jsonify({"error": "Session already exists", "code": 409}), 409
    try:
        db.create_workout_session(data)
    except (sqlite3.IntegrityError, KeyError) as e:
        return jsonify({"error": f"Invalid session: {e}", "code": 400}), 400
    return jsonify({"id": session_id}), 201


@blueprint.patch("/workout/sessions/<session_id>")
def workout_session_update(session_id: str):
    data = request.get_json(silent=True) or {}
    db = get_db()
    if db.get_workout_session(session_id) is None:
        return jsonify({"error": "Session not found", "code": 404}), 404
    db.update_workout_session(session_id, **data)
    return jsonify({"id": session_id})


@blueprint.delete("/workout/sessions/<session_id>")
def workout_session_delete(session_id: str):
    db = get_db()
    if db.get_workout_session(session_id) is None:
        return jsonify({"error": "Session not found", "code": 404}), 404
    db.delete_workout_session(session_id)
    return jsonify({"deleted": session_id})


# ------------------------------------------------------------------
# Workout: Plans + the observance calendar behind them
# ------------------------------------------------------------------

@blueprint.get("/workout/plans")
def workout_plans_list():
    status = request.args.get("status", "")
    return jsonify(get_db().get_workout_plans(status=status or None))


@blueprint.get("/workout/plans/<plan_id>")
def workout_plan_get(plan_id: str):
    plan = get_db().get_workout_plan(plan_id)
    if plan is None:
        return jsonify({"error": "Plan not found", "code": 404}), 404
    return jsonify(plan)


@blueprint.delete("/workout/plans/<plan_id>")
def workout_plan_delete(plan_id: str):
    db = get_db()
    if db.get_workout_plan(plan_id) is None:
        return jsonify({"error": "Plan not found", "code": 404}), 404
    keep = request.args.get("keep_events", "").lower() in ("1", "true", "yes")
    removed = db.delete_workout_plan(plan_id, delete_events=not keep)
    return jsonify({"deleted": plan_id, "events_removed": removed})


@blueprint.get("/workout/plan-items")
def workout_plan_items_list():
    """Scheduled sessions in a date range — what the phone's day view asks for."""
    return jsonify(get_db().get_workout_plan_items(
        start_date=request.args.get("start_date", ""),
        end_date=request.args.get("end_date", ""),
        plan_id=request.args.get("plan_id", ""),
    ))


@blueprint.patch("/workout/plan-items/<item_id>")
def workout_plan_item_update(item_id: str):
    db = get_db()
    if db.get_workout_plan_item(item_id) is None:
        return jsonify({"error": "Plan item not found", "code": 404}), 404
    db.update_workout_plan_item(item_id, **(request.get_json(silent=True) or {}))
    return jsonify(db.get_workout_plan_item(item_id))

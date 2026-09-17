"""Coursework's HTTP surface: `/courses*` and `/assignments*`.

A Flask blueprint rather than lines in `server.py`, per
`assistant/features/CONVENTION.md`: a surface owns a folder, declares itself
once to a registry, ships its own routes, and the generic layer never learns
its name.

| route | what |
|---|---|
| `GET/POST /courses` | the course list, and create |
| `PATCH/DELETE /courses/<id>` | edit or drop one |
| `GET /assignments` | every assignment across every course |
| `GET /courses/<id>/assignments` | one course's |
| `POST /assignments` `PATCH/DELETE /assignments/<id>` | create, edit, drop |
| `PATCH /assignments/<id>/toggle` `DELETE /assignments/completed` | tick off; clear |

No `url_prefix`: every path above is already absolute, and a prefix would move
all of them.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from assistant.features.idempotency import idempotent_create

blueprint = Blueprint("coursework", __name__)


def get_db():
    """Resolved through `assistant.api.server` at CALL time, never bound at
    import. server.py re-exports `assistant.db.get_db`, and a test that swaps
    it there — `tests/integration/test_api_server.py`'s `app_client` fixture —
    has to reach the feature blueprints too. A blueprint holding its own early
    binding would quietly read the REAL ~/.assistant_tools/calendar.db while
    the test watched a temp one."""
    from assistant.api import server
    return server.get_db()


# ------------------------------------------------------------------
# Courses
# ------------------------------------------------------------------

@blueprint.get("/courses")
def courses_list():
    return jsonify(get_db().get_courses())


@blueprint.post("/courses")
def course_create():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing 'name'"}), 400
    # Idempotent on `client_token`: the phone queues this create while the Mac
    # is away and replays it on reconnect, so a reply lost after the row was
    # written would otherwise land a second course.
    body, status = idempotent_create("courses", data, lambda: get_db().create_course(
        number=data.get("number", ""),
        name=name,
        color=data.get("color", "#1a6fc4"),
        partners=data.get("partners", []),
    ))
    return jsonify(body), status


@blueprint.patch("/courses/<int:course_id>")
def course_update(course_id: int):
    data = request.get_json(silent=True) or {}
    get_db().update_course(course_id, **data)
    return jsonify({"id": course_id})


@blueprint.delete("/courses/<int:course_id>")
def course_delete(course_id: int):
    get_db().delete_course(course_id)
    return jsonify({"deleted": course_id})


# ------------------------------------------------------------------
# Assignments
# ------------------------------------------------------------------

@blueprint.get("/assignments")
def assignments_list_all():
    """Return all assignments across every course."""
    db = get_db()
    courses = db.get_courses()
    result = []
    for c in courses:
        result.extend(db.get_assignments(c["id"]))
    return jsonify(result)


@blueprint.get("/courses/<int:course_id>/assignments")
def assignments_list(course_id: int):
    return jsonify(get_db().get_assignments(course_id))


@blueprint.post("/assignments")
def assignment_create():
    data = request.get_json(silent=True) or {}
    course_id = data.get("course_id")
    title     = data.get("title", "").strip()
    if not course_id or not title:
        return jsonify({"error": "Missing 'course_id' or 'title'"}), 400
    body, status = idempotent_create("assignments", data, lambda: get_db().create_assignment(
        course_id=int(course_id),
        title=title,
        due_date=data.get("due_date", ""),
    ))
    return jsonify(body), status


@blueprint.patch("/assignments/<int:asgn_id>")
def assignment_update(asgn_id: int):
    data = request.get_json(silent=True) or {}
    get_db().update_assignment(asgn_id, **data)
    return jsonify({"id": asgn_id})


@blueprint.patch("/assignments/<int:asgn_id>/toggle")
def assignment_toggle(asgn_id: int):
    new_state = get_db().toggle_assignment(asgn_id)
    return jsonify({"id": asgn_id, "completed": int(new_state)})


@blueprint.delete("/assignments/<int:asgn_id>")
def assignment_delete(asgn_id: int):
    get_db().delete_assignment(asgn_id)
    return jsonify({"deleted": asgn_id})


@blueprint.delete("/assignments/completed")
def assignments_clear_completed():
    course_id = request.args.get("course_id", type=int)  # optional filter
    count = get_db().delete_completed_assignments(course_id=course_id)
    return jsonify({"deleted": count})

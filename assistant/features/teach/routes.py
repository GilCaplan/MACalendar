"""Teach's HTTP surface: `/labels*` — the labelling game.

A Flask blueprint rather than lines in `server.py`, per
`assistant/features/CONVENTION.md`: a surface owns a folder, declares itself
once to a registry, ships its own routes, and the generic layer never learns
its name. Teach is iOS-only — it has no Mac panel — but its routes live here
like every other feature's.

| route | what |
|---|---|
| `GET /labels/next` | items worth labelling, hardest-first (active learning) |
| `POST /labels` | record one answer as an EXPLICIT pick |
| `POST /labels/retrain` | refit now; the gate still applies |

No `url_prefix`: every path above is already absolute, and a prefix would move
all of them.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

blueprint = Blueprint("teach", __name__)


def get_db():
    """Resolved through `assistant.api.server` at CALL time, never bound at
    import. server.py re-exports `assistant.db.get_db`, and a test that swaps
    it there — `tests/integration/test_api_server.py`'s `app_client` fixture —
    has to reach the feature blueprints too. A blueprint holding its own early
    binding would quietly read the REAL ~/.assistant_tools/calendar.db while
    the test watched a temp one."""
    from assistant.api import server
    return server.get_db()


# ---------------------------------------------------------------- labels
#
# The labelling game (Gil, 2026-09-10): a tab on the phone that shows one
# title and the categories as buttons, so labelling is a few taps instead of
# a spreadsheet. What it produces is the only non-circular label source this
# project has — see `engine/label/feedback.py` for why an untouched label is
# not one.

@blueprint.get("/labels/next")
def labels_next():
    """Items worth labelling, hardest-first.

    ACTIVE LEARNING, not a random sample. A tap is only worth something if
    the system could not already answer, so the queue is ordered by where it
    is weakest:

      1. rows the RULES punted to the catch-all AND the model was unsure
         about — nothing can label these today
      2. rows where the rules and the model DISAGREE — one of them is wrong
      3. rows the catch-all took, model confident — a cheap confirmation

    Rows already labelled by hand are excluded: asking twice wastes the tap
    and, if the answers differ, quietly corrupts the set.
    """
    from assistant.actions.calendar import categories as _cat
    from assistant.engine.label import feedback as _fb
    from assistant.engine.label.model import LabelModel

    kind = (request.args.get("kind") or "event").strip()
    want = max(1, min(int(request.args.get("n") or 20), 100))
    done = {t.lower() for t, _l in _fb.gold(kind)}

    db = get_db()
    rows = []
    if kind == "event":
        model = LabelModel.load("event")
        seen = set()
        events = db.search_events("", limit=400) or []
        if hasattr(model, "warm"):
            # one batched embedding call for the whole queue, not one per title
            model.warm([(ev.get("title") or "").strip() for ev in events])
        for ev in events:
            title = (ev.get("title") or "").strip()
            key = title.lower()
            if not title or key in seen or key in done:
                continue
            seen.add(key)
            rule = _cat.classify(title)
            got = model.predict(title) if model else None
            if rule == "Personal" and got is None:
                rank = 0
            elif got and got[0] != rule:
                rank = 1
            elif rule == "Personal":
                rank = 2
            else:
                continue                  # the rules were confident: skip
            rows.append({"id": ev.get("id"), "text": title, "rank": rank,
                         "current": rule,
                         "suggestion": got[0] if got else None})
        options = [c["name"] for c in _cat.all_categories()]
    else:
        from assistant.actions.todo import tagging as _tag
        options = sorted(_tag.KEYWORDS)
        seen = set()
        for td in db.get_todos(list_name=None) if hasattr(db, "get_todos") else []:
            title = (td.get("title") or "").strip()
            key = title.lower()
            if not title or key in seen or key in done:
                continue
            seen.add(key)
            got = _tag.suggest_tags(title, options)
            if got:
                continue                  # the rules fired; not the weak spot
            rows.append({"id": td.get("id"), "text": title, "rank": 0,
                         "current": None, "suggestion": None})

    rows.sort(key=lambda r: r["rank"])
    return jsonify({"kind": kind, "options": options, "items": rows[:want],
                    "remaining": max(0, len(rows) - want),
                    "labelled": len(done)})


@blueprint.post("/labels")
def labels_record():
    """{"kind": "event", "text": "...", "label": "Fitness"} — or `labels`
    (a list) for a task.

    Recorded as an EXPLICIT pick: the user chose it, which is one of the two
    origins `feedback.py` will train on. Nothing here writes to the calendar
    row itself — the label being learned and the label on an existing event
    are different things, and conflating them would let one screen quietly
    rewrite the other.
    """
    from assistant.engine.label import feedback as _fb

    b = request.get_json(silent=True) or {}
    kind = str(b.get("kind") or "event")
    text = str(b.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "no text"}), 400
    if kind == "event":
        label = str(b.get("label") or "").strip()
        if not label:
            return jsonify({"ok": False, "error": "no label"}), 400
        _fb.record_category(text, b.get("current"), label, origin=_fb.EXPLICIT)
    else:
        labels = [str(x) for x in (b.get("labels") or []) if str(x).strip()]
        if not labels:
            return jsonify({"ok": False, "error": "no labels"}), 400
        _fb.record_tags(text, b.get("current"), labels, origin=_fb.EXPLICIT)
    counts = _fb.counts(kind)
    return jsonify({"ok": True, "counts": counts,
                    "retrain_due": _fb.should_retrain(kind)})


@blueprint.post("/labels/retrain")
def labels_retrain():
    """Refit now. The gate still applies — a model that is not better than
    the installed one does not ship, however many labels arrived."""
    from assistant.engine.label import train as _train
    kind = str((request.get_json(silent=True) or {}).get("kind") or "event")
    try:
        out = _train.train(kind, force=True, verbose=False)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    return jsonify({"ok": True, "result": out})

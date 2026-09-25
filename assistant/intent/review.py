"""What a remembered command DID, laid out for the review sheet.

The phone's "Review commands" screen and the Mac's review dialog both ask one
question per command: was this right, and if not, what should it have been?
Answering it well needs every object the command touched, not the first one —
a six-part command used to open a fix sheet showing one event (Gil,
2026-09-24: *"when reviewing it creates multiple objects yet only shows
one"*) — and, for a change, what the row looked like BEFORE, so "nothing
should have been done" can actually put it back.

`unreviewed()` is the one join both surfaces read (it was written twice, in
`server.py` and `review_dialog.py`, and the two copies had already started to
differ). Each command gains a `resolved` list, in the order its actions ran:

    type        "event" | "todo"
    id          the row id
    action      the action that touched it (create_event, delete_todo, ...)
    index       that action's position in the command's `actions`, or -1
    state       "live" (the row exists) | "gone" (deleted since, or by this command)
    title, date, start_time, end_time   — the row now, or as it was if gone
    list, completed                     — to-dos only
    before      the row as it stood before this command changed it, or None
                (creates have none; rows linked before 2026-09-24 have none)
    restore     for a row this command DELETED: the ready-to-POST body that
                puts it back ({"kind", "body"} — the same shape as the
                background check's revert), else None
"""
from __future__ import annotations

from typing import Any

_EVENT_FIELDS = ("title", "date", "start_time", "end_time")
_TODO_FIELDS = ("title", "due_date", "list", "completed")


def _event_view(row: dict) -> dict:
    return {"title": row.get("title") or "", "date": row.get("date") or "",
            "start_time": row.get("start_time") or "", "end_time": row.get("end_time") or ""}


def _todo_view(row: dict) -> dict:
    return {"title": row.get("title") or "", "date": row.get("due_date") or "",
            "start_time": "", "end_time": "", "list": row.get("list") or "",
            "completed": bool(row.get("completed"))}


def resolve(example_id: int, memory=None, db=None) -> list[dict[str, Any]]:
    """Every row this command touched, as the review sheet shows it."""
    if memory is None:
        from assistant.intent.memory import get_memory
        memory = get_memory()
    if db is None:
        from assistant.db import get_db
        db = get_db()
    from assistant.engine import _revert_spec

    out: list[dict[str, Any]] = []
    for rec in memory.records_for(example_id):
        kind, rid = rec["record_type"], int(rec["record_id"])
        try:
            now = db.get_event(rid) if kind == "event" else db.get_todo(rid)
        except Exception:
            now = None
        before = rec.get("before")
        view = _event_view if kind == "event" else _todo_view
        shown = now or before
        if shown is None:
            # A create whose row has since been removed, linked before rows
            # carried their old state: there is nothing left to show.
            continue
        entry = {"type": kind, "id": rid, "action": rec["action"],
                 "index": int(rec.get("action_index", -1)),
                 "state": "live" if now else "gone", **view(shown),
                 "before": view(before) if before else None, "restore": None}
        if not now and before and rec["action"].startswith("delete_"):
            entry["restore"] = _revert_spec(kind, before)
        out.append(entry)
    return out


def unreviewed(limit: int = 30) -> list[dict[str, Any]]:
    """Successful commands nobody has judged yet, newest first, each with its
    `resolved` rows. Health probes and harness traffic (source "test") are
    machine noise, not the user's asks — 43 of them once flooded the phone's
    review queue with identical "what do I have today"s."""
    from assistant.db import get_db
    from assistant.intent.memory import get_memory
    memory, db = get_memory(), get_db()
    rows = [r for r in memory.recent(200)
            if r["feedback"] == "none" and r["success"] and r["actions"]
            and r.get("source") != "test"][:limit]
    for r in rows:
        r["resolved"] = resolve(r["id"], memory, db)
    return rows


# ---------------------------------------------------------------------------
# The fix sheet's logic — what each object's verdict writes, and what the
# command SHOULD have produced. The phone (`AssistantReviewView.swift`,
# `FixObject` / `CorrectionSheet`) runs the same rules over the API; the Mac's
# dialog runs these against the database it owns. Change one, change both.
# ---------------------------------------------------------------------------

RIGHT, CHANGE, UNDO = "right", "change", "undo"


class FixRow:
    """One thing a command did — or, with ``index`` None, should have done."""

    def __init__(self, *, index, action, kind, title="", date="", start="", end="",
                 record=None, choice=RIGHT):
        self.index, self.action, self.record = index, action, record
        self.kind, self.title, self.date = kind, title, date
        self.start, self.end, self.choice = start, end, choice

    added = property(lambda s: s.index is None)
    is_create = property(lambda s: s.action.startswith("create_"))
    is_update = property(lambda s: s.action.startswith("update_"))
    is_delete = property(lambda s: s.action.startswith("delete_"))
    is_complete = property(lambda s: s.action == "complete_todo")

    @property
    def read_only(self) -> bool:
        """A question answered: nothing in the calendar to edit or take back."""
        return not self.added and not (self.is_create or self.is_update
                                       or self.is_delete or self.is_complete)

    @property
    def can_undo(self) -> bool:
        r = self.record or {}
        if self.is_create:
            return r.get("id") is not None and r.get("state") != "gone"
        if self.is_delete:
            return bool(r.get("restore"))
        if self.is_update:
            return bool(r.get("before")) and r.get("id") is not None
        if self.is_complete:
            return r.get("id") is not None and bool(r.get("completed"))
        return False

    @property
    def undo_label(self) -> str:
        return ("Remove" if self.is_create else "Restore" if self.is_delete
                else "Put back" if self.is_update else "Reopen" if self.is_complete
                else "Wrong")

    @property
    def verb(self) -> str:
        return {"create_event": "New event", "create_todo": "New to-do",
                "update_event": "Changed event", "update_todo": "Changed to-do",
                "delete_event": "Deleted event", "delete_todo": "Deleted to-do",
                "complete_todo": "Ticked off", "query_schedule": "Read your schedule",
                "query_todos": "Read your to-dos",
                "": "Missed event" if self.kind == "event" else "Missed to-do",
                }.get(self.action, self.action.replace("_", " ").capitalize())

    def event_fields(self) -> dict:
        f = {"title": self.title}
        for k, v in (("date", self.date), ("start_time", self.start), ("end_time", self.end)):
            if v:
                f[k] = v
        return f


def rows_for(example: dict) -> list[FixRow]:
    """Every object the command touched, in the order it ran: the rows the
    Mac linked, and — for an action nothing was linked to — what was asked."""
    resolved = example.get("resolved") or []
    indexed = any(int(r.get("index", -1)) >= 0 for r in resolved)
    unclaimed = list(resolved)
    out: list[FixRow] = []
    for i, a in enumerate(example.get("actions") or []):
        name, p = a.get("action", ""), a.get("parameters") or {}
        if indexed:
            mine = [r for r in resolved if int(r.get("index", -1)) == i]
        else:
            k = next((j for j, r in enumerate(unclaimed) if r.get("action") == name), None)
            mine = [unclaimed.pop(k)] if k is not None else []
        if mine:
            out += [FixRow(index=i, action=name, record=r, kind=r["type"],
                           title=r.get("title", ""), date=r.get("date", ""),
                           start=r.get("start_time", ""), end=r.get("end_time") or "")
                    for r in mine]
            continue
        if name == "create_todo":
            titles = p.get("titles") or ([p["title"]] if p.get("title") else [""])
            out += [FixRow(index=i, action=name, kind="todo", title=t,
                           date=p.get("due_date", "")) for t in titles]
            continue
        todo = name.endswith("_todo") or name.endswith("_todos")
        out.append(FixRow(index=i, action=name, kind="todo" if todo else "event",
                          title=p.get("title") or p.get("match_title") or "",
                          date=p.get("date") or p.get("match_date") or "",
                          start=p.get("start_time", ""), end=p.get("end_time", "")))
    return out


def ops_for(row: FixRow) -> list[tuple]:
    """The calendar writes one row's verdict asks for."""
    r = row.record or {}
    rid = r.get("id")
    if row.added:
        if not row.title.strip():
            return []
        return [("create_event", row.event_fields())] if row.kind == "event" \
            else [("create_todo", row.title, row.date)]
    if row.choice == UNDO:
        if not row.can_undo:
            return []
        if row.is_create:
            return [("delete_" + r["type"], rid)]
        if row.is_delete:
            return [("restore", r["restore"])]
        if row.is_complete:
            return [("toggle_todo", rid)]
        b = r["before"]
        if r["type"] == "event":
            f = {"title": b["title"], "date": b["date"], "start_time": b["start_time"]}
            if b.get("end_time"):
                f["end_time"] = b["end_time"]
            return [("patch_event", rid, f)]
        return [("patch_todo", rid, b["title"], b.get("date", ""))]
    if row.choice == CHANGE:
        if rid is None or r.get("state") == "gone":
            return []           # nothing to edit in place; the fix is still taught
        if r["type"] != row.kind:
            make = ("create_event", row.event_fields()) if row.kind == "event" \
                else ("create_todo", row.title, row.date)
            return [("delete_" + r["type"], rid), make]
        return [("patch_event", rid, row.event_fields())] if row.kind == "event" \
            else [("patch_todo", rid, row.title, row.date)]
    return []


def gold(example: dict, rows: list[FixRow]) -> list[dict]:
    """What the command SHOULD have produced, action by action in the order it
    ran, so `intent/correction.annotate` can pair it with what it did. An
    action taken back is absent; "nothing should have been done" is []."""
    out: list[dict] = []
    for i, a in enumerate(example.get("actions") or []):
        mine = [r for r in rows if r.index == i]
        if not mine or all(r.choice == RIGHT for r in mine):
            out.append({"action": a.get("action"), "parameters": dict(a.get("parameters") or {})})
            continue
        kept = [r for r in mine if r.choice != UNDO]
        if not kept:
            continue
        if a.get("action", "").startswith("create_"):
            todos = [r for r in kept if r.kind == "todo"]
            if todos:
                p = {"titles": [r.title for r in todos]}
                due = next((r.date for r in todos if r.date), "")
                if due:
                    p["due_date"] = due
                out.append({"action": "create_todo", "parameters": p})
            out += [{"action": "create_event", "parameters": r.event_fields()}
                    for r in kept if r.kind == "event"]
        else:
            p = dict(a.get("parameters") or {})
            if kept[0].choice == CHANGE:
                p.update(kept[0].event_fields())
            out.append({"action": a.get("action"), "parameters": p})
    for r in rows:
        if r.added and r.title.strip():
            out.append({"action": "create_event", "parameters": r.event_fields()}
                       if r.kind == "event" else
                       {"action": "create_todo",
                        "parameters": {"titles": [r.title], **({"due_date": r.date} if r.date else {})}})
    return out


def plan(example: dict, rows: list[FixRow], reasons=(), notes: str = "") -> dict:
    """{ops, feedback, correction, notes} for Save. Only a verdict with no
    edit, removal or addition is a plain "rejected" with the reasons as notes."""
    why = "; ".join(sorted(reasons))
    note = " ".join(x for x in ((f"[{why}]" if why else ""), notes.strip()) if x)
    touched = any(r.choice != RIGHT or r.added for r in rows)
    if not touched:
        return {"ops": [], "feedback": "rejected", "correction": None, "notes": note}
    ops = [op for r in rows for op in ops_for(r)]
    return {"ops": ops, "feedback": "corrected", "correction": gold(example, rows), "notes": note}


def apply(ops: list[tuple], db=None) -> list[str]:
    """Run a plan's writes against the calendar database (the Mac's path; the
    phone makes the same writes over the API). Returns what failed, if any."""
    if db is None:
        from assistant.db import get_db
        db = get_db()
    failed = []
    for op in ops:
        try:
            kind = op[0]
            if kind == "patch_event":
                db.update_event(op[1], **op[2])
            elif kind == "delete_event":
                db.delete_event(op[1])
            elif kind == "create_event":
                f = dict(op[1])
                f.setdefault("date", _today())
                f.setdefault("start_time", "09:00")
                f.setdefault("end_time", _plus_hour(f["start_time"]))
                db.create_event_from_dict(f)
            elif kind == "patch_todo":
                db.update_todo(op[1], title=op[2], due_date=op[3] or "")
            elif kind == "delete_todo":
                db.delete_subtasks_for_todo(op[1])
                db.delete_todo(op[1])
            elif kind == "toggle_todo":
                db.toggle_todo_complete(op[1])
            elif kind == "create_todo":
                db.create_todo(op[1], due_date=op[2] or "")
            elif kind == "restore":
                spec = op[1]
                body = dict(spec["body"])
                if spec["kind"] == "event":
                    db.create_event_from_dict(body)
                else:
                    db.create_todo(body.pop("title"), **body)
        except Exception as exc:        # one failed write must not lose the rest
            failed.append(f"{op[0]}: {exc}")
    return failed


def _today() -> str:
    import datetime as _dt
    return _dt.date.today().isoformat()


def _plus_hour(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":")[:2])
    return f"{min(h + 1, 23):02d}:{m:02d}"

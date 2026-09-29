"""Occasions routes — HTTP only (DEVQA Q73).

    GET    /occasions                  this person's occasions + countdowns ahead
    POST   /occasions                  add one {kind, title, calendar, month, day, year?, …}
    PATCH  /occasions/<id>             change it (the banner's editor)
    DELETE /occasions/<id>             remove it
    GET    /occasions/range?start&end  every banner in the range (theirs + the
                                       computed calendars switched on)
"""

from __future__ import annotations

import datetime

from flask import jsonify, request

from assistant.occasions import feed, store


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg, "code": code}), code


def register(app) -> None:
    @app.get("/occasions")
    def occasions_list():
        return jsonify({"occasions": store.load(), "countdowns": feed.countdowns()})

    @app.post("/occasions")
    def occasions_add():
        got, why = store.add(request.get_json(silent=True) or {})
        return (jsonify(got), 201) if got else _err(why)

    @app.patch("/occasions/<oid>")
    def occasions_update(oid: str):
        got, why = store.update(oid, request.get_json(silent=True) or {})
        if got:
            return jsonify(got)
        return _err(why, 404 if why == "no such occasion" else 400)

    @app.delete("/occasions/<oid>")
    def occasions_delete(oid: str):
        return jsonify({"deleted": oid}) if store.delete(oid) else _err("no such occasion", 404)

    @app.get("/occasions/range")
    def occasions_range():
        try:
            start = datetime.date.fromisoformat(request.args.get("start", ""))
            end = datetime.date.fromisoformat(request.args.get("end", ""))
        except ValueError:
            return _err("start and end are YYYY-MM-DD")
        return jsonify({"banners": feed.banners(start, end)})

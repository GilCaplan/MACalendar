"""Users, phase 3: sharing and the merged calendar, over HTTP.

DEVQA Q65: a user shares their WHOLE calendar + to-dos per person, VIEW or
EDIT; the admin sees and edits everything and toggles a user into his view
(off until he does). Rows come back in the owner's colour and name; ids of
rows the viewer does not own are namespaced so two files' "event 7" never
collide; a write runs AS the owner.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib

import pytest

from assistant import users
from assistant.users import paths, registry, sharing

DAY = "2026-10-06"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    from assistant.users import routes
    routes._fails.clear()
    gil = registry.create_user("gil", "admin-pass", role="admin")
    dana = registry.create_user("dana", "dana-pass")
    noa = registry.create_user("noa", "noa-pass")
    from assistant.api import server
    c = server.create_app().test_client()
    tok = {n: c.post("/auth/login", json={"username": n, "password": f"{'admin' if n == 'gil' else n}-pass"}
                     ).get_json()["session_token"] for n in ("gil", "dana", "noa")}
    return c, {"gil": gil, "dana": dana, "noa": noa}, tok


def _h(tok):
    return {"X-Session-Token": tok}


def _event(uid, title, start="09:00"):
    from assistant.db import get_db
    with users.bind(uid):
        return get_db().create_event_from_dict({
            "title": title, "date": DAY, "start_time": start, "end_time": "10:00",
            "attendees": "", "location": "", "description": "",
            "recurrence": "", "recurrence_end": ""})


def _day(c, tok):
    return c.get(f"/events?date={DAY}", headers=_h(tok)).get_json()


def _titles_in(uid):
    from assistant.db import get_db
    with users.bind(uid):
        return [e["title"] for e in get_db().get_events_for_day(dt.date.fromisoformat(DAY))]


# ------------------------------------------------------------------ ids

def test_own_ids_are_unchanged_and_others_round_trip():
    registry_seq = 3
    enc = (registry_seq << sharing.SHIFT) | 7
    assert enc > 2 ** 32 and enc < 2 ** 53
    assert (enc >> sharing.SHIFT, enc & ((1 << sharing.SHIFT) - 1)) == (3, 7)


def _color_in(uid, event_id):
    from assistant.db import get_db
    with users.bind(uid):
        return get_db().get_event(event_id)["color"]


# ------------------------------------------------------------------ view share

def test_a_view_share_shows_the_owners_rows_with_their_name_and_colour_edge(world):
    c, u, tok = world
    ev = _event(u["dana"], "dana's dentist")
    _event(u["noa"], "noa's gym")
    registry.set_share(u["dana"], u["noa"], "view")
    rows = {r["title"]: r for r in _day(c, tok["noa"])}
    assert set(rows) == {"dana's dentist", "noa's gym"}
    shared, own = rows["dana's dentist"], rows["noa's gym"]
    assert shared["owner_name"] == "Dana" and shared["shared"] and not shared["can_edit"]
    # the event keeps its own (category) colour; the owner's rides alongside
    # for the card's edge (Gil, 2026-09-28)
    assert shared["owner_color"] == registry.get(u["dana"])["color"]
    assert shared["color"] != "" and shared["color"] == _color_in(u["dana"], ev)
    assert shared["id"] != ev and shared["id"] > 2 ** 32           # namespaced
    assert own["id"] < 2 ** 32 and not own["shared"] and own["can_edit"]
    # readable by that id; not changeable with a view share
    assert c.get(f"/events/{shared['id']}", headers=_h(tok["noa"])).get_json()["title"] == "dana's dentist"
    r = c.patch(f"/events/{shared['id']}", json={"title": "hacked"}, headers=_h(tok["noa"]))
    assert r.status_code == 403
    assert _titles_in(u["dana"]) == ["dana's dentist"]


def test_without_a_share_another_users_row_is_not_found_not_forbidden(world):
    c, u, tok = world
    ev = _event(u["dana"], "private")
    guessed = (registry.load()["users"][u["dana"]]["seq"] << sharing.SHIFT) | ev
    assert c.get(f"/events/{guessed}", headers=_h(tok["noa"])).status_code == 404
    assert "private" not in [r["title"] for r in _day(c, tok["noa"])]


def test_an_edit_share_writes_into_the_owners_own_file(world):
    c, u, tok = world
    _event(u["dana"], "dana's dentist")
    registry.set_share(u["dana"], u["noa"], "edit")
    sid = next(r["id"] for r in _day(c, tok["noa"]) if r["title"] == "dana's dentist")
    assert c.patch(f"/events/{sid}", json={"title": "dentist (moved)"},
                   headers=_h(tok["noa"])).status_code == 200
    assert _titles_in(u["dana"]) == ["dentist (moved)"]
    assert _titles_in(u["noa"]) == []
    assert c.delete(f"/events/{sid}", headers=_h(tok["noa"])).status_code == 200
    assert _titles_in(u["dana"]) == []


def test_the_editor_can_add_straight_into_a_calendar_it_may_edit(world):
    c, u, tok = world
    body = {"title": "for dana", "date": DAY, "start_time": "12:00", "end_time": "13:00",
            "owner_id": u["dana"]}
    assert c.post("/events", json=body, headers=_h(tok["noa"])).status_code == 403
    registry.set_share(u["dana"], u["noa"], "edit")
    r = c.post("/events", json=body, headers=_h(tok["noa"]))
    assert r.status_code == 201 and r.get_json()["id"] > 2 ** 32
    assert _titles_in(u["dana"]) == ["for dana"] and _titles_in(u["noa"]) == []


# ------------------------------------------------------------------ admin

def test_the_admin_sees_others_only_once_toggled_but_may_edit_regardless(world):
    c, u, tok = world
    _event(u["dana"], "dana's dentist")
    _event(u["gil"], "gil's shiur")
    assert [r["title"] for r in _day(c, tok["gil"])] == ["gil's shiur"]
    registry.set_admin_view(u["gil"], u["dana"], True)
    rows = {r["title"]: r for r in _day(c, tok["gil"])}
    assert set(rows) == {"gil's shiur", "dana's dentist"}
    assert rows["dana's dentist"]["can_edit"]
    assert c.patch(f"/events/{rows['dana' + chr(39) + 's dentist']['id']}", json={"title": "by admin"},
                   headers=_h(tok["gil"])).status_code == 200
    assert _titles_in(u["dana"]) == ["by admin"]
    # a toggle is the admin's view, not a share: Dana still sees only her own
    assert [r["title"] for r in _day(c, tok["dana"])] == ["by admin"]


# ------------------------------------------------------------------ to-dos

def test_shared_todos_are_mixed_in_and_links_never_cross_calendars(world):
    c, u, tok = world
    from assistant.db import get_db
    with users.bind(u["dana"]):
        t = get_db().create_todo("dana's milk")
    ev = _event(u["noa"], "noa's thing")
    registry.set_share(u["dana"], u["noa"], "edit")
    rows = {r["title"]: r for r in c.get("/todos?list=all", headers=_h(tok["noa"])).get_json()}
    assert rows["dana's milk"]["owner_name"] == "Dana" and rows["dana's milk"]["id"] != t
    sid = rows["dana's milk"]["id"]
    assert c.patch(f"/todos/{sid}/toggle", headers=_h(tok["noa"])).status_code == 200
    r = c.put(f"/todos/{sid}/link", json={"event_id": ev}, headers=_h(tok["noa"]))
    assert r.status_code == 403


def test_the_change_token_moves_when_a_shared_calendar_changes(world):
    c, u, tok = world
    registry.set_share(u["dana"], u["noa"], "view")
    before = c.get("/changes", headers=_h(tok["noa"])).get_data(as_text=True)
    import time
    time.sleep(0.02)
    _event(u["dana"], "new on dana's side")
    after = c.get("/changes", headers=_h(tok["noa"])).get_data(as_text=True)
    assert before != after


def test_a_spoken_delete_never_reaches_a_shared_row(world, monkeypatch, registry_with_real_actions):
    """Deletion is destructive: the engine acts on the SPEAKER's calendar only,
    so an edit share never lets a mishearing delete someone else's event."""
    import assistant.engine.llm as _llm
    import assistant.intent.parser as _parser
    from assistant.exceptions import OllamaUnavailableError
    monkeypatch.setattr(_parser.IntentParser, "_call_ollama",
                        lambda *a, **k: (_ for _ in ()).throw(OllamaUnavailableError("no model")))
    monkeypatch.setattr(_llm, "is_reachable", lambda cfg=None: False)
    c, u, tok = world
    _event(u["dana"], "team meeting")
    _event(u["noa"], "team meeting")       # the control: the delete DOES work on hers
    registry.set_share(u["dana"], u["noa"], "edit")
    c.post("/voice/text", json={"transcript": f"delete the team meeting on {DAY}", "source": "test"},
           headers=_h(tok["noa"]))
    assert _titles_in(u["noa"]) == [], "the spoken delete did not run at all"
    assert _titles_in(u["dana"]) == ["team meeting"]


def test_the_calendar_sync_loop_serves_each_user_as_themselves(world, monkeypatch):
    from assistant.calendar_sync import scheduler
    _, u, _ = world
    seen = []
    monkeypatch.setattr(scheduler, "_has_sources", lambda: True)
    monkeypatch.setattr(scheduler, "sync_now", lambda config=None: seen.append(users.current()))
    for uid in users.each_user():
        with users.bind(uid):
            if scheduler._has_sources():
                scheduler.sync_now(config=None)
    assert sorted(seen) == sorted(u.values())


def test_a_vocabulary_the_admin_shares_corrects_that_users_speech_and_learns_nothing(world):
    from assistant.stt.vocab import apply_vocab, get_vocab
    _, u, _ = world
    with users.bind(u["gil"]):
        get_vocab().add_word("Jada", ["jaida"])
        before = pathlib.Path(get_vocab()._path).read_bytes()
    with users.bind(u["dana"]):
        assert "jaida" in apply_vocab("walk jaida at nine", source="test")[0].lower()   # not shared yet
    registry.set_vocab_share(u["gil"], u["dana"], True)
    with users.bind(u["dana"]):
        fixed, _ = apply_vocab("walk jaida at nine", source="test")
        assert "Jada" in fixed
        assert "Jada" not in [e.word for e in get_vocab().entries]           # Dana's own list untouched
    with users.bind(u["gil"]):
        assert pathlib.Path(get_vocab()._path).read_bytes() == before       # Gil's list learned nothing

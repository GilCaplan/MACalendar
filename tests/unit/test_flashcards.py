"""Flashcards: the card format, import / re-import, the study queue, the
scheduler, the inbox an agent drops files into, and the HTTP surface.

Every store here is a tmp_path file — the real `flashcards.db` holds what Gil
is studying, and `conftest.py` redirects MACALENDAR_FLASHCARDS besides.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import pathlib
import re
import zipfile

import pytest
import yaml
from flask import Flask

from assistant.features.flashcards import cardformat, fsrs
from assistant.features.flashcards.store import FlashcardError, FlashcardStore

HERE = pathlib.Path(__file__).resolve()
FEATURE = HERE.parents[2] / "assistant" / "features" / "flashcards"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
       b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
       b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def store(tmp_path):
    return FlashcardStore(str(tmp_path / "flashcards.db"))


def _doc(cards, set_="Verbs", subject="Spanish", **kw):
    return {"subject": subject, "set": set_, "cards": cards, **kw}


BASIC = [{"type": "basic", "front": f"q{i}", "back": f"a{i}"} for i in range(5)]


# ---------------------------------------------------------------- the format

def _format_examples():
    text = (FEATURE / "FORMAT.md").read_text(encoding="utf-8")
    return [yaml.safe_load(b) for b in re.findall(r"```yaml\n(.*?)```", text, re.S)]


def test_every_card_in_format_md_is_valid():
    """FORMAT.md is what agents copy. If an example there stops importing, the
    agent's file stops importing too."""
    cards = [c for ex in _format_examples() if isinstance(ex.get("cards"), list)
             for c in ex["cards"] if isinstance(c, dict)]
    assert {c["type"] for c in cards} == set(cardformat.TYPES)
    for c in cards:
        cardformat.normalise(c)


def test_format_md_examples_import_with_their_pictures(store):
    ex = next(e for e in _format_examples() if any(c.get("type") == "occlusion" for c in e.get("cards", [])))
    media = {"images/stethoscope.png": PNG, "images/map.jpg": PNG}
    out = store.import_doc(_doc(ex["cards"]), media=media)
    assert out[0]["added"] == len(ex["cards"])


@pytest.mark.parametrize("card,needle", [
    ({"type": "mc", "question": "q", "choices": ["a", "b"], "answer": "c"}, "not one of the choices"),
    ({"type": "basic", "front": "q", "back": "a", "anwser": "x"}, "unknown field"),
    ({"type": "cloze", "text": "no gaps"}, "{{blank}}"),
    ({"type": "occlusion", "image": "i.png", "labels": [{"text": "x", "box": [90, 0, 20, 5]}]}, "outside"),
    ({"type": "order", "prompt": "p", "steps": ["one"]}, "2 to 20"),
    ({"type": "flip", "front": "q"}, "unknown type"),
])
def test_bad_cards_are_refused_with_a_sentence(card, needle):
    with pytest.raises(cardformat.CardError, match=re.escape(needle)):
        cardformat.normalise(card)


def test_english_mirrors_the_card_and_is_not_its_identity():
    """Gil, 2026-10-12: an English line beside a Hebrew card. Adding it must
    not cost the progress already made on the card."""
    he = {"type": "basic", "front": "שאלה", "back": "תשובה", "explain": "הסבר"}
    en = dict(he, en={"front": "Question", "back": "Answer", "explain": "Why"})
    clean = cardformat.normalise(en)
    assert clean["en"] == {"front": "Question", "back": "Answer", "explain": "Why"}
    assert cardformat.key(clean) == cardformat.key(cardformat.normalise(he))
    mc = cardformat.normalise({"type": "mc", "question": "ש", "choices": ["א", "ב"], "answer": "א",
                               "en": {"question": "Q", "choices": ["A", "B"], "answer": "A"}})
    assert mc["en"]["choices"] == ["A", "B"]
    cloze = {"type": "cloze", "text": "{{א}} ו{{ב}}", "en": {"text": "{{A}} and {{B}}"}}
    assert cardformat.normalise(cloze)["en"]["text"] == "{{A}} and {{B}}"


@pytest.mark.parametrize("en,needle", [
    ({"question": "Q"}, "no 'question'"),
    ({"front": ["x"]}, "must be text"),
    ({"back": "A", "colour": "red"}, "unknown field"),
    ("Question", "mapping"),
])
def test_english_that_does_not_fit_the_card_is_refused(en, needle):
    with pytest.raises(cardformat.CardError, match=re.escape(needle)):
        cardformat.normalise({"type": "basic", "front": "ש", "back": "ת", "en": en})


def test_english_lists_and_gaps_must_line_up():
    with pytest.raises(cardformat.CardError, match="must list 2"):
        cardformat.normalise({"type": "order", "prompt": "p", "steps": ["a", "b"],
                              "en": {"steps": ["only one"]}})
    with pytest.raises(cardformat.CardError, match="same number"):
        cardformat.normalise({"type": "cloze", "text": "{{a}} {{b}}", "en": {"text": "{{A}} only"}})


def test_reimporting_with_english_keeps_progress(store):
    """How English reaches cards already being studied: export the set, add
    `en` to each card, import it again — progress stays."""
    [r] = store.import_doc(_doc(BASIC))
    sid = r["set_id"]
    store.review(store.get_set(sid)["cards"][0]["id"], "", 3)
    doc = store.export_doc(sid)
    for c in doc["cards"]:
        c["en"] = {"front": c["front"].upper(), "back": c["back"].upper()}
    [r2] = store.import_doc(doc)
    assert (r2["added"], r2["removed"]) == (0, 0)
    card = store.get_set(sid)["cards"][0]
    assert card["en"] == {"front": "Q0", "back": "A0"}
    assert card["progress"][""]["reps"] == 1


def test_study_items_split_what_is_remembered_separately():
    assert cardformat.items({"type": "cloze", "text": "{{a}} and {{b}}"}) == ["c0", "c1"]
    occ = {"type": "occlusion", "image": "m", "labels": [{"text": "x", "box": [0, 0, 1, 1]}] * 3}
    assert cardformat.items({**occ, "ask": "one_at_a_time"}) == ["l0", "l1", "l2"]
    assert cardformat.items({**occ, "ask": "all_at_once"}) == [""]
    assert cardformat.items({"type": "basic", "front": "q", "back": "a", "both_ways": True}) == ["", "rev"]


def test_identity_ignores_tags_page_and_explanation():
    a = cardformat.normalise({"type": "basic", "front": "q", "back": "a", "page": 3})
    b = cardformat.normalise({"type": "basic", "front": "q", "back": "a", "tags": ["x"], "explain": "e"})
    assert cardformat.key(a) == cardformat.key(b)
    assert cardformat.key(a) != cardformat.key({**a, "back": "b"})


# ---------------------------------------------------------------- import

def test_reimport_keeps_progress_on_unchanged_cards(store):
    [r] = store.import_doc(_doc(BASIC))
    sid = r["set_id"]
    q0 = store.get_set(sid)["cards"][0]
    store.review(q0["id"], "", 3)
    changed = BASIC[1:] + [{"type": "basic", "front": "new", "back": "card"}]
    [r2] = store.import_doc(_doc([{**BASIC[0], "tags": ["t"]}] + changed[:-1] + changed[-1:]))
    assert (r2["added"], r2["kept"], r2["removed"]) == (1, 5, 0)
    s = store.get_set(sid)
    assert s["cards"][0]["progress"][""]["reps"] == 1          # tag added, progress kept
    assert s["cards"][0]["tags"] == ["t"]


def test_replace_removes_cards_the_file_dropped(store):
    [r] = store.import_doc(_doc(BASIC))
    [r2] = store.import_doc(_doc(BASIC[:2]))
    assert r2["removed"] == 3
    assert len(store.get_set(r["set_id"])["cards"]) == 2


def test_append_only_adds(store):
    [r] = store.import_doc(_doc(BASIC[:3]))
    [r2] = store.import_doc(_doc(BASIC[2:]), mode="append")
    assert (r2["added"], r2["kept"], r2["removed"]) == (2, 1, 0)
    assert [c["front"] for c in store.get_set(r["set_id"])["cards"]] == [f"q{i}" for i in range(5)]


def test_one_bad_card_refuses_the_whole_file(store):
    bad = BASIC + [{"type": "mc", "question": "q", "choices": ["a", "b"], "answer": "z"}]
    with pytest.raises(FlashcardError, match="card 6"):
        store.import_doc(_doc(bad))
    assert store.library() == []


def test_a_picture_must_arrive_with_its_card(store):
    card = {"type": "image", "image": "images/x.png", "back": "X"}
    with pytest.raises(FlashcardError, match="images/x.png"):
        store.import_doc(_doc([card]))
    with pytest.raises(FlashcardError, match="inside the set"):
        store.import_doc(_doc([{**card, "image": "../../etc/passwd"}]), media={"../../etc/passwd": b"x"})


def test_zip_import_carries_pictures(store, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("deck/set.yaml", yaml.safe_dump(_doc([{"type": "image", "image": "images/x.png", "back": "X"}])))
        z.writestr("deck/images/x.png", PNG)
    [r] = store.import_file("deck.zip", buf.getvalue())
    path = store.media_path(r["set_id"], "images/x.png")
    assert pathlib.Path(path).read_bytes() == PNG


def test_multi_set_file_and_hebrew_direction(store):
    out = store.import_doc({"subject": "היסטוריה", "lang": "he", "sets": [
        {"set": "פרק 1", "cards": BASIC[:2]}, {"set": "פרק 2", "cards": BASIC[2:]}]})
    assert len(out) == 2
    [subject] = store.library()
    assert subject["name"] == "היסטוריה"
    assert {s["dir"] for s in subject["sets"]} == {"rtl"}
    assert sum(s["cards"] for s in subject["sets"]) == 5


def test_export_round_trips(store):
    cards = [{"type": "cloze", "text": "{{a}} b", "page": 4},
             {"type": "mc", "question": "q", "choices": ["1", "2"], "answer": "2", "explain": "e"}]
    [r] = store.import_doc(_doc(cards, set_id="v1", lang="es"))
    doc = store.export_doc(r["set_id"])
    assert doc["cards"] == [cardformat.normalise(c) for c in cards]
    [again] = store.import_doc(doc)
    assert (again["set_id"], again["added"], again["kept"]) == (r["set_id"], 0, 2)


# ---------------------------------------------------------------- the inbox

def test_inbox_imports_and_files_away(store):
    inbox = pathlib.Path(store.inbox_dir)
    inbox.mkdir(parents=True)
    (inbox / "good.yaml").write_text(yaml.safe_dump(_doc(BASIC)), encoding="utf-8")
    (inbox / "good.append.yaml").write_text(
        yaml.safe_dump(_doc([{"type": "basic", "front": "more", "back": "x"}])), encoding="utf-8")
    (inbox / "bad.yaml").write_text("subject: x\nset: y\ncards: []\n", encoding="utf-8")
    (inbox / "notes.txt").write_text("ignored")
    res = store.import_inbox()
    assert sorted(r["file"] for r in res) == ["bad.yaml", "good.append.yaml", "good.yaml"]
    assert any("no cards" in r.get("error", "") for r in res)
    assert sorted(p.name for p in inbox.iterdir() if p.is_file()) == ["notes.txt"]
    assert len(list((inbox / "imported").iterdir())) == 2
    assert any(p.name.endswith(".error.txt") for p in (inbox / "failed").iterdir())
    [sub] = store.library()
    assert sub["sets"][0]["cards"] == 6


# ---------------------------------------------------------------- editing

def test_cards_by_hand(store):
    sid = store.create_set("Spanish", "Food")
    cid = store.add_card(sid, {"type": "basic", "front": "pan", "back": "bread"}, client_token="t1")
    assert store.add_card(sid, {"type": "basic", "front": "pan", "back": "bread"}, client_token="t1") == cid
    with pytest.raises(FlashcardError, match="already has"):
        store.add_card(sid, {"type": "basic", "front": "pan", "back": "bread"})
    store.update_card(cid, {"type": "cloze", "text": "{{pan}} is bread, {{agua}} is water"})
    store.review(cid, "c1", 3)
    store.update_card(cid, {"type": "cloze", "text": "{{pan}} is bread"})
    assert store.get_set(sid)["cards"][0]["progress"] == {}      # c1 no longer exists
    store.delete_card(cid)
    assert store.get_set(sid)["cards"] == []


def test_move_card_reorders_within_its_set(store):
    sid = store.create_set("Spanish", "Order")
    ids = [store.add_card(sid, {"type": "basic", "front": f"f{i}", "back": "b"}) for i in range(3)]
    store.move_card(ids[2], -1)
    assert [c["id"] for c in store.get_set(sid)["cards"]] == [ids[0], ids[2], ids[1]]
    store.move_card(ids[0], -5)                  # clamped at the top: no change
    store.move_card(ids[0], 9)                   # clamped at the bottom
    assert [c["id"] for c in store.get_set(sid)["cards"]] == [ids[2], ids[1], ids[0]]
    with pytest.raises(FlashcardError):
        store.move_card(99999, 1)


# ---------------------------------------------------------------- study + schedule

def _two_sets(store):
    a = store.import_doc(_doc(BASIC, set_="A"))[0]["set_id"]
    b = store.import_doc(_doc([{"type": "mc", "question": f"m{i}", "choices": ["x", "y"], "answer": "x"}
                               for i in range(4)], set_="B"))[0]["set_id"]
    return a, b


def test_study_mixes_one_some_or_all_sets(store):
    a, b = _two_sets(store)
    assert {e["set_id"] for e in store.study([a], limit=0)} == {a}
    assert {e["set_id"] for e in store.study([a, b], limit=0)} == {a, b}
    assert len(store.study([a, b], limit=3)) == 3
    exam = store.study([a, b], mode="exam", limit=0)
    assert {e["card"]["type"] for e in exam} == {"mc"} and len(exam) == 4
    assert {e["card"]["type"] for e in store.study([a, b], types=["basic"], limit=0)} == {"basic"}
    with pytest.raises(FlashcardError):
        store.study([])


def test_smart_puts_due_first_and_hides_what_is_not_due(store):
    a, _ = _two_sets(store)
    t0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
    cards = store.get_set(a)["cards"]
    store.review(cards[0]["id"], "", 3, at=t0.isoformat())     # due in days
    store.review(cards[1]["id"], "", 1, at=t0.isoformat())     # due in 10 minutes
    q = store.study([a], now=t0 + dt.timedelta(hours=1), limit=0)
    assert q[0]["card_id"] == cards[1]["id"]
    assert cards[0]["id"] not in [e["card_id"] for e in q]
    assert len(q) == 4


def test_fsrs_grows_on_success_and_shrinks_on_a_lapse(store):
    sid = store.import_doc(_doc(BASIC[:1]))[0]["set_id"]
    cid = store.get_set(sid)["cards"][0]["id"]
    t = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    gaps = []
    for _ in range(4):
        p = store.review(cid, "", 3, at=t.isoformat())
        due = dt.datetime.fromisoformat(p["due"])
        gaps.append((due - t).days)
        t = due
    assert gaps == sorted(gaps) and gaps[-1] > gaps[0] * 5, gaps
    p = store.review(cid, "", 1, at=t.isoformat())
    assert dt.datetime.fromisoformat(p["due"]) - t == dt.timedelta(minutes=fsrs.RELEARN_MINUTES)
    assert p["lapses"] == 1


def test_a_replayed_or_late_review_does_not_move_the_card_twice(store):
    sid = store.import_doc(_doc(BASIC[:1]))[0]["set_id"]
    cid = store.get_set(sid)["cards"][0]["id"]
    t = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    first = store.review(cid, "", 3, at=t.isoformat(), client_token="r1")
    assert store.review(cid, "", 3, at=t.isoformat(), client_token="r1") == first
    later = store.review(cid, "", 4, at=(t + dt.timedelta(days=5)).isoformat())
    stale = store.review(cid, "", 1, at=(t + dt.timedelta(days=1)).isoformat())   # offline phone, synced late
    assert stale == later


def test_the_phone_schedules_with_the_same_weights():
    swift = (HERE.parents[2] / "MACalendar-iOS" / "MACalendar-iOS" / "Features" / "Flashcards" / "FSRS.swift")
    if not swift.exists():
        pytest.skip("iOS FSRS not built yet")
    nums = re.search(r"static let w: \[Double\] = \[(.*?)\]", swift.read_text(), re.S).group(1)
    assert tuple(float(x) for x in nums.replace("\n", " ").split(",") if x.strip()) == fsrs.W


# ---------------------------------------------------------------- HTTP

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_FLASHCARDS", str(tmp_path / "api" / "flashcards.db"))
    from assistant.features.flashcards.routes import blueprint
    app = Flask(__name__)
    app.register_blueprint(blueprint)
    return app.test_client()


def test_http_round_trip(client):
    assert b"Card types" in client.get("/flashcards/format").data
    body = yaml.safe_dump(_doc([{"type": "image", "image": "images/x.png", "back": "X"}] + BASIC),
                          allow_unicode=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("set.yaml", body)
        z.writestr("images/x.png", PNG)
    r = client.post("/flashcards/import", data={"file": (io.BytesIO(buf.getvalue()), "s.zip")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.json
    sid = r.json["imported"][0]["set_id"]
    assert client.get(f"/flashcards/media/{sid}/images/x.png").data == PNG
    assert client.get(f"/flashcards/media/{sid}/images/none.png").status_code == 404
    lib = client.get("/flashcards").json["subjects"]
    assert lib[0]["sets"][0]["cards"] == 6
    q = client.post("/flashcards/study", json={"set_ids": [sid], "limit": 0}).json["queue"]
    assert len(q) == 6
    rv = client.post("/flashcards/review", json={"card_id": q[0]["card_id"], "item": q[0]["item"], "grade": 3})
    assert rv.status_code == 200 and rv.json["reps"] == 1
    assert client.post("/flashcards/review", json={"card_id": 999, "grade": 3}).status_code == 404
    bad = client.post("/flashcards/import", json={"doc": _doc([{"type": "basic", "front": "x"}])})
    assert bad.status_code == 400 and "back" in bad.json["error"]
    new = client.post(f"/flashcards/sets/{sid}/cards", json={"type": "typed", "front": "f", "answer": "a"})
    assert new.status_code == 201
    exported = yaml.safe_load(client.get(f"/flashcards/sets/{sid}/export").data)
    assert len(exported["cards"]) == 7
    assert client.post("/flashcards/inbox").status_code == 200


def test_the_feature_is_registered():
    from assistant.features import registry
    f = registry.get("flashcards")
    assert f is not None and f.blueprint() is not None


# ---------------------------------------------------------------- archive / delete

def test_archive_keeps_everything_and_only_flags(store):
    sid = store.import_doc(_doc(BASIC))[0]["set_id"]
    cid = store.get_set(sid)["cards"][0]["id"]
    store.review(cid, "", 3)
    store.set_archived("set", sid, True)
    [sub] = store.library()
    assert sub["sets"][0]["archived"] is True and sub["archived"] is False
    assert store.get_set(sid)["cards"][0]["progress"][""]["reps"] == 1       # nothing lost
    store.set_archived("subject", sub["id"], True)
    assert store.library()[0]["archived"] is True
    store.update_set(sid, archived=False)
    assert store.library()[0]["sets"][0]["archived"] is False
    with pytest.raises(FlashcardError):
        store.set_archived("set", 999, True)


def test_a_delete_is_recorded_and_ids_are_never_reused(store):
    """The phone removes its copy of a set ONLY for a recorded delete. If ids
    were reused, an old record could remove a set made later."""
    a = store.import_doc(_doc(BASIC, set_="A"))[0]["set_id"]
    b = store.import_doc(_doc(BASIC, set_="B"))[0]["set_id"]
    store.delete_set(b)                            # the TOP id — the one SQLite would reuse
    c = store.create_set("Spanish", "C")
    assert c > b
    gone = store.deleted()
    assert [d["id"] for d in gone["sets"]] == [b] and gone["sets"][0]["name"] == "B"
    sub = store.library()[0]["id"]
    store.delete_subject(sub)
    gone = store.deleted()
    assert {d["id"] for d in gone["sets"]} == {a, b, c} and [d["id"] for d in gone["subjects"]] == [sub]
    assert store.subject_id("Spanish") > sub


def test_an_existing_store_gains_archive_in_place(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,"
                      " client_token TEXT UNIQUE, created_at TEXT NOT NULL);"
                      "INSERT INTO subjects(name, created_at) VALUES ('Old', '2026-01-01');")
    old.commit(); old.close()
    s = FlashcardStore(str(path))
    assert s.library()[0]["name"] == "Old" and s.library()[0]["archived"] is False


def test_http_archive_and_deleted(client):
    sid = client.post("/flashcards/import", json={"doc": _doc(BASIC)}).json["imported"][0]["set_id"]
    assert client.patch(f"/flashcards/sets/{sid}", json={"archived": True}).status_code == 200
    lib = client.get("/flashcards").json
    assert lib["subjects"][0]["sets"][0]["archived"] is True and lib["deleted"] == {"sets": [], "subjects": []}
    sub = lib["subjects"][0]["id"]
    assert client.patch(f"/flashcards/subjects/{sub}", json={"archived": True}).status_code == 200
    assert client.get("/flashcards").json["subjects"][0]["archived"] is True
    assert client.get("/flashcards").json["subjects"][0]["name"] == "Spanish"      # archiving did not rename
    assert client.delete(f"/flashcards/sets/{sid}").status_code == 200
    assert [d["id"] for d in client.get("/flashcards").json["deleted"]["sets"]] == [sid]
    assert client.delete(f"/flashcards/sets/{sid}").status_code == 404


def test_naming_an_archived_subject_again_brings_it_back(store):
    sid = store.import_doc(_doc(BASIC))[0]["set_id"]
    sub = store.library()[0]["id"]
    store.set_archived("subject", sub, True)
    store.create_set("Spanish", "New verbs")
    assert store.library()[0]["archived"] is False
    assert store.subject_id("Spanish", create=False) == sub and sid

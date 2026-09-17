"""GET /sync/bootstrap and GET /tags/rules — the two reads the phone's
offline story is built on (DOCUMENTATION/SYNC_PROTOCOL.md).

A cold start used to be five to eight independent GETs run one after another.
Online that is merely wasteful; offline each one sat out its own timeout before
falling back to a cache that had been on disk the whole time, so the app opened
on an empty calendar for tens of seconds. One request means one timeout.

`/tags/rules` exists so the phone can run the Mac's task-tag classifier without
the Mac. The point of serving the table rather than shipping it in the app is
that half of it — the user's own vocabulary labels — could not be shipped: no
list compiled into a binary knows that "Haxaga" is a course.
"""
from __future__ import annotations

import datetime

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api.server import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


# ---------------------------------------------------------------------------
# /sync/bootstrap
# ---------------------------------------------------------------------------

def test_one_request_carries_everything_a_cold_start_needs(client):
    body = client.get("/sync/bootstrap?year=2026&month=9").get_json()
    for key in ("token", "server_time", "window", "events", "todos", "tags",
                "tag_rules", "categories", "holidays", "timers", "counters"):
        assert key in body, f"a cold start still needs a second request for {key}"


def test_the_window_is_the_month_either_side(client):
    """Month, week and day can all reach a neighbouring month without another
    fetch, so the snapshot covers what they can reach."""
    w = client.get("/sync/bootstrap?year=2026&month=9").get_json()["window"]
    assert w == {"start": "2026-08-01", "end": "2026-10-31"}


@pytest.mark.parametrize("year,month,expected", [
    (2026, 12, {"start": "2026-11-01", "end": "2027-01-31"}),   # over new year
    (2026, 1, {"start": "2025-12-01", "end": "2026-02-28"}),    # back over it
    (2026, 2, {"start": "2026-01-01", "end": "2026-03-31"}),
])
def test_the_window_survives_a_year_boundary(client, year, month, expected):
    w = client.get(f"/sync/bootstrap?year={year}&month={month}").get_json()["window"]
    assert w == expected


def test_it_carries_the_holidays_for_that_window(client):
    """The Hebrew calendar was the one part with no cache at all: going offline
    emptied the holidays out of every month view while the Hebrew dates beside
    them — computed on the phone — carried on."""
    body = client.get("/sync/bootstrap?year=2026&month=9").get_json()
    names = {h["name_en"] for h in body["holidays"]}
    assert "Rosh Hashana" in names and "Yom Kippur" in names
    for h in body["holidays"]:
        assert body["window"]["start"] <= h["gregorian_end"]
        assert h["gregorian_erev_start"] <= body["window"]["end"]


def test_the_events_it_carries_are_the_ones_the_month_route_serves(client):
    client.post("/events", json={"title": "Thesis meeting", "date": "2026-09-20",
                                 "start_time": "10:00", "end_time": "11:00"})
    snap = client.get("/sync/bootstrap?year=2026&month=9").get_json()
    month = client.get("/events?year=2026&month=9").get_json()
    assert [e["id"] for e in month] == [e["id"] for e in snap["events"]
                                        if e["date"].startswith("2026-09")]


def test_the_token_is_the_one_the_poll_loop_compares_against(client):
    """The client seeds its `lastToken` from the snapshot, so it must be the
    same string /changes would have answered — otherwise the first poll reads
    as a change and refetches everything it has just been given."""
    snap = client.get("/sync/bootstrap").get_json()
    assert snap["token"] == client.get("/changes").get_json()["token"]


def test_a_nonsense_month_is_refused_not_guessed(client):
    assert client.get("/sync/bootstrap?year=x&month=1").status_code == 400
    assert client.get("/sync/bootstrap?year=2026&month=13").status_code == 400


def test_no_arguments_means_this_month(client):
    today = datetime.date.today()
    w = client.get("/sync/bootstrap").get_json()["window"]
    assert w["start"] <= today.isoformat() <= w["end"]


# ---------------------------------------------------------------------------
# /tags/rules
# ---------------------------------------------------------------------------

def test_the_rules_are_the_classifier_s_own_table(client):
    """Served, not re-typed: a second keyword list in a second language is a
    list that drifts."""
    from assistant.actions.todo import tagging

    rules = client.get("/tags/rules").get_json()
    assert rules["keywords"] == tagging.KEYWORDS
    assert set(rules["never_infer"]) == set(tagging._NEVER_INFER)


def test_the_rules_carry_the_real_palette(client):
    """Only names that exist can be returned, so a tag the user renamed or
    deleted never comes back — the same guarantee `suggest_tags` gives."""
    client.post("/tags", json={"name": "Volunteering"})
    rules = client.get("/tags/rules").get_json()
    assert "Volunteering" in rules["palette"]
    assert set(rules["palette"]) == {r["name"] for r in client.get("/tags").get_json()}


def test_the_revision_moves_when_the_table_does(client):
    before = client.get("/tags/rules").get_json()["rev"]
    client.post("/tags", json={"name": "Volunteering"})
    after = client.get("/tags/rules").get_json()["rev"]
    assert before != after, "a client cannot tell its copy is stale"
    assert client.get("/tags/rules").get_json()["rev"] == after, "rev must be stable"


def test_personal_labels_are_the_half_that_cannot_ship_in_an_app(client, tmp_path,
                                                                 monkeypatch):
    import assistant.stt.vocab as _vocab
    # A scratch store, not the session one: vocab.json is hand-curated and a
    # test writing into it quietly degrades the assistant (CLAUDE.md).
    monkeypatch.setattr(_vocab, "_store", _vocab.VocabStore(str(tmp_path / "vocab.json")))
    _vocab.get_vocab().add_word("Haxaga", label="Coursework")

    rules = client.get("/tags/rules").get_json()
    assert rules["personal_labels"].get("haxaga") == "Coursework"


def test_the_bootstrap_serves_the_same_rules(client):
    """One fetch, one table — the phone must not end up with two revisions of
    it depending on which call it made."""
    assert (client.get("/sync/bootstrap").get_json()["tag_rules"]["rev"]
            == client.get("/tags/rules").get_json()["rev"])


# ---------------------------------------------------------------------------
# The port
#
# `TagClassifier.swift` is `tagging.infer_tag` rewritten in Swift, scoring the
# table above. Swift cannot run here, so what is checked is the next best
# thing: the ALGORITHM, transcribed from the Swift line for line, reading only
# what `/tags/rules` serves, must reach `infer_tag`'s answer. That catches the
# two failures worth catching — a mis-read scoring rule, and a rule added to
# tagging.py that the port has never heard of.
# ---------------------------------------------------------------------------

def _swift_port(title: str, rules: dict) -> "str | None":
    """TagClassifier.tag(for:), in Python. Keep the two in step."""
    def normalise(s: str) -> str:
        blanked = "".join(
            c if (c.isalnum() or c in "_'-" or c.isspace()) else " " for c in s.lower())
        return " " + " ".join(blanked.split()) + " "

    def contains_word(text: str, word: str) -> bool:
        def is_word_char(c: str) -> bool:
            return c.isalnum() or c in "_'-"
        i = 0
        while i + len(word) <= len(text):
            if text[i:i + len(word)] == word:
                before_ok = i == 0 or not is_word_char(text[i - 1])
                after = i + len(word)
                after_ok = after == len(text) or not is_word_char(text[after])
                if before_ok and after_ok:
                    return True
            i += 1
        return False

    def score(text: str, keywords: list) -> float:
        total = 0.0
        for raw in keywords:
            kw = raw.lower()
            if not kw:
                continue
            if " " in kw:
                if f" {kw} " in text:
                    total += 2.0 + 0.2 * len(kw.split(" "))
            elif contains_word(text, kw):
                total += 1.5 if len(kw) > 3 else 1.0
        return total

    trimmed = title.strip()
    if not trimmed:
        return None
    never = {n.lower() for n in rules["never_infer"]}
    allowed_names = [n for n in rules["palette"] if n and n.lower() not in never]
    allowed = {n.lower(): n for n in allowed_names}
    if not allowed:
        return None
    text = normalise(trimmed)

    for word in sorted(rules["personal_labels"], key=len, reverse=True):
        if f" {word} " in text:
            label = rules["personal_labels"][word]
            if label.lower() in allowed:
                return allowed[label.lower()]
            break

    best, best_score = None, 0.0
    for tag, keywords in rules["keywords"].items():
        if tag.lower() not in allowed:
            continue
        s = score(text, keywords)
        if s > best_score:
            best, best_score = allowed[tag.lower()], s

    for name in allowed_names:
        if contains_word(text, name.lower()):
            return name
    return best


@pytest.mark.parametrize("title", [
    "buy milk and eggs",
    "zucchini",
    "Canola oil",
    "gatorade",
    "finish the NLP problem set",
    "pick up a package from the post office",
    "dentist appointment",
    "code review for the sprint",
    "call mum",                       # nothing matches — untagged is the answer
    "",
    "   ",
    "team meeting",                   # "tea" must not fire inside "team"
    "put it on the groceries list",   # names a tag outright
    "Coursework: read chapter 4",
    "buy chicken, rice and olive oil",
    "renew my passport",
    "study for the midterm",
    "personal errand",                # "Personal" is never inferred
])
def test_the_swift_port_reaches_the_same_answer(client, title):
    from assistant.actions.todo.tagging import infer_tag

    rules = client.get("/tags/rules").get_json()
    assert _swift_port(title, rules) == infer_tag(title, rules["palette"])

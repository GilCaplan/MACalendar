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
    assert {"word": "haxaga", "label": "Coursework"} in rules["personal_labels"]


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

    for entry in rules["personal_labels"]:
        if f" {entry['word']} " in text:
            label = entry["label"]
            if label.lower() in allowed:
                return allowed[label.lower()]
            break

    # `order`, not the keywords dict: a tie goes to whichever tag is scored
    # first, and a Swift Dictionary has no order.
    scoring_order = [t for t in rules["order"] if t in rules["keywords"]]
    scoring_order += sorted(t for t in rules["keywords"] if t not in scoring_order)

    best, best_score = None, 0.0
    for tag in scoring_order:
        if tag.lower() not in allowed:
            continue
        s = score(text, rules["keywords"][tag])
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


# ---------------------------------------------------------------------------
# Tie-breaking — the bug the broad comparison found
#
# `infer_tag` keeps the best score with a strict `>`, so a TIE goes to whichever
# tag was scored first: in Python, KEYWORDS' insertion order. That order does
# not survive the trip. Flask sorts JSON keys, and a Swift `Dictionary` has no
# order at all and is not even stable between runs — so the phone broke ties at
# random and disagreed with the Mac on 20 of 10,200 real strings, a different
# twenty each launch. The order now travels with the table.
# ---------------------------------------------------------------------------

def test_the_scoring_order_is_served_explicitly(client):
    from assistant.actions.todo import tagging

    rules = client.get("/tags/rules").get_json()
    assert rules["order"] == list(tagging.KEYWORDS), (
        "the order ties are broken in must travel with the table")
    assert set(rules["order"]) == set(rules["keywords"]), (
        "every scored tag needs a place in the order, and vice versa")


def test_the_served_key_order_is_not_the_python_one(client):
    """The reason `order` has to exist at all — proven, not assumed, so that
    nobody deletes it as redundant."""
    from assistant.actions.todo import tagging

    served = list(client.get("/tags/rules").get_json()["keywords"])
    assert served != list(tagging.KEYWORDS) or len(served) < 2, (
        "if JSON ever preserves the order, this test can go — but check the "
        "Swift side first: a Dictionary there still has none")


def test_a_tie_goes_the_same_way_on_both_sides(client):
    """"buy twelve eggs and book haircut" is Groceries 1.5, Errands 1.5."""
    from assistant.actions.todo.tagging import infer_tag

    rules = client.get("/tags/rules").get_json()
    said = "buy twelve eggs and book haircut the 30th"
    assert infer_tag(said, rules["palette"]) == "Groceries"
    assert _swift_port(said, rules) == "Groceries"


def test_personal_labels_keep_the_order_label_for_uses(client, tmp_path, monkeypatch):
    """Longest word first, so a course called "Modern Computer Vision" wins
    over a "vision" entry rather than depending on dictionary order."""
    import assistant.stt.vocab as _vocab
    monkeypatch.setattr(_vocab, "_store", _vocab.VocabStore(str(tmp_path / "vocab.json")))
    v = _vocab.get_vocab()
    v.add_word("vision", label="Work")
    v.add_word("Modern Computer Vision", label="Coursework")

    rules = client.get("/tags/rules").get_json()
    words = [e["word"] for e in rules["personal_labels"]]
    assert words.index("modern computer vision") < words.index("vision")
    assert _swift_port("finish the Modern Computer Vision pset", rules) == "Coursework"


# ---------------------------------------------------------------------------
# The port, over real strings rather than chosen ones
# ---------------------------------------------------------------------------

def test_the_port_agrees_over_the_real_corpus(client):
    """Eighteen hand-picked titles is a sanity check; this is the test. The
    dataset's 3,000 real utterances are what found the tie-break bug — none of
    the hand-picked ones was a tie."""
    import json
    import pathlib

    from assistant.actions.todo.tagging import infer_tag

    corpus = pathlib.Path("dataset/inputs/history_3000.json")
    if not corpus.exists():
        pytest.skip("the verification corpus is not in this checkout")
    rows = json.loads(corpus.read_text())["rows"]
    client.post("/tags", json={"name": "Volunteering"})   # a custom tag, no keywords
    rules = client.get("/tags/rules").get_json()

    disagreements = []
    tagged = 0
    for row in rows:
        said = row["text"]
        mac = infer_tag(said, rules["palette"])
        if mac:
            tagged += 1
        if _swift_port(said, rules) != mac:
            disagreements.append((said, _swift_port(said, rules), mac))
    assert tagged > 100, "the corpus tagged almost nothing — the test is vacuous"
    assert not disagreements, f"{len(disagreements)} of {len(rows)}: {disagreements[:5]}"

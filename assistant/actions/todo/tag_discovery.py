"""Learn NEW tag classes from the user's own history — with consent.

Gil's design (2026-09-05): the tag registry is a finite class set, but it
should be able to GROW from real usage. When enough untagged tasks share a
theme, the app may ask — once, in a small popup, while the user is actively
using it — "add 'Pharmacy' as a tag?" yes/no.

Politeness is structural, not best-effort:

  • a candidate needs MIN_EVIDENCE distinct untagged tasks behind it, none of
    which the existing classifier could already file;
  • at most one ask per COOLDOWN_DAYS — and fetching a suggestion COSTS the
    cooldown whether or not it is answered, so a glitchy client can never nag;
  • a refused name is recorded and never proposed again;
  • the server never pushes: clients pull `GET /tags/suggestion` only when the
    app is foregrounded, which is what "actively using it" means here.

State lives in a small table inside the calendar DB (so tests inherit the
scratch isolation automatically).
"""
from __future__ import annotations

import datetime
import re
from collections import Counter, defaultdict

MIN_EVIDENCE = 5
COOLDOWN_DAYS = 7

_LAST_ASKED = "__last_asked__"

_STOP = frozenset(
    "the a an my your for with and then also this that from about need to buy "
    "get pick up add put new list today tomorrow week next call text send make "
    "some more please remember don't dont have has was were will would".split())


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z']{3,}", (title or "").lower())
            if w not in _STOP}


def candidate() -> dict | None:
    """The one suggestion worth asking about right now, or None.

    None whenever: the cooldown hasn't elapsed, no theme reaches
    MIN_EVIDENCE, or every qualifying name was already decided."""
    from assistant.actions.todo.tagging import resolve_tags, suggest_tags
    from assistant.db import get_db

    db = get_db()
    asked = db.tag_suggestion(_LAST_ASKED)
    if asked:
        last = datetime.datetime.fromisoformat(asked["ts"])
        if datetime.datetime.now() - last < datetime.timedelta(days=COOLDOWN_DAYS):
            return None
    decided = {r["name"].lower() for r in db.tag_suggestions(exclude=_LAST_ASKED)}
    todos = db.todo_titles_and_tags()

    palette = [r["name"] for r in db.get_tags()]
    counts: Counter = Counter()
    samples: dict = defaultdict(set)
    for r in todos:
        title = r["title"]
        if r["tags"]:
            continue                                # already classified
        if suggest_tags(title, palette):
            continue                                # an existing class covers it
        for w in _words(title):
            samples[w].add(title.strip())
    for w, titles in samples.items():
        counts[w] = len(titles)                     # distinct tasks, not mentions

    for word, n in counts.most_common():
        if n < MIN_EVIDENCE:
            break
        if word in decided:
            continue
        name = word.capitalize()
        if resolve_tags([name], palette):
            continue                                # near-miss of an existing class
        return {"name": name, "evidence": n,
                "samples": sorted(samples[word])[:3]}
    return None


def record_ask() -> None:
    """Stamp the cooldown — called when a suggestion is HANDED OUT, so even an
    unanswered popup counts as this week's one ask."""
    from assistant.db import get_db
    get_db().record_tag_suggestion(_LAST_ASKED, "asked", datetime.datetime.now().isoformat(),
                                   keep_status=True)


def answer(name: str, accept: bool) -> dict | None:
    """Record the verdict. Yes → the class joins the registry (and is returned);
    no → the name is never proposed again."""
    from assistant.db import get_db
    db = get_db()
    db.record_tag_suggestion(name.strip().lower(), "accepted" if accept else "refused",
                             datetime.datetime.now().isoformat())
    if accept:
        return db.create_tag(name.strip())
    return None


def change_answer(name: str, accept: bool) -> dict | None:
    """Reverse or change a past verdict from the history view (Gil,
    2026-09-05): un-refusing creates the class after all; un-accepting removes
    it from the registry again (delete_tag also strips it from todos — the
    same behaviour as deleting it by hand)."""
    from assistant.db import get_db
    db = get_db()
    row = db.tag_suggestion(name.strip().lower())
    was_accepted = bool(row and row["status"] == "accepted")
    if was_accepted and not accept:
        db.delete_tag(name.strip().capitalize())
        db.delete_tag(name.strip())
    return answer(name, accept)


def set_hidden(name: str, hidden: bool) -> None:
    """Hide an entry from the visible history — it stays in the record."""
    from assistant.db import get_db
    get_db().hide_tag_suggestion(name.strip().lower(), hidden)


def history() -> list:
    """Every past suggestion and its verdict, newest first — the reviewable
    record behind the app's history view. Hidden entries are included with
    their flag; the client decides how to fold them away."""
    from assistant.db import get_db
    rows = get_db().tag_suggestions(exclude=_LAST_ASKED)
    return [{"name": r["name"].capitalize(), "status": r["status"],
             "ts": r["ts"], "hidden": bool(r["hidden"])} for r in rows]

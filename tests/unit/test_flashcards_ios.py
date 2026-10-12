"""The phone's Flashcards tab keeps what it has received.

Gil, 2026-10-11: *"once the phone receives and without deleting on either
device it should be there without needing to connect or sync."* Until then
`FlashcardStore.refresh` REPLACED the library with the Mac's answer and, under
"Sets gone from the Mac are gone here too", deleted every cached set the answer
lacked — so a Mac whose store was reset (or a different user's library) wiped
the phone. Now a set leaves the phone only because it was DELETED: here, or on
the Mac, which says so in `GET /flashcards`'s `deleted`.

These read the Swift source, like `test_ios_offline.py`: there is no Swift test
target CI can run, and the rule is about which lines may remove a set.
"""

from __future__ import annotations

import re

from tests.unit._ios_sources import ios_source


def _body(src: str, signature: str) -> str:
    """The brace-matched body of the first declaration containing `signature`."""
    start = src.index(signature)
    open_at = src.index("{", start)
    depth = 0
    for i in range(open_at, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_at:i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def _store() -> str:
    return ios_source("FlashcardStore.swift")


def test_refresh_removes_a_cached_set_only_when_it_is_in_deleted():
    refresh = _body(_store(), "func refresh(api: APIClient) async")
    assert "Sets gone from the Mac are gone here too" not in refresh
    # The only removal in refresh walks the merge's plan...
    removals = re.findall(r"sets\[[^\]]+\]\s*=\s*nil", refresh)
    assert removals == ["sets[id] = nil"], removals
    loop = refresh[:refresh.index("sets[id] = nil")].rsplit("for ", 1)[1]
    assert loop.startswith("id in plan.removeSets"), loop[:60]
    # ...and the plan removes the Mac's `deleted` sets (with those of a deleted
    # subject) plus placeholders whose create was cancelled — nothing else.
    merge = _body(_store(), "static func mergeLibrary(")
    assert "deleted.sets" in merge and "deleted.subjects" in merge
    assert "removeSets: goneSets.union(cancelled)" in merge
    cancelled = merge[merge.index("let cancelled"):merge.index("let sorted")]
    assert "$0 < 0" in cancelled and "pendingTemps" in cancelled, (
        "only a placeholder that never reached the Mac may go without a deletion")


def test_a_set_the_mac_did_not_send_is_kept():
    merge = _body(_store(), "static func mergeLibrary(")
    # cached subjects missing from the answer stay unless deleted
    assert "for local in cached where !sent.contains(local.id) && alive(local.id, gone: goneSubjects)" in merge
    # cached sets missing from the answer are put back unless deleted
    assert "for s in local.sets where !placed.contains(s.id) && alive(s.id, gone: goneSets)" in merge


def test_a_failed_refresh_touches_nothing():
    refresh = _body(_store(), "func refresh(api: APIClient) async")
    fetch = refresh.index("try await api.flashcardLibrary()")
    catch = refresh[fetch:refresh.index("reachedMac = true")]
    assert "return" in catch, "a failed library fetch must stop the refresh"
    assert "subjects =" not in refresh[:refresh.index("reachedMac = true")]
    # A reply the phone cannot decode THROWS rather than reading as empty.
    api = _body(ios_source("FlashcardAPI.swift"), "func flashcardLibrary()")
    assert "try?" not in api and "decode(FlashLibrary.self" in api


def test_archive_is_a_queued_write_and_a_cached_flag():
    api = ios_source("FlashcardAPI.swift")
    for func, path in (("archiveFlashSubject", "/flashcards/subjects/"),
                       ("archiveFlashSet", "/flashcards/sets/")):
        body = _body(api, f"func {func}(")
        assert "mutate(" in body and path in body and '"PATCH"' in body and '"archived"' in body
    models = ios_source("FlashcardModels.swift")
    for struct in ("struct FlashSubject", "struct FlashSetSummary"):
        assert "var archived: Bool" in _body(models, struct), f"{struct} does not keep `archived`"


def test_archived_sets_are_out_of_the_library_and_study():
    view = ios_source("FlashcardsView.swift")
    assert "ForEach(store.activeSubjects)" in view
    assert ".intersection(store.activeSets.map(\\.id))" in view, (
        "an archived set must not stay ticked for study")
    active = _body(_store(), "var activeSubjects: [FlashSubject]")
    assert "!$0.archived" in active


def test_subjects_can_be_renamed_minimised_and_archived_from_the_header():
    view = ios_source("FlashcardsView.swift")
    actions = _body(view, "private func subjectActions(")
    for label in ('"Rename subject…"', '"Archive subject"', '"Delete subject…"'):
        assert label in actions, label
    assert '@AppStorage("flashcards.collapsed")' in view
    header = _body(view, "private func subjectHeader(")
    assert "toggleCollapsed(subject.id)" in header and "countLine(subject)" in header


def test_the_phone_shows_english_folded_on_the_question_and_open_on_the_answer():
    """DEVQA Q91. The phone decodes `en`, folds the question's English behind
    a remembered toggle, shows the answer's straight under the answer, and an
    edit carries back only what still fits the card."""
    models = ios_source("FlashcardModels.swift")
    study = ios_source("FlashcardStudyView.swift")
    fields = set(re.findall(r"var (\w+): (?:String|\[String\])\?", _body(models, "struct FlashEnglish")))
    from assistant.features.flashcards import cardformat
    assert fields == set(cardformat.EN_TEXT) | set(cardformat.EN_LISTS)
    assert "case prompt, steps, labels, ask, tags, page, explain, note, en," in models
    assert 'if let e = en?.body(for: b) { b["en"] = e }' in models
    assert '@AppStorage("flashcardsEnglishOpen")' in study
    # every kind of card offers the question's English, and the self-graded
    # ones show the answer's once revealed
    assert study.count("promptEnglish\n") >= 8
    assert study.count("answerEnglish") >= 6           # five uses and the declaration


def test_the_phone_copies_the_question_and_the_answer():
    """Gil, 2026-10-12: a copy button at the bottom right of both texts."""
    study = ios_source("FlashcardStudyView.swift")
    assert "UIPasteboard.general.string = text" in _body(study, "struct CopyButton")
    assert "CopyButton(text: Self.promptLine(entry))" in _body(study, "private var promptEnglish")
    assert "CopyButton(text: Self.answerLine(entry))" in _body(study, "private var answerEnglish")
    # the row is laid out left-to-right, so "bottom right" stays right on a Hebrew card
    assert ".environment(\\.layoutDirection, .leftToRight)" in _body(study, "private var answerEnglish")
    assert "if picked != nil { answerEnglish }" in study and "if checked { answerEnglish }" in study

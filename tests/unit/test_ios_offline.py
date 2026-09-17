"""Every write survives the Mac being away, or says why it needn't.

The rule, from `assistant/features/CONVENTION.md`: **a write that cannot go out
is queued or it FAILS LOUDLY — never `try?` and a stale cache the next sync
overwrites.**

It was not being followed. `CourseStore.swift` documented "offline writes are
queued in LocalStore.shared.enqueue() and replayed on reconnect" while no
`/courses` or `/assignments` path appeared in a single `enqueue` call site.
`CourseworkView` did `store.removeCourse(id)` then `try? await
api.deleteCourse(id)`, so the failure was swallowed, and the next sync
re-downloaded the course. **Delete a course offline and it came back. Add an
assignment offline and it vanished.**

The queue itself was never the problem — `syncPending` is path-agnostic, remaps
temporary ids, reports 409s and drops 404s. The problem was per-tab folklore
about whether to use it. This test removes the folklore: a mutating call is
queued, or it is listed below with a reason.
"""

from __future__ import annotations

import re

import pytest

from tests.unit._ios_sources import ios_source

#: Methods that genuinely must NOT be replayed later, each with the reason.
#: Adding a name here is a claim that replaying it would be WRONG, not merely
#: inconvenient — keep it short and keep the reason honest.
NOT_QUEUEABLE = {
    # Presence and transport. A stale "I am here" replayed an hour later is
    # worse than none; enrolment must happen against a reachable server or the
    # device simply stays unenrolled and retries.
    "heartbeat", "enrollIfNeeded", "testConnection",
    # Voice has its OWN queue (`LocalStore.enqueueVoice`): recordings are
    # replayed as audio, because the phone cannot understand them — the brain
    # is on the Mac.
    "sendText", "confirmCreate", "sendVoice", "uploadVoice",
    # Operate ON the queue, or ask the Mac to recompute something. Replaying a
    # "retrain now" from an hour ago asks for work nobody is waiting for.
    "retryPending", "retrainLabels", "syncPending", "syncPendingVoice",
    # Carries nothing of the user's: it asks the Mac to read ITS OWN calendar
    # for TODAY and copy what it finds into the task list. Replayed tomorrow it
    # would do a different job from the one asked for, and the count it returns
    # — all the button shows — would be reported to nobody.
    "syncTodosFromCalendar",
    # A POST that WRITES NOTHING ("Returns candidates only — nothing is added",
    # server.py): it mines text for words worth keeping and the user then picks
    # from the answer. `vocabAddWords` is the write, and that one IS queued.
    # Queueing this would park a WhatsApp export in the write queue to produce
    # a list of suggestions for a screen that is no longer open.
    "vocabImport",
    # Answers to a prompt the Mac raised. If it was away when you answered, the
    # prompt itself is stale and will be asked again.
    "answerTagSuggestion", "reviseTagSuggestion", "setTagSuggestionHidden",
    # Feature visibility has its own queueing in FeatureVisibility.set, which
    # also distinguishes a REFUSAL (409) from an unreachable Mac.
    "setFeatureVisible",
}

MUTATING = re.compile(r'request\(\s*"[^"]*"[^)]*?method:\s*"(POST|PATCH|PUT|DELETE)"', re.S)


def _methods(src: str):
    """(name, body) for every function in the file."""
    parts = re.split(r"\n    (?=@discardableResult\n    )?(?:private )?func ", src)
    for part in parts[1:]:
        name = re.match(r"(\w+)", part)
        if name:
            yield name.group(1), part


@pytest.fixture(scope="module")
def client_src():
    return ios_source("APIClient.swift")


def test_every_mutating_call_is_queued_or_declared_unqueueable(client_src):
    offenders = []
    for name, body in _methods(client_src):
        if not MUTATING.search(body):
            continue
        if name in NOT_QUEUEABLE:
            continue
        # Either it queues directly, or it goes through the helper that does.
        if "enqueue(" in body or re.search(r"\bmutate\(", body):
            continue
        paths = re.findall(r'request\(\s*"([^"]*)"', body)
        offenders.append(f"{name}  ({', '.join(sorted(set(paths)))})")
    assert not offenders, (
        "these writes are lost when the Mac is away — queue them, or add them "
        "to NOT_QUEUEABLE with a reason:\n  " + "\n  ".join(sorted(offenders)))


def test_the_coursework_paths_are_actually_queued(client_src):
    """The specific bug: /courses and /assignments appeared in no enqueue call
    site at all, while CourseStore's own comment claimed otherwise."""
    for path in ("/courses", "/assignments"):
        assert re.search(rf'(enqueue|mutate)\([^)]*"{path}', client_src) or \
               re.search(rf'"{path}[^"]*",\s*method:', client_src), path


def test_course_store_no_longer_claims_something_it_does_not_do(client_src):
    """A doc comment that lies is worse than no comment: it is what stopped
    anyone checking."""
    store = ios_source("CourseStore.swift")
    if "enqueue" in store:
        # If it still makes the claim, the claim must now be TRUE — i.e. the
        # client really does queue those paths.
        assert re.search(r'(enqueue|mutate)\([^)]*"/courses', client_src), (
            "CourseStore still promises offline queueing that APIClient does "
            "not provide for /courses")


def test_temp_ids_are_remapped_for_every_store_that_mints_them(client_src):
    """`remapTemporaryID` rewrote queued paths and the todos/events arrays, but
    CourseStore mints its own negative ids (`nextTemp`). A course created
    offline and then edited would replay the edit against a placeholder id the
    Mac never issued."""
    store = ios_source("LocalStore.swift")
    remap = re.search(r"func remapTemporaryID.*?\n    \}", store, re.S)
    assert remap, "remapTemporaryID not found"
    body = remap.group(0)
    course_store = ios_source("CourseStore.swift")
    if "nextTemp" in course_store:
        assert "CourseStore" in body or "remapTemporaryID" in course_store, (
            "CourseStore mints temporary ids that nothing remaps on reconnect")


# ---------------------------------------------------------------------------
# The other half: a replayed create must not become a second row
# ---------------------------------------------------------------------------

def test_creates_carry_an_idempotency_token(client_src):
    """Queueing a create is only half the job.

    Replay is AT-LEAST-ONCE: a create that reaches the Mac and commits but
    loses its reply stays queued and goes out again. Without a token the Mac
    cannot tell the replay from a new request, and inserts a duplicate — the
    32 "buy groceries" rows of 2026-09-04..06. The server half is
    `assistant/features/idempotency.py`; this is the client half.
    """
    for func in ("createCourse", "createAssignment", "createTimer", "createCounter"):
        body = next((b for n, b in _methods(client_src) if n == func), None)
        assert body, f"{func} not found"
        assert "client_token" in body, (
            f"{func} queues its create but mints no client_token — a replayed "
            f"create will land a second row")


def test_the_token_is_minted_once_per_create(client_src):
    """One token per thing the USER asked to create, reused on every attempt.
    Minting inside the retry path instead would defeat the whole mechanism:
    each replay would look like a different request."""
    for func in ("createCourse", "createAssignment"):
        body = next(b for n, b in _methods(client_src) if n == func)
        # The token belongs to the body built ONCE at the top, which both the
        # live request and the enqueued copy then share.
        head = body.split("do {")[0]
        assert "client_token" in head, (
            f"{func} mints its token after the request begins — the queued "
            f"copy would carry a different one")


# ---------------------------------------------------------------------------
# Reads need a cache, or a queued write has nothing to show for itself
# ---------------------------------------------------------------------------

#: Reads that legitimately have no offline answer: they ask the Mac to think,
#: or to report something only it knows.
NO_CACHE_NEEDED = {
    "health", "changes", "features",        # liveness and server-side state
    "judeStatus", "judeChats", "judeHistory", "judeAsk",   # Jude needs the Mac
    "vocabOnboarding", "vocabPreview", "tagSuggestion",    # computed on demand
    "unreviewedCount", "unreviewed", "memoryDetail",
    "digest", "observance", "holidays", "timerSessions", "counterPresses",
    "labelNext", "workoutStats", "searchAll", "devices",
}

READING = re.compile(r'request\(\s*"([^"]*)"(?![^)]*method:\s*"(?:POST|PATCH|PUT|DELETE)")')


def test_every_cached_surface_reads_from_the_cache_when_offline(client_src):
    """A queued write is only half of working offline.

    `timers()` and `counters()` were the only reads in the app with no
    fallback, so away from the Mac the Timer tab drew nothing and `load()` set
    "Couldn't reach the Mac". Tapping ＋ then queued the press correctly while
    the screen showed no count to increment — which reads as a broken button,
    and is what it was reported as.
    """
    for func in ("timers", "counters", "todos", "courses", "allAssignments"):
        body = next((b for n, b in _methods(client_src) if n == func), None)
        if body is None:
            continue
        cached = "LocalStore" in body or "CourseStore" in body
        assert "APIError.offline" in body and cached, (
            f"{func} has no offline fallback — its surface is empty away from "
            f"the Mac, and any optimistic write has nothing to apply to")


def test_a_counter_press_updates_the_cache_before_it_goes_out(client_src):
    """Optimistic FIRST, network second — otherwise ＋ does nothing until a
    round trip completes, and nothing at all when there is no round trip."""
    body = next(b for n, b in _methods(client_src) if n == "pressCounter")
    bump = body.index("bumpCounter")
    send = body.index("mutateOrTell")
    assert bump < send, (
        "pressCounter contacts the Mac before updating the local count — "
        "offline the tap would appear to do nothing")

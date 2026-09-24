"""Who gets the model next, and whose words may be spoken in one breath.

Gil, 2026-09-10: *"same application requests can concatenate … if from different
applications then we queue according to the protocol … each device is its own
unique requests; two different iphones or my laptop that send requests should be
queued; the same device can merge if we choose."*

Both halves are tested here because they are one rule: **identity decides
whether you merge or queue.**

The lock half is tested ACROSS PROCESSES, with real subprocesses, because that
is the only thing being claimed — a `threading.Lock` would pass any in-process
test and protect nothing, since the contenders are the API, the GUI, a board and
a test, each in its own interpreter.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import textwrap
import time

import pytest

from assistant import model_protocol as mp

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Identity — the half that decides merge vs queue
# ---------------------------------------------------------------------------

def test_two_different_iphones_are_two_streams():
    """THE DEFECT THIS EXISTS FOR. `source` is "ios" for every iPhone on the
    tailnet, and the pending flush grouped on it — so two people's queued
    commands were concatenated into one utterance and parsed as one person's."""
    assert not mp.may_merge(("ios", "phone-A"), ("ios", "phone-B"))
    assert mp.stream_key("ios", "phone-A") != mp.stream_key("ios", "phone-B")


def test_the_same_iphone_is_one_stream_and_may_merge():
    """The other half of the rule: one device's queued commands are one
    person's backlog and coalescing them into one parse is the point."""
    assert mp.may_merge(("ios", "phone-A"), ("ios", "phone-A"))


def test_a_laptop_never_merges_with_a_phone():
    assert not mp.may_merge(("mac", "book-1"), ("ios", "phone-A"))


def test_a_test_sandbox_never_merges_with_real_traffic():
    """Not hygiene — a correctness rule with a measured cost. A test's words
    inside the user's batch EXECUTE as the user's command, and the whole batch
    is then attributed to one source, defeating `weekly_review.py`'s
    test-traffic filter. That filter had been inflating real-usage accuracy to
    83%."""
    assert not mp.may_merge(("test", "phone-A"), ("ios", "phone-A"))
    assert not mp.may_merge(("test", ""), ("ios", ""))


def test_a_client_that_sends_no_id_gets_its_own_anonymous_stream():
    """ISOLATE BY DEFAULT, and this is the fix for "two test sandboxes were one
    entity". An unlabelled caller used to key on the bare source string, so
    every `test` process shared one stream and their commands were concatenated.
    Now each falls back to the PROCESS asking — unique per process, stable
    within it — so two sandboxes are two entities with no coordination at all.
    """
    assert mp.stream_key("ios", "").startswith("ios:anon:")
    assert mp.stream_key("ios", None).startswith("ios:anon:")
    # A caller that knows something about the peer can say so; two unlabelled
    # clients on different machines then stay distinct.
    assert mp.stream_key("test", "", anon="host-1") != mp.stream_key("test", "", anon="host-2")
    # …and a Mac still never merges with a phone.
    assert not mp.may_merge(("mac", ""), ("ios", ""))


def test_an_unverified_claim_never_reaches_the_real_devices_stream():
    """THE SECURITY PROPERTY, and it is structural rather than a check.

    An imposter presenting the exact id of an enrolled device must not land in
    that device's stream. It gets a separate namespace, so spoofing buys an
    isolated queue of its own and the real phone's backlog is untouched.
    """
    did = "ios-1eec2744018f405e"
    real = mp.stream_key("ios", did, trusted=True)
    fake = mp.stream_key("ios", did, trusted=False)
    assert real != fake
    assert real == f"ios:{did}"
    assert fake.startswith("ios:untrusted:")
    # The claimed id is HASHED, never reflected verbatim into a group key.
    assert did not in fake


def test_two_different_imposters_do_not_merge_with_each_other_either():
    a = mp.stream_key("ios", "ios-aaaa", trusted=False)
    b = mp.stream_key("ios", "ios-bbbb", trusted=False)
    assert a != b


def test_identity_is_not_confused_by_case_or_padding():
    assert mp.stream_key(" IOS ", " phone-A ") == mp.stream_key("ios", "phone-A")


# ---------------------------------------------------------------------------
# The gate — across real processes
# ---------------------------------------------------------------------------

def _holder_script(lock: pathlib.Path, seconds: float) -> str:
    return textwrap.dedent(f"""
        import os, sys, time
        os.environ["MACALENDAR_MODEL_LOCK"] = {str(lock)!r}
        os.environ["MACALENDAR_LLM_PRIORITY"] = "background"
        sys.path.insert(0, {str(ROOT)!r})
        from assistant import model_protocol as mp
        with mp.hold():
            print("HELD", flush=True)
            time.sleep({seconds})
    """)


def _spawn_holder(lock, seconds):
    proc = subprocess.Popen([sys.executable, "-c", _holder_script(lock, seconds)],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "HELD"   # it really has the lock
    return proc


@pytest.fixture
def lock(tmp_path, monkeypatch):
    path = tmp_path / "model.lock"
    monkeypatch.setattr(mp, "LOCK_PATH", path)
    # A live call in one test must not hold a background call in the next for
    # the full 20 s quiet window (the tests of that window set their own).
    monkeypatch.setattr(mp, "LIVE_QUIET_S", 0.2)
    return path


def test_the_lock_actually_excludes_another_process(lock):
    """The claim under test. A background caller must WAIT while another
    process holds it — not sail through, which is what an in-process lock would
    do here and what no in-process test would catch."""
    proc = _spawn_holder(lock, 1.0)
    try:
        t0 = time.monotonic()
        with mp.hold(mp.BACKGROUND) as waited:
            waited_s = time.monotonic() - t0
        assert waited_s > 0.4, "a background caller sailed past a held lock"
        assert waited > 400
    finally:
        proc.wait(timeout=10)


def test_live_traffic_is_never_made_to_wait_for_a_board(lock):
    """THE ASYMMETRY, and the reason this is a yield signal rather than a mutex.

    A user's voice command must not queue behind a research board. It tries
    briefly, then goes anyway — worst case it degrades to the behaviour before
    this module existed, which is a slow command, never a failed one.
    """
    proc = _spawn_holder(lock, 3.0)
    try:
        t0 = time.monotonic()
        with mp.hold(mp.LIVE):
            pass
        assert time.monotonic() - t0 < 1.0, "live traffic blocked behind background"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_a_killed_holder_releases_the_lock(lock):
    """THE PROPERTY THAT CHOSE `flock`.

    A board that crashes or is `kill -9`'d must not wedge the assistant
    forever. The kernel drops a flock when the holder dies, so no stale-lock
    reaper is needed — and a reaper would be a second bug waiting to happen.
    """
    proc = _spawn_holder(lock, 60.0)
    proc.kill()
    proc.wait(timeout=10)
    t0 = time.monotonic()
    with mp.hold(mp.BACKGROUND):
        pass
    assert time.monotonic() - t0 < 1.0, "the lock outlived the process holding it"


def test_the_gate_never_raises_when_it_cannot_lock(tmp_path, monkeypatch):
    """A command must not fail because its traffic warden could not start.
    Every failure path falls through to running the call."""
    monkeypatch.setattr(mp, "LOCK_PATH", tmp_path / "no" / "such" / "dir" / "x.lock")
    monkeypatch.setattr(mp, "_open_lock", lambda: None)
    with mp.hold() as waited:
        assert waited >= 0


def test_two_background_callers_serialise(lock):
    """The point of the gate: two boards do not both hammer the model."""
    proc = _spawn_holder(lock, 0.8)
    try:
        t0 = time.monotonic()
        with mp.hold(mp.BACKGROUND):
            held_at = time.monotonic()
        assert held_at - t0 > 0.3
    finally:
        proc.wait(timeout=10)


def test_priority_defaults_to_live(monkeypatch):
    """Forgetting to declare yourself makes you the USER, so the failure mode of
    forgetting is "a board is ruder than it should be", never "a voice command
    waits behind a board"."""
    monkeypatch.delenv("MACALENDAR_LLM_PRIORITY", raising=False)
    assert mp.priority() == mp.LIVE
    monkeypatch.setenv("MACALENDAR_LLM_PRIORITY", "background")
    assert mp.priority() == mp.BACKGROUND
    monkeypatch.setenv("MACALENDAR_LLM_PRIORITY", "nonsense")
    assert mp.priority() == mp.LIVE


# ---------------------------------------------------------------------------
# The hole this whole design can develop
# ---------------------------------------------------------------------------

def test_every_door_to_the_model_goes_through_the_gate():
    """A GATE WITH A KNOWN HOLE IS WORSE THAN NO GATE — it invites the
    assumption of coverage.

    `llmseg.py` is why this test exists: it talks to ollama through its own
    `urllib` socket rather than through `IntentParser`, so a gate placed only in
    the parser would have missed it silently. This finds the fourth door the
    same way, by reading the tree rather than by remembering.

    It looks for CALL SITES, not for the string "/api/chat" — llmseg's call
    names a constant, so a literal search finds the constant's definition (which
    needs no gate) and misses the request (which does). The first cut of this
    test did exactly that and would have passed with the real door open.
    """
    CALL = re.compile(r"\.post\(|urlopen\(")
    OLLAMA = re.compile(r"base_url|ENDPOINT|11434")
    #: `/api/tags` is a reachability probe — no tokens, no queue. Only calls
    #: that GENERATE or LOAD hold up the model, and only those are gated.
    PROBE = re.compile(r"/api/tags")

    missed = []
    for path in sorted((ROOT / "assistant").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        if "/experiments/" in rel or "/datasets/" in rel:
            continue
        if path.name == "model_protocol.py":
            continue                       # the gate itself, and its prose
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if not CALL.search(line):
                continue
            args = "\n".join(lines[i:i + 4])       # the URL may be on this line
            if not OLLAMA.search(args) or PROBE.search(args):
                continue
            window = "\n".join(lines[max(0, i - 14):i + 4])
            if "model_protocol.hold()" not in window:
                missed.append(f"{rel}:{i + 1}  {line.strip()[:64]}")
    assert not missed, (
        "these reach the model outside the gate:\n  " + "\n  ".join(missed))


def test_the_pin_would_actually_catch_an_ungated_door(tmp_path):
    """The pin above is only worth having if it FAILS on a real hole. A check
    that cannot fail is decoration, and this project has shipped one of those
    before (a UI test that never sent a mouse event)."""
    CALL = re.compile(r"\.post\(|urlopen\(")
    OLLAMA = re.compile(r"base_url|ENDPOINT|11434")
    ungated = 'resp = session.post(f"{conf.base_url}/api/chat", json=payload)'
    assert CALL.search(ungated) and OLLAMA.search(ungated)
    assert "model_protocol.hold()" not in ungated


def test_every_board_declares_itself_background():
    """THE WAY THIS MECHANISM QUIETLY STOPS WORKING.

    The gate only arbitrates between callers that PARTICIPATE. `priority()`
    defaults to live — deliberately, so that forgetting makes a board rude
    rather than making a voice command wait — which means a new experiment that
    forgets is invisible: every test passes, the board runs fine, and the user's
    phone is just mysteriously slow while it does.

    So the rule is checked by reading the tree. Anything that sets up a scratch
    environment to drive the engine is BACKGROUND, and must say so before it
    imports anything from `assistant` (the value is read at call time, but the
    env block is where every other override already lives and splitting them is
    how one of them gets missed).
    """
    live_by_design = {
        # These ARE the assistant. They set MACALENDAR_NO_WARMUP for the
        # opposite reason — not to be polite, but because a warm-up thread
        # racing a model load segfaults the interpreter.
        "assistant/notifier.py",
        "assistant/api/server.py",
        "assistant/engine/__init__.py",
        # `assistant-cli endpoints` builds the app to list its routes — it
        # WANTS ROUTES, NOT MODELS, which is the same reason the three above
        # set the flag. It makes no model call at all, so there is nothing for
        # it to yield; and where the CLI does drive the engine (`cli say`) it
        # is a person at a terminal waiting for an answer, which is live by
        # the same rule that makes a phone live.
        "assistant/cli.py",
    }
    missed = []
    for base in ("assistant", "scripts"):
        for path in sorted((ROOT / base).rglob("*.py")):
            rel = str(path.relative_to(ROOT))
            if rel in live_by_design:
                continue
            text = path.read_text()
            if "MACALENDAR_NO_WARMUP" not in text:
                continue
            if "MACALENDAR_LLM_PRIORITY" not in text:
                missed.append(rel)
    assert not missed, (
        "these drive the engine without yielding the model to the live "
        "assistant:\n  " + "\n  ".join(missed))


def test_a_board_that_declares_background_actually_gets_it(lock, monkeypatch):
    """The declaration has to reach `priority()`, not just sit in a file."""
    monkeypatch.setenv("MACALENDAR_LLM_PRIORITY", "background")
    assert mp.priority() == mp.BACKGROUND
    proc = _spawn_holder(lock, 0.6)
    try:
        t0 = time.monotonic()
        with mp.hold():                    # no explicit kind: reads the env
            waited = time.monotonic() - t0
        assert waited > 0.2, "declared background but did not yield"
    finally:
        proc.wait(timeout=10)


def _looping_holder_script(lock: pathlib.Path, rounds: int, work: float) -> str:
    """A board in a TIGHT LOOP — acquire, work, release, acquire again. This is
    what a real experiment does, and it is the shape that starves a peer."""
    return textwrap.dedent(f"""
        import os, sys, time
        os.environ["MACALENDAR_MODEL_LOCK"] = {str(lock)!r}
        os.environ["MACALENDAR_LLM_PRIORITY"] = "background"
        sys.path.insert(0, {str(ROOT)!r})
        from assistant import model_protocol as mp
        print("HELD", flush=True)
        for _ in range({rounds}):
            with mp.hold():
                time.sleep({work})
    """)


def test_a_board_in_a_tight_loop_does_not_starve_another_board(lock):
    """FOUND BY A LIVE DEMO, NOT BY A TEST — which is why it is a test now.

    `flock` has no fairness and this poller has no queue, so a board that
    re-acquires the instant it releases never lets a peer in. Measured against
    real ollama before the fix: background caller #2 waited the FULL 120s bound
    and then barged — two boards hammering the model, the exact thing the gate
    exists to prevent. Live traffic was unaffected (it waits 50ms and goes), so
    every unit test passed.

    The fix is a yield gap after a background release. This pins that a second
    background caller gets in within ROUGHLY ONE unit of work, not at the
    timeout bound.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", _looping_holder_script(lock, rounds=12, work=0.25)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "HELD"
        time.sleep(0.3)                      # let it get into its rhythm
        t0 = time.monotonic()
        with mp.hold(mp.BACKGROUND):
            waited = time.monotonic() - t0
        assert waited < 1.5, (
            f"starved for {waited:.1f}s — a peer board cannot get the gate")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_live_still_never_waits_while_a_board_loops(lock):
    """The starvation fix must not have been bought with live latency."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _looping_holder_script(lock, rounds=12, work=0.25)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "HELD"
        time.sleep(0.3)
        worst = 0.0
        for _ in range(4):
            t0 = time.monotonic()
            with mp.hold(mp.LIVE):
                worst = max(worst, time.monotonic() - t0)
        assert worst < 0.5, f"live waited {worst:.2f}s behind a board"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# Enrolment: a name the SERVER issued, not one the caller asserted
# ---------------------------------------------------------------------------

@pytest.fixture
def enrolment(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SECRET_PATH", tmp_path / "device_secret")
    monkeypatch.setattr(mp, "REGISTRY_PATH", tmp_path / "devices.json")
    return tmp_path


def test_an_enrolled_device_gets_a_name_and_a_token(enrolment):
    got = mp.enroll("ios", "Gil's iPhone")
    assert got["device_id"].startswith("ios-")
    assert mp.verify("ios", got["device_id"], got["token"])
    # The LABEL is the point of enrolling rather than self-naming: a UUID in a
    # log tells a reader nothing about whose command it was.
    assert mp.devices()[got["device_id"]]["label"] == "Gil's iPhone"


def test_the_server_chooses_the_id_so_two_devices_cannot_collide(enrolment):
    """Self-chosen ids can collide by accident and be chosen on purpose. These
    are issued."""
    ids = {mp.enroll("ios", f"phone {i}")["device_id"] for i in range(50)}
    assert len(ids) == 50


def test_a_forged_token_does_not_verify(enrolment):
    got = mp.enroll("ios", "phone")
    assert not mp.verify("ios", got["device_id"], "deadbeef")
    assert not mp.verify("ios", got["device_id"], "")
    # Flip the last hex digit to a DIFFERENT one. Appending a fixed "0" was
    # wrong once every sixteen runs — whenever the real token already ended in
    # "0" the "forgery" was the genuine token, and the test failed for being
    # right. A flaky assertion is worse than no assertion: it teaches you to
    # re-run the suite instead of reading it.
    flipped = got["token"][:-1] + ("1" if got["token"][-1] != "1" else "2")
    assert flipped != got["token"]
    assert not mp.verify("ios", got["device_id"], flipped)


def test_a_token_cannot_be_replayed_under_a_different_source(enrolment):
    """The source is INSIDE the signature, not merely beside it — so a phone's
    token cannot be presented by something claiming to be the Mac, which would
    otherwise be a free identity upgrade into a different trust bucket."""
    got = mp.enroll("ios", "phone")
    assert mp.verify("ios", got["device_id"], got["token"])
    assert not mp.verify("mac", got["device_id"], got["token"])


def test_an_id_the_server_never_issued_is_not_trusted(enrolment):
    """Even a well-formed id has no claim on a stream without a token the
    server minted."""
    mp.enroll("ios", "phone")                     # a real one exists
    assert not mp.verify("ios", "ios-0000000000000000", mp.token_for("ios", "ios-0000000000000000"))


def test_a_revoked_device_stops_verifying_but_is_not_cut_off(enrolment):
    """Revocation ISOLATES rather than blocks. A stolen token keeps working as
    its own quarantined stream and can never rejoin the real one — which is why
    revoking does not have to be raced against the thief, and why a revoked
    device does not silently start executing into somebody else's queue."""
    got = mp.enroll("ios", "phone")
    assert mp.revoke(got["device_id"])
    assert not mp.verify("ios", got["device_id"], got["token"])
    trusted_key = mp.stream_key("ios", got["device_id"], trusted=True)
    now_key = mp.stream_key("ios", got["device_id"], trusted=False)
    assert now_key != trusted_key


def test_revoking_one_device_leaves_the_others_alone(enrolment):
    a = mp.enroll("ios", "phone A")
    b = mp.enroll("ios", "phone B")
    mp.revoke(a["device_id"])
    assert not mp.verify("ios", a["device_id"], a["token"])
    assert mp.verify("ios", b["device_id"], b["token"])


def test_the_secret_is_created_private(enrolment):
    """A key that was ever world-readable is not a key. It is opened 0600
    BEFORE the bytes go in, rather than chmod-ed afterwards."""
    mp.enroll("ios", "phone")
    assert mp.SECRET_PATH.exists()
    assert (mp.SECRET_PATH.stat().st_mode & 0o777) == 0o600
    assert len(mp.SECRET_PATH.read_bytes()) >= 32


def test_the_secret_is_stable_across_calls(enrolment):
    """A key regenerated per call would fail every existing token and look
    exactly like an attack."""
    got = mp.enroll("ios", "phone")
    for _ in range(5):
        assert mp.verify("ios", got["device_id"], got["token"])


def test_with_no_secret_nothing_is_trusted_rather_than_everything(enrolment,
                                                                  monkeypatch):
    """The failure direction matters. Losing the key must ISOLATE every device,
    never trust every device."""
    monkeypatch.setattr(mp, "_secret", lambda: b"")
    assert mp.token_for("ios", "ios-abc") == ""
    assert not mp.verify("ios", "ios-abc", "anything")


def test_the_registry_survives_a_half_written_file(enrolment):
    """It is written to a temp file and renamed, so a crash mid-write leaves
    the old registry rather than a truncated one."""
    got = mp.enroll("ios", "phone")
    mp.REGISTRY_PATH.write_text("{ this is not json")
    assert mp.devices() == {}                 # unreadable reads as empty…
    assert not mp.verify("ios", got["device_id"], got["token"])   # …so: untrusted


# ---------------------------------------------------------------------------
# A person waiting beats a sandbox — at the MODEL, not just in the queue
# ---------------------------------------------------------------------------

def test_a_test_request_inside_a_live_process_yields_to_a_real_device(monkeypatch):
    """THE HOLE THE ENV VAR COULD NOT CLOSE.

    `MACALENDAR_LLM_PRIORITY` describes a PROCESS, and the API server is one
    process serving the phone, the Mac and any test curl. So a
    `source: "test"` command got LIVE priority purely by arriving at a live
    process, and could sit in front of a real device's command at the model.

    The env is forced LIVE here because `conftest.py` marks the whole suite
    BACKGROUND — which is right for a test run and would hide the very hole
    this test is about.
    """
    monkeypatch.delenv("MACALENDAR_LLM_PRIORITY", raising=False)
    assert mp.priority() == mp.LIVE                    # this process is live
    with mp.serving("test"):
        assert mp.priority() == mp.BACKGROUND
    with mp.serving("ios"):
        assert mp.priority() == mp.LIVE
    assert mp.priority() == mp.LIVE                    # and it is restored


def test_a_request_marking_beats_the_process_env_in_both_directions(monkeypatch):
    """A board that happens to serve a real device's request should treat it as
    live, and a live server handling a test should treat it as background. The
    per-request mark is the more specific fact, so it wins either way."""
    monkeypatch.setenv("MACALENDAR_LLM_PRIORITY", "background")
    assert mp.priority() == mp.BACKGROUND
    with mp.serving("ios"):
        assert mp.priority() == mp.LIVE


def test_an_unverified_real_device_is_still_a_person_waiting():
    """Trust decides who you are GROUPED with; source decides whether someone
    is WAITING. An old iOS app that sends no device id cannot merge with the
    enrolled phone — but demoting it to background would punish the user for
    the app being out of date."""
    assert mp.priority_for("ios") == mp.LIVE
    assert mp.priority_for("mac") == mp.LIVE
    assert mp.priority_for("test") == mp.BACKGROUND
    assert mp.priority_for("") == mp.BACKGROUND


def test_a_real_device_takes_the_gate_from_a_test_request(lock):
    """End to end at the gate: a test request behaves like a board — it queues
    and yields — while a real device's request goes straight through."""
    proc = _spawn_holder(lock, 2.0)
    try:
        t0 = time.monotonic()
        with mp.serving("ios"), mp.hold():
            live_wait = time.monotonic() - t0
        assert live_wait < 0.5, "a real device queued behind a board"

        t0 = time.monotonic()
        with mp.serving("test"), mp.hold():
            test_wait = time.monotonic() - t0
        assert test_wait > live_wait, "a test request did not yield"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_the_priority_of_one_request_cannot_leak_into_another():
    """Flask serves each request on its own thread. A global would let a test
    request's priority be read by a phone's request running beside it."""
    import threading
    seen = {}

    def _worker():
        with mp.serving("ios"):
            time.sleep(0.05)
            seen["worker"] = mp.priority()

    t = threading.Thread(target=_worker)
    with mp.serving("test"):
        t.start()
        t.join()
        seen["main"] = mp.priority()
    assert seen == {"worker": mp.LIVE, "main": mp.BACKGROUND}


def test_a_secret_whose_bytes_look_like_whitespace_is_not_regenerated(enrolment):
    """THE 4.61% BUG, pinned.

    The key is RANDOM BYTES. `.strip()` eats six of 256 byte values at either
    end, so 4.61% of 32-byte keys read back short, failed the length check, and
    were silently REPLACED — invalidating every device token at once, about one
    start in twenty. It surfaced as a flaky test (revoking one device
    intermittently un-verified the other) and in production would look like
    every device being logged out for no reason.

    Bytes are not text. This forces the worst case explicitly rather than
    waiting for randomness to find it again.
    """
    mp.SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    # whitespace at BOTH ends, and inside
    hostile = b"\n\t " + b"k" * 26 + b" \r\n"
    assert len(hostile) >= 32
    mp.SECRET_PATH.write_bytes(hostile)

    got = mp.enroll("ios", "phone")
    assert mp.SECRET_PATH.read_bytes() == hostile, "the key was rewritten"
    for _ in range(10):
        assert mp.verify("ios", got["device_id"], got["token"])


def test_every_freshly_generated_secret_survives_a_round_trip(enrolment):
    """The same property, from the generation side: whatever `_secret()`
    creates must read back identical, whatever bytes randomness picked."""
    for i in range(200):
        mp.SECRET_PATH.unlink(missing_ok=True)
        first = mp._secret()
        assert len(first) >= 32
        assert mp._secret() == first, f"secret changed on re-read (iteration {i})"


def test_background_stands_aside_while_live_traffic_is_recent(lock, monkeypatch):
    """Gil's six-ask command (2026-09-24) spent 39 s of 48.9 s in one model
    call behind a running board: the lock let live go after 50 ms, but the
    board re-took the MODEL the instant each call ended. Background now waits
    for the live-quiet window before starting a call."""
    import time as _t
    from assistant import model_protocol as mp
    monkeypatch.setattr(mp, "LIVE_QUIET_S", 0.4)
    mp.note_live()
    t0 = _t.monotonic()
    with mp.hold(mp.BACKGROUND):
        waited = _t.monotonic() - t0
    assert 0.3 <= waited < 2.0, waited


def test_live_never_waits_for_the_quiet_window(lock, monkeypatch):
    import time as _t
    from assistant import model_protocol as mp
    monkeypatch.setattr(mp, "LIVE_QUIET_S", 5.0)
    mp.note_live()
    t0 = _t.monotonic()
    with mp.hold(mp.LIVE):
        pass
    assert _t.monotonic() - t0 < 0.5


def test_the_quiet_window_is_bounded_for_a_board(lock, monkeypatch):
    import time as _t
    from assistant import model_protocol as mp
    monkeypatch.setattr(mp, "LIVE_QUIET_S", 60.0)
    monkeypatch.setattr(mp, "BACKGROUND_WAIT_S", 0.3)
    mp.note_live()
    t0 = _t.monotonic()
    with mp.hold(mp.BACKGROUND):
        pass
    assert _t.monotonic() - t0 < 1.5          # never hangs past its own bound

"""Who gets the model next, and whose words may be spoken in one breath.

    stream_key(source, device)       the identity a request belongs to
    may_merge(a, b)                  same device only — never across devices
    hold()                           the cross-process gate around one call
    priority()                       "live" | "background"

Four processes on this Mac share ONE ollama, and so does every phone on the
tailnet. Until 2026-09-10 nothing arbitrated that: every caller did a bare
blocking `POST /api/chat` and whoever arrived first won. Measured while a
research board was running, a trivial five-token call took **2.0s, then 42.5s,
then 43.9s** — none of it inference, all of it queue.

## The two halves are the same rule seen from two sides

Gil, 2026-09-10: *"same application requests can concatenate … if from different
applications then we queue according to the protocol … each device is its own
unique request stream. two different iphones or my laptop that send requests
should be queued; the same device can merge if we choose or queued."*

    SAME device      MAY MERGE      ("buy milk")and("call Sam")   one parse
    OTHER device     NEVER MERGE    queue, and arbitrate here

So one module answers both questions, because getting them from two places is
how they drift apart.

## `source` IS NOT AN IDENTITY, and that was a live defect

`EngineState.source` is `"mac" | "ios" | "test"` — a CATEGORY. The pending queue
grouped on it (`by_source.setdefault(row["source"] or "ios", …)`), so **two
different iPhones both reported `ios` and their queued commands were
concatenated into one utterance.** Gil's rule says they are different streams and
must queue.

`stream_key` is therefore `source:device`, and the device half comes from the
client because only the client knows which phone it is. A client that sends none
falls back to its source, which keeps old clients working and still stops a Mac
merging with a phone — it merely cannot tell two silent phones apart, which is
strictly better than today and is visible rather than assumed.

## Why the gate is a FILE LOCK, and specifically `flock`

The contenders are separate PROCESSES — the API, the GUI, a test, a board — so a
`threading.Lock` cannot see them. Of the cross-process options, `flock` is chosen
for one property that decides it:

**the kernel releases it when the holder dies.** A board that crashes or is
`kill -9`'d must not wedge the assistant forever. A lock directory or a PID file
would need a stale-lock reaper, and a reaper is a second bug waiting to happen.

## The asymmetry IS the design

    live        try for ~50ms, then GO ANYWAY
    background  block for it, and release between EVERY call

Live never *fails* on the lock — worst case it degrades to exactly the old
behaviour. Background can never hold it across a batch, so live's worst case is
one inference, not one board. This is not a mutex protecting a resource; it is a
yield signal from background work to live work.

Two live commands still race each other, deliberately: they are both the user,
and inventing an order between them would be a guess.
"""
from __future__ import annotations

import contextlib
import contextvars
import errno
import fcntl
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import threading
import time
import uuid

#: The gate. Honours an override like every other store in this project, and
#: `tests/conftest.py` must point it at scratch BEFORE importing assistant —
#: the path is read at import time, so a fixture is too late.
LOCK_PATH = pathlib.Path(
    os.environ.get("MACALENDAR_MODEL_LOCK")
    or (pathlib.Path.home() / ".assistant_tools" / "model.lock"))

#: How long LIVE traffic will wait before going anyway. One inference is ~9s on
#: this machine, so this is not "wait for the model" — it is "let a background
#: caller that is between calls notice and stand aside".
LIVE_WAIT_S = 0.05

#: How long BACKGROUND traffic will wait before giving up and going anyway. Long
#: enough to yield through a burst of live commands, bounded so a board can
#: never deadlock behind a live process that died holding nothing.
BACKGROUND_WAIT_S = 120.0

LIVE = "live"
BACKGROUND = "background"

#: THE LIVE-QUIET WINDOW (2026-09-24). Background work does not START a model
#: call while live traffic has been active within this many seconds.
#:
#: Gil, from his phone: a six-ask command took 48.9 s, 39 s of it one model call
#: — the engine's own work was 1.9 s. A 1,200-row board was running beside it.
#: `hold()` let the live call wait only 50 ms and go, which is right, but the
#: board re-took the model the instant each of its calls ended, so the live
#: command's calls kept landing behind board calls ("live traffic never waits
#: for a board" was true of the LOCK and false of the MODEL). Now every live
#: command stamps a file as it starts and around each of its model calls, and a
#: background caller waits for the stamp to go quiet before starting its next
#: call. A call already in flight cannot be interrupted; nothing new starts.
LIVE_QUIET_S = float(os.environ.get("MACALENDAR_LIVE_QUIET_S") or 20.0)


def _live_stamp() -> pathlib.Path:
    """Beside the lock, read at call time so a redirected lock moves it too."""
    return LOCK_PATH.with_name(LOCK_PATH.name + ".live")


def note_live() -> None:
    """Live traffic is happening now. Never raises."""
    try:
        stamp = _live_stamp()
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
    except OSError:
        pass


def live_recently(window: float = None) -> bool:
    """Was live traffic active within the quiet window?"""
    try:
        age = time.time() - _live_stamp().stat().st_mtime
    except OSError:
        return False
    return 0 <= age < (LIVE_QUIET_S if window is None else window)

#: The server's HMAC key. 32 random bytes, written 0600 on first use.
SECRET_PATH = pathlib.Path(
    os.environ.get("MACALENDAR_DEVICE_SECRET")
    or (pathlib.Path.home() / ".assistant_tools" / "device_secret"))

#: Who has enrolled: id -> {label, source, enrolled_at, last_seen, revoked}.
REGISTRY_PATH = pathlib.Path(
    os.environ.get("MACALENDAR_DEVICES")
    or (pathlib.Path.home() / ".assistant_tools" / "devices.json"))

_registry_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Enrolment: a name the server issued, not one the caller asserted
# ---------------------------------------------------------------------------

def _secret() -> bytes:
    """The HMAC key, created once and kept 0600.

    Regenerating it invalidates every token, which is the emergency lever: if
    the secret leaks, deleting the file un-enrols every device at once and each
    one re-enrols. That is a blunt revocation and it is meant to be — per-device
    revocation is `revoke()`.
    """
    try:
        if SECRET_PATH.exists():
            # NO `.strip()`. The key is RANDOM BYTES, and 4.61% of 32-byte keys
            # begin or end with a byte `.strip()` eats (space, tab, newline, CR,
            # VT, FF — six values out of 256, at either end). Stripping made the
            # key read back SHORT, the length check then rejected it, and a
            # brand-new key was written — silently invalidating every device
            # token at once, roughly one start in twenty.
            #
            # It surfaced as a FLAKY TEST: "revoke one device" intermittently
            # un-verified the other, at exactly 4.6%. In production it would look
            # like every device being logged out for no reason, which is
            # indistinguishable from an attack. Bytes are not text; they are not
            # stripped, trimmed or decoded.
            raw = SECRET_PATH.read_bytes()
            if len(raw) >= 32:
                return raw
        SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        made = secrets.token_bytes(32)
        # 0600 BEFORE the bytes go in: creating world-readable and chmod-ing
        # after leaves a window where the key is readable, and a key that was
        # ever readable is not a key.
        fd = os.open(str(SECRET_PATH), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            os.write(fd, made)
        finally:
            os.close(fd)
        return made
    except OSError:
        # No key, no trust. Everything becomes untrusted, which ISOLATES rather
        # than merges — the safe direction. Never fabricate an in-memory key: a
        # key that changes per process would fail every existing token and look
        # exactly like an attack.
        return b""


def token_for(source: str, device_id: str) -> str:
    """The proof that this id was ISSUED rather than invented.

    HMAC-SHA256 over `source:device_id`, so a token minted for a phone cannot be
    replayed by something claiming to be the Mac — the source is inside the
    signature, not merely beside it.
    """
    key = _secret()
    if not key:
        return ""
    msg = f"{(source or '').strip().lower()}:{(device_id or '').strip()}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _load_registry() -> dict:
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_registry(reg: dict) -> None:
    try:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = REGISTRY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(reg, indent=2, sort_keys=True))
        tmp.replace(REGISTRY_PATH)      # atomic: never a half-written registry
    except OSError:
        pass


def enroll(source: str, label: str = "") -> dict:
    """Issue a NAME and a token for one device. Returns what the client stores.

    The id is server-generated, so two devices cannot collide by accident and a
    client cannot choose to be an existing one. The label is the human name —
    "Gil's iPhone" — which is what logs, the review panel and the weekly review
    should show; a UUID tells a reader nothing about whose command it was.
    """
    src = (source or "").strip().lower() or "ios"
    did = f"{src}-{uuid.uuid4().hex[:16]}"
    with _registry_lock:
        reg = _load_registry()
        reg[did] = {"label": (label or "").strip()[:64] or did,
                    "source": src, "enrolled_at": time.time(),
                    "last_seen": 0.0, "revoked": False}
        _save_registry(reg)
    return {"device_id": did, "token": token_for(src, did), "label": reg[did]["label"]}


def verify(source: str, device_id: str, token: str) -> bool:
    """Is this device who it says it is, and is it still allowed?

    Constant-time compare, because a token check that leaks timing leaks the
    token. Unknown and revoked ids fail here rather than being quietly
    accepted — an id the server never issued has no claim on a stream.
    """
    did = (device_id or "").strip()
    tok = (token or "").strip()
    if not did or not tok:
        return False
    expected = token_for(source, did)
    if not expected or not hmac.compare_digest(expected, tok):
        return False
    entry = _load_registry().get(did)
    if entry is None or entry.get("revoked"):
        return False
    return True


def seen(device_id: str) -> None:
    """Record that a verified device just spoke — so `GET /devices` can show
    what is actually in use and the user can revoke what is not."""
    with _registry_lock:
        reg = _load_registry()
        if device_id in reg:
            reg[device_id]["last_seen"] = time.time()
            _save_registry(reg)


def revoke(device_id: str) -> bool:
    """Retire one device without disturbing the others. A revoked device keeps
    working as an UNTRUSTED, isolated stream — it cannot rejoin the stream it
    used to own, which is the property that makes a stolen token survivable."""
    with _registry_lock:
        reg = _load_registry()
        if device_id not in reg:
            return False
        reg[device_id]["revoked"] = True
        _save_registry(reg)
        return True


def devices() -> dict:
    """The registry, for `GET /devices`."""
    return _load_registry()


#: This PROCESS, for callers that are not clients at all — a board, a test
#: sandbox, a script driving the engine in-process. Stable for the life of the
#: process and unique across processes, so two sandboxes running at once are
#: two entities without having to coordinate.
_PROCESS_ID = f"proc-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def local_device_id() -> str:
    """`MACALENDAR_DEVICE_ID`, or this process's own id."""
    return (os.environ.get("MACALENDAR_DEVICE_ID") or "").strip() or _PROCESS_ID


#: Set PER REQUEST, and it outranks the environment.
#:
#: The env var describes a whole PROCESS, which is right for a board and wrong
#: for the API server: one server process serves the phone, the Mac and any
#: test curl, so a `source: "test"` request was inheriting LIVE priority purely
#: by arriving at a live process. Gil, 2026-09-10: *"real device takes
#: precedence over test, so push real device to the front of the queue."*
#:
#: A `ContextVar` rather than a global: Flask serves each request on its own
#: thread and each gets its own context, so two concurrent requests cannot read
#: each other's priority.
_request_priority: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "macalendar_request_priority", default=None)

#: Sources that are a PERSON waiting for an answer.
_REAL_SOURCES = frozenset({"ios", "mac"})


def priority_for(source: "str | None") -> str:
    """LIVE for a real device, BACKGROUND for a test.

    Deliberately keyed on SOURCE and not on trust: an old iOS client that sends
    no device id is unverified — so it cannot MERGE with the enrolled phone —
    but it is still a person holding a phone waiting for an answer, and
    demoting it would punish the user for the app being out of date. Trust
    decides who you are grouped with; source decides whether someone is
    waiting.
    """
    return LIVE if (source or "").strip().lower() in _REAL_SOURCES else BACKGROUND


@contextlib.contextmanager
def serving(source: "str | None"):
    """Mark this request's priority for every model call made under it."""
    token = _request_priority.set(priority_for(source))
    try:
        yield
    finally:
        _request_priority.reset(token)


def priority() -> str:
    """The priority of the work being done right now.

    Per-request first (`serving`), then `MACALENDAR_LLM_PRIORITY` for a whole
    process, then LIVE.

    Live is the DEFAULT on purpose. A new caller that forgets to declare itself
    is treated as the user, so the failure mode of forgetting is "a board is
    slightly ruder than it should be", never "a voice command waits behind a
    board".
    """
    got = _request_priority.get()
    if got is not None:
        return got
    return (BACKGROUND if os.environ.get("MACALENDAR_LLM_PRIORITY", "").strip().lower()
            == BACKGROUND else LIVE)


def seed_options() -> dict:
    """The extra ollama `options` of a SEEDED process — `{"seed": N,
    "temperature": 0.0}` when `MACALENDAR_LLM_SEED` holds an integer, `{}`
    otherwise. Read at call time like the priority, and merged LAST into every
    generating door's options so it overrides a configured temperature.

    Unset for live traffic: the assistant answers the way it always has. Set by
    a MEASUREMENT, so two runs of one board on one commit produce the same
    rows. Board D v2 measured what its absence costs (2026-09-22): two runs of
    the 1,200-row board at the same code differed on 22 rows, none of them
    touched by the thing being measured — the rescue's unseeded parse
    answering "book club" one time and "club" the next — which is more rows
    than the board's two arms disagree on (19). A fixed/broke pair read
    through that is dice. A value that is not an integer is ignored rather
    than crashing a run at its first model call.
    """
    raw = os.environ.get("MACALENDAR_LLM_SEED", "").strip()
    if not raw:
        return {}
    try:
        return {"seed": int(raw), "temperature": 0.0}
    except ValueError:
        return {}


def stream_key(source: "str | None", device: "str | None" = None,
               trusted: bool = False, anon: "str | None" = None) -> str:
    """The identity whose requests may be spoken in one breath.

    Two requests share a stream when they came from the SAME DEVICE. The source
    stays in the key so a device id colliding across surfaces cannot merge a Mac
    with a phone, and so a `test` sandbox can never join real traffic — that
    last one is not hypothetical: merging a test's words into the user's batch
    would execute them AND attribute the whole batch to one source, defeating
    `weekly_review.py`'s test-traffic filter, which had been inflating measured
    real-usage accuracy to 83%.

    ## Three tiers, and the middle one is the security property

        trusted     `ios:ios-7f3a…`              the server ISSUED this id
        untrusted   `ios:untrusted:9c1e…`        it merely CLAIMED it
        anonymous   `test:anon:proc-4821-…`      it claimed nothing

    **An unverified caller can never land in a verified device's stream**, even
    if it presents that device's exact id — the claimed id is hashed into a
    separate namespace instead. So spoofing buys nothing: the imposter gets its
    own isolated queue and the real phone's backlog is untouched. That is the
    whole defence, and it is structural rather than a check that could be
    forgotten at one call site.

    It also means a device whose token is REVOKED keeps working, isolated,
    rather than silently rejoining the stream it used to own — which is what
    makes a stolen token survivable instead of catastrophic.

    Anonymous callers fall back to `anon`, or to THIS PROCESS when none is
    given. That is what makes two test sandboxes two entities without any
    coordination: each one is its own process, so each one is its own stream.
    Previously both were the bare string "test" and their commands merged.
    """
    src = (source or "ios").strip().lower() or "ios"
    dev = (device or "").strip()
    if dev and trusted:
        return f"{src}:{dev}"
    if dev:
        # Hashed, not pasted: the namespace must be separate AND the claimed id
        # must not be reflected verbatim into a log line or a group key.
        digest = hashlib.sha256(dev.encode()).hexdigest()[:12]
        return f"{src}:untrusted:{digest}"
    return f"{src}:anon:{(anon or '').strip() or local_device_id()}"


def may_merge(a: "tuple", b: "tuple") -> bool:
    """May these two requests be concatenated into one prompt?

    Each argument is `(source, device)` or `(source, device, trusted)`. True
    only for the same stream — the question is "is this the same phone", never
    "is this also a phone".
    """
    return stream_key(*a) == stream_key(*b)


def _open_lock():
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        return os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return None                   # unwritable path: never block on it


@contextlib.contextmanager
def hold(kind: "str | None" = None):
    """Serialise ONE model call against every other process on this machine.

    Yields the milliseconds spent waiting, so a caller can subtract it from its
    own timeout: `_estimate_timeout` is computed before the POST and covers the
    wait, which is how a user's command times out because a board was ahead of
    it — the model was never even reached.

    **It never raises and it never refuses.** Every failure path — no lock file,
    a filesystem that cannot flock, a timeout — falls through to running the
    call. A command must not fail because its traffic warden could not start.
    """
    kind = kind or priority()
    limit = BACKGROUND_WAIT_S if kind == BACKGROUND else LIVE_WAIT_S
    t0 = time.monotonic()
    if kind == BACKGROUND:
        # Stand aside while someone is using the assistant (bounded by the
        # same limit as the lock wait, so a board never hangs for ever).
        while live_recently() and time.monotonic() - t0 < limit:
            time.sleep(0.25)
    else:
        note_live()
    fd = _open_lock()
    held = False
    if fd is not None:
        deadline = t0 + limit
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    break             # not a contention error — do not spin
                if time.monotonic() >= deadline:
                    break             # go anyway; see the docstring
                time.sleep(0.02)
    try:
        yield int((time.monotonic() - t0) * 1000)
    finally:
        if fd is not None:
            if held:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(fd)
        # THE YIELD GAP, and a live demo is what found the need for it.
        #
        # `flock` has no fairness and this poller has no queue, so a board in a
        # tight loop re-acquires the instant it releases and a second board
        # never gets in: measured against real ollama, background caller #2
        # waited the FULL 120s bound and then barged, which is precisely the
        # "two boards hammering the model" this exists to stop. Live traffic was
        # never affected — it waits 50ms and goes — so no unit test saw it.
        #
        # Sleeping briefly after a background release opens a window a waiter can
        # actually take. It costs a board ~30ms per call and costs live traffic
        # nothing, which is the trade this whole module is making.
        if kind == BACKGROUND and held:
            time.sleep(0.03)
        if kind != BACKGROUND:
            note_live()          # the quiet window runs from the END of a live call

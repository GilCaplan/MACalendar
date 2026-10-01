"""The Mac's Easter egg: magic words (DEVQA Q75), through its own helper.

The drawings, the word matcher and every decision live in Swift, shared with
the phone (`MACalendar-iOS/MACalendar-iOS/EasterEgg/`, `EggRules`), so this
module does not match words itself — a second matcher in Python would drift
from the phone's. It starts the helper (`mac/MagicWords`, built on first use)
and asks it, one JSON line at a time:

    heard(text, bare=True)   → True when the words were only magic words:
                               the caller then does not send them.
    heard(text, bare=False)  → plays what a command names, while it runs.

Best effort throughout: no helper (not a Mac, no Swift compiler, a build that
failed) means no animations and nothing else changes — a command is never
held up or dropped because of an Easter egg.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import select
import shutil
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

HERE = pathlib.Path(__file__).resolve().parents[1] / "mac" / "MagicWords"
BINARY = HERE / "build" / "MACalendarMagic"

_proc: "subprocess.Popen | None" = None
_lock = threading.Lock()
_building = False


def _disabled() -> bool:
    return (sys.platform != "darwin" or "PYTEST_CURRENT_TEST" in os.environ
            or os.environ.get("MACALENDAR_NO_MAGIC") == "1")


def _store_dir() -> str:
    override = os.environ.get("MACALENDAR_MAGIC_WORDS")
    if override:
        return override
    from assistant.users import paths as _paths
    return os.path.dirname(_paths.resolve(os.path.expanduser("~/.assistant_tools/magic_words.json")))


def _build() -> None:
    global _building
    try:
        subprocess.run([str(HERE / "build.sh")], check=True, capture_output=True, timeout=600)
        logger.info("✨ Built the magic-words helper")
        _spawn()
    except Exception as e:                       # noqa: BLE001 — best effort
        logger.warning("✨ Could not build the magic-words helper: %s", e)
    finally:
        _building = False


def _spawn() -> None:
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            return
        _proc = subprocess.Popen([str(BINARY), _store_dir()], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, bufsize=1)


def _stale() -> bool:
    """The helper is older than a Swift file it is built from — rebuild, or a
    change to the drawings or the settings window never reaches the Mac."""
    if not BINARY.exists():
        return True
    built = BINARY.stat().st_mtime
    egg = HERE.parents[1] / "MACalendar-iOS" / "MACalendar-iOS" / "EasterEgg"
    script = (HERE / "build.sh").read_text()
    # Only what build.sh compiles: the phone's own screens don't count.
    shared = [egg / name for name in re.findall(r'"\$EGG/([\w.]+\.swift)"', script)]
    sources = [*HERE.glob("*.swift"), HERE / "build.sh", *shared]
    return any(p.stat().st_mtime > built for p in sources if p.exists())


def start() -> None:
    """Start the helper, building it in the background the first time and
    whenever its sources have changed since."""
    global _building
    if _disabled():
        return
    if not _stale():
        try:
            _spawn()
        except OSError as e:
            logger.warning("✨ Could not start the magic-words helper: %s", e)
    elif not _building and shutil.which("swiftc"):
        _building = True
        threading.Thread(target=_build, daemon=True, name="magic-words-build").start()
    elif BINARY.exists():                        # stale, but nothing to rebuild it with
        try:
            _spawn()
        except OSError as e:
            logger.warning("✨ Could not start the magic-words helper: %s", e)


def _ask(op: str, wait: bool = False, timeout: float = 0.5, **fields) -> "dict | None":
    if _disabled():
        return None
    with _lock:
        p = _proc
        if not p or p.poll() is not None or not p.stdin or not p.stdout:
            return None
        try:
            p.stdin.write(json.dumps({"op": op, **fields}) + "\n")
            p.stdin.flush()
            if not wait:
                return None
            ready, _, _ = select.select([p.stdout], [], [], timeout)
            if not ready:
                return None
            return json.loads(p.stdout.readline() or "null")
        except (OSError, ValueError):
            return None


def heard(text: str, bare: bool) -> bool:
    """Tell the helper what was said. bare=True → True when the words were
    only magic words (don't send). bare=False → True when something played."""
    # Usually answered in a millisecond; the longer leash is for the rare
    # moment the helper is busy rendering, so a bare magic word is still
    # recognised rather than sent on as a command.
    reply = _ask("heard", wait=True, timeout=2.5, text=text, bare=bare)
    if bare:
        return bool(reply and reply.get("bare"))
    return bool(reply and reply.get("played"))


def heard_late(text: str) -> bool:
    """The brain's corrected transcript, when the raw words played nothing —
    a name Whisper misheard and the vocabulary fixed ("Val"). Checked whether
    or not the command made anything. True when something played."""
    text = re.sub(r"^\s*\[[A-Z ]+ VIEW\]\s*", "", text or "")   # the words, not the view tag
    if not text.strip():
        return False
    reply = _ask("heard_late", wait=True, text=text)
    return bool(reply and reply.get("played"))


def open_settings() -> None:
    _ask("settings", wait=True)


def demo() -> None:
    _ask("demo", wait=True)


def festival_tick() -> None:
    _ask("festival", wait=True)


def stop() -> None:
    _ask("quit")


# -- the loading screen (TASKS 48) --------------------------------------------

def wait_begin() -> str:
    """A command is in flight. One that runs past the loader's threshold shows
    the user's loading screen in the middle of the screen. Returns its id."""
    import uuid
    wid = uuid.uuid4().hex
    _ask("wait_begin", id=wid)
    return wid


def wait_end(wid: "str | None") -> None:
    if wid:
        _ask("wait_end", id=wid)


def made(labels: "list[str]") -> None:
    """What a command just made — its events' categories and to-dos' tags —
    for "Also for what gets made" (the helper decides, as the phone does)."""
    if labels:
        _ask("made", labels=list(labels))


def made_rows(rows: "list[dict]") -> None:
    """The reply's `committed` rows ({"kind", "id"}) → their category or tags
    → `made`. On a daemon thread: it reads the database, and the caller is the
    voice pipeline, which must not wait on an Easter egg."""
    if _disabled() or not rows:
        return

    def work():
        try:
            from assistant.db import get_db
            db = get_db()
            labels: list[str] = []
            for r in rows:
                if r.get("kind") == "event":
                    e = db.get_event(int(r["id"]))
                    if e and e.get("category"):
                        labels.append(e["category"])
                elif r.get("kind") == "todo":
                    t = db.get_todo(int(r["id"]))
                    if t:
                        labels.extend(t.get("tags") or [])
            made(labels)
        except Exception as e:                   # noqa: BLE001 — best effort
            logger.debug("✨ made: %s", e)

    threading.Thread(target=work, daemon=True, name="magic-words-made").start()


def loader_demo() -> None:
    _ask("loader_demo", wait=True)


def loader_frames() -> "dict | None":
    """The loader as a loop of frames the helper wrote for the HUD — which is a
    separate process and cannot talk to the helper — or None (off, never
    written, not a Mac). {"dir", "frames", "fps", "enabled", "caption"}."""
    if sys.platform != "darwin" or (_disabled() and not os.environ.get("MACALENDAR_MAGIC_WORDS")):
        return None
    try:
        with open(os.path.join(_store_dir(), "loader", "current.json"), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    if not info.get("enabled") or not os.path.isdir(info.get("dir", "")):
        return None
    return info

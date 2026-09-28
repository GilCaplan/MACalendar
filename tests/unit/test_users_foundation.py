"""Users, phase 1: every personal store is per user, and today's data moves
into the admin's folder without a byte changing.

Gil, 2026-09-28: an admin plus other users, each with their own calendar,
to-dos and everything the assistant learns about them. The request asked for
proof that *user A's command can never write B's db or vocab* — that is
`test_one_users_command_never_touches_anothers_stores`, through the real
engine, and the store-by-store test beside it.

The compat contract is the other half: with nobody bound and no registry,
every store resolves to exactly the path it always had — which the rest of
the suite (3,008 tests, none of which binds a user) is the proof of.
"""
from __future__ import annotations

import ast
import hashlib
import os
import pathlib

import pytest

from assistant import users
from assistant.users import migrate, passwords, paths, registry

REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """A registry of our own: its directory is the root of every user store."""
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    users.set_process_default(None)
    yield tmp_path
    users.set_process_default(None)


# ------------------------------------------------------------------ paths

def test_nobody_bound_means_every_path_is_unchanged(reg):
    assert users.current() is None
    assert paths.resolve("/x/y/calendar.db") == "/x/y/calendar.db"
    assert paths.resolve(pathlib.Path("/x/models")) == pathlib.Path("/x/models")


def test_a_bound_user_gets_the_same_file_name_in_their_own_folder(reg):
    with users.bind("u_abc"):
        assert paths.resolve("/anything/calendar.db") == str(reg / "users" / "u_abc" / "calendar.db")
        assert paths.resolve(pathlib.Path("/a/models")) == reg / "users" / "u_abc" / "models"


def test_the_suite_roots_users_in_scratch_never_the_real_directory():
    real = os.path.realpath(os.path.expanduser("~/.assistant_tools"))
    assert os.path.realpath(paths.root()) != real


def test_a_user_id_cannot_walk_out_of_the_users_folder(reg):
    for bad in ("../etc", "a/b", ".hidden", ""):
        with pytest.raises(ValueError):
            paths.user_dir(bad)


# ------------------------------------------------------------------ passwords

def test_passwords_round_trip_and_are_never_stored_readably(reg):
    rec = passwords.hash_password("correct horse")
    assert passwords.verify("correct horse", rec)
    assert not passwords.verify("correct hors", rec)
    uid = registry.create_user("dana", "correct horse")
    text = pathlib.Path(paths.registry_path()).read_text()
    assert "correct horse" not in text and "dana" in text
    assert registry.verify_login("Dana", "correct horse") == uid
    assert registry.verify_login("dana", "wrong password") is None


def test_a_short_password_is_refused():
    with pytest.raises(ValueError):
        passwords.hash_password("short")


def test_generated_passwords_are_readable_and_do_not_repeat():
    seen = {passwords.generate() for _ in range(500)}
    assert len(seen) == 500
    assert all(len(p) == 12 and not set(p) & set("0O1lI") for p in seen)


# ------------------------------------------------------------------ registry

def test_one_admin_and_unique_lowercase_usernames(reg):
    registry.create_user("gil", "password1", role="admin")
    with pytest.raises(ValueError, match="already an admin"):
        registry.create_user("other", "password1", role="admin")
    registry.create_user("dana", "password1")
    with pytest.raises(ValueError, match="taken"):
        registry.create_user("DANA", "password1")
    with pytest.raises(ValueError):
        registry.create_user("no spaces", "password1")


def test_a_disabled_user_cannot_log_in_and_the_admin_cannot_be_disabled(reg):
    admin = registry.create_user("gil", "password1", role="admin")
    dana = registry.create_user("dana", "password1")
    registry.update_user(dana, disabled=True)
    assert registry.verify_login("dana", "password1") is None
    with pytest.raises(ValueError):
        registry.update_user(admin, disabled=True)


def test_sharing_is_per_person_view_or_edit_and_replaceable(reg):
    a = registry.create_user("gil", "password1", role="admin")
    d = registry.create_user("dana", "password1")
    registry.set_share(d, a, "view")
    assert registry.share_level(d, a) == "view"
    registry.set_share(d, a, "edit")
    assert registry.share_level(d, a) == "edit" and len(registry.shares_out(d)) == 1
    registry.set_share(d, a, None)
    assert registry.share_level(d, a) is None
    with pytest.raises(ValueError):
        registry.set_share(d, d, "view")


def test_the_admins_view_of_others_is_off_until_he_turns_it_on(reg):
    a = registry.create_user("gil", "password1", role="admin")
    d = registry.create_user("dana", "password1")
    assert registry.admin_shows(a, d) is False
    registry.set_admin_view(a, d, True)
    assert registry.admin_shows(a, d) is True
    with pytest.raises(ValueError):
        registry.set_admin_view(d, a, True)


def test_the_admin_chooses_who_his_vocabulary_is_shared_with(reg):
    a = registry.create_user("gil", "password1", role="admin")
    d = registry.create_user("dana", "password1")
    assert registry.vocab_sources(d) == [d]
    registry.set_vocab_share(a, d, True)
    assert registry.vocab_sources(d) == [d, a]


def test_nobody_logged_in_acts_as_the_admin_until_login_is_required(reg):
    assert users.current() is None                     # no registry: legacy
    a = registry.create_user("gil", "password1", role="admin")
    assert users.current() == a
    registry.set_policy(require_login=True)
    assert users.current() is None
    with users.bind("u_someone"):
        assert users.current() == "u_someone"


# ------------------------------------------------------------------ isolation

@pytest.fixture
def two(reg):
    a = registry.create_user("gil", "password1", role="admin")
    b = registry.create_user("dana", "password1")
    return a, b


def _udir(uid):
    return pathlib.Path(paths.user_dir(uid))


def test_each_store_writes_only_the_bound_users_file(two):
    a, b = two
    from assistant import llm_bus, trace_bus
    from assistant.actions.calendar import categories
    from assistant.db import get_db
    from assistant.engine.label import feedback
    from assistant.intent.context import context_memory
    from assistant.intent.memory import get_memory
    from assistant.stt.vocab import get_vocab

    with users.bind(a):
        ev = get_db().create_event_from_dict({
            "title": "gil's dentist", "date": "2026-10-01", "start_time": "09:00",
            "end_time": "10:00", "attendees": "", "location": "", "description": "",
            "recurrence": "", "recurrence_end": ""})
        get_db().create_todo("gil's milk")
        get_memory().record(transcript="gil said this", source="test")
        get_vocab().add_word("Jada", ["jaida"])
        trace_bus.publish("test", [{"stage": "done", "title": "Done"}], {"message": "hi"})
        feedback.record_category("gil's dentist", None, "Health")
        context_memory.update_event(ev, "gil's dentist", "2026-10-01")
        a_db = get_db().path

    assert a_db == str(_udir(a) / os.path.basename(os.environ["MACALENDAR_DB"]))
    for name in ("vocab.json", "trace_bus.jsonl", "label_feedback.jsonl"):
        assert (_udir(a) / name).exists(), name

    # A's own reads see A's rows — so the empty reads below are not hollow
    with users.bind(a):
        assert [t["title"] for t in get_db().get_todos()] == ["gil's milk"]
        assert get_db().get_event(ev)["title"] == "gil's dentist"
        assert get_memory().stats()["total"] == 1
        assert "Jada" in [e.word for e in get_vocab().entries]
        assert len(trace_bus.read_history(50)) == 1
        assert context_memory.last_event_id == ev

    with users.bind(b):
        assert get_db().get_todos() == []
        assert get_db().get_event(ev) is None
        assert get_memory().stats()["total"] == 0
        assert "Jada" not in [e.word for e in get_vocab().entries]
        assert trace_bus.read_history(50) == []
        assert context_memory.last_event_id is None
    for name in ("vocab.json", "trace_bus.jsonl", "label_feedback.jsonl"):
        assert not (_udir(b) / name).exists(), f"{name} written into the other user's folder"


def test_one_users_command_never_touches_anothers_stores(two, monkeypatch, registry_with_real_actions):
    """Through the real engine, rule path, no model."""
    import assistant.engine.llm as _llm
    import assistant.intent.parser as _parser
    from assistant.exceptions import OllamaUnavailableError
    monkeypatch.setattr(_parser.IntentParser, "_call_ollama",
                        lambda *a, **k: (_ for _ in ()).throw(OllamaUnavailableError("no model")))
    monkeypatch.setattr(_llm, "is_reachable", lambda cfg=None: False)
    monkeypatch.setenv("MACALENDAR_NO_BG", "1")

    from assistant import engine
    from assistant.db import get_db
    a, b = two
    with users.bind(a):
        engine.run_transcript("book the dentist tomorrow at 4", source="test")
        mine = [e["title"] for e in get_db().get_events_between(
            __import__("datetime").date.today(),
            __import__("datetime").date.today() + __import__("datetime").timedelta(days=2))]
    assert any("dentist" in t for t in mine)
    with users.bind(b):
        import datetime as dt
        assert get_db().get_events_between(dt.date.today(),
                                           dt.date.today() + dt.timedelta(days=2)) == []
    assert not (_udir(b) / "nlu_memory.db").exists() or \
        __import__("sqlite3").connect(str(_udir(b) / "nlu_memory.db")).execute(
            "select count(*) from examples").fetchone()[0] == 0


def test_a_background_thread_keeps_the_callers_user(two):
    a, _ = two
    seen = []
    with users.bind(a):
        t = users.thread(target=lambda: seen.append(users.current()), daemon=True)
    t.start(); t.join(2)
    assert seen == [a]


def test_every_thread_the_engine_or_api_starts_carries_its_user():
    """A new thread starts with no bound user. Every `threading.Thread(` under
    the engine and the API is `users.thread(` or on this list with a reason."""
    allowed = {
        ("assistant/api/server.py", "warm-up"),          # loads models; touches no store
        ("assistant/api/server.py", "pending-retry"),    # binds each user itself
    }
    found = []
    for root in ("assistant/engine", "assistant/api"):
        for f in (REPO / root).rglob("*.py"):
            if "experiments" in f.parts:
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "Thread" and getattr(node.func.value, "id", "") in (
                            "threading", "_threading"):
                    name = next((k.value.value for k in node.keywords
                                 if k.arg == "name" and isinstance(k.value, ast.Constant)), "?")
                    found.append((str(f.relative_to(REPO)), name))
    assert set(found) <= allowed, f"threads that drop the user: {set(found) - allowed}"


# ------------------------------------------------------------------ migration

def _legacy_tree(root: pathlib.Path) -> None:
    from assistant.db import CalendarDB
    db = CalendarDB(str(root / "calendar.db"))
    db.create_todo("migrated milk")
    (root / "vocab.json").write_text('{"words": []}')
    (root / "trace_bus.jsonl").write_text('{"kind": "trace"}\n')
    (root / "models").mkdir()
    (root / "models" / "event_label.joblib").write_bytes(b"model-bytes")
    (root / "calendar.db.bak-old").write_bytes(b"old backup")
    (root / "hud_position.json").write_text('{"x": 1, "y": 2}')      # global: stays


def _md5s(root: pathlib.Path) -> dict:
    return {str(p.relative_to(root)): hashlib.md5(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    root = tmp_path / "store"
    root.mkdir()
    monkeypatch.setenv("MACALENDAR_USERS", str(root / "users.json"))
    _legacy_tree(root)
    users.set_process_default(None)
    return root


def test_a_dry_run_changes_nothing(legacy):
    before = _md5s(legacy)
    p = migrate.plan()
    assert set(p["move"]) >= {"calendar.db", "vocab.json", "trace_bus.jsonl", "models"}
    assert _md5s(legacy) == before and not registry.exists()


def test_apply_moves_every_store_into_the_admins_folder_unchanged(legacy):
    before = _md5s(legacy)
    rec = migrate.apply("gil", "password1", check_stack=False)
    admin = rec["admin"]
    dest = legacy / "users" / admin
    for name in ("calendar.db", "vocab.json", "trace_bus.jsonl", "models/event_label.joblib"):
        assert (dest / name).exists() and not (legacy / name).exists(), name
        assert hashlib.md5((dest / name).read_bytes()).hexdigest() == before[name]
    assert (legacy / "hud_position.json").exists()                     # global stays
    assert (legacy / "legacy" / "calendar.db.bak-old").exists()
    assert pathlib.Path(rec["backup"]).is_dir()
    assert (dest / "MIGRATED.json").exists()
    # and the assistant, with nobody logged in, now reads the admin's data
    from assistant.db import CalendarDB
    assert users.current() == admin
    titles = [t["title"] for t in CalendarDB().get_todos()]
    assert "migrated milk" in titles


def test_apply_twice_is_refused(legacy):
    migrate.apply("gil", "password1", check_stack=False)
    with pytest.raises(migrate.MigrationError, match="already migrated"):
        migrate.apply("gil", "password1", check_stack=False)


def test_a_mismatch_after_the_move_rolls_everything_back(legacy, monkeypatch):
    before = _md5s(legacy)
    real = migrate.snapshot
    calls = []

    def lying(base):
        calls.append(base)
        snap = real(base)
        return snap if len(calls) == 1 else {**snap, "calendar.db": {"events": -1}}
    monkeypatch.setattr(migrate, "snapshot", lying)
    with pytest.raises(migrate.MigrationError, match="does not match"):
        migrate.apply("gil", "password1", check_stack=False)
    after = {k: v for k, v in _md5s(legacy).items() if not k.startswith("legacy/")}
    assert {k: v for k, v in before.items() if ".bak" not in k} == \
        {k: v for k, v in after.items() if ".bak" not in k}
    assert not registry.exists() and not (legacy / "users").exists()


def test_rollback_restores_the_tree_byte_for_byte(legacy):
    before = _md5s(legacy)
    migrate.apply("gil", "password1", check_stack=False)
    migrate.rollback(check_stack=False)
    assert _md5s(legacy) == before
    assert not registry.exists()


def test_rollback_is_refused_once_another_user_exists(legacy):
    migrate.apply("gil", "password1", check_stack=False)
    registry.create_user("dana", "password1")
    with pytest.raises(migrate.MigrationError, match="orphaned"):
        migrate.rollback(check_stack=False)


def test_the_real_users_tree_is_refused_under_pytest():
    from assistant.db import DB_PATH, CalendarDB
    real = os.path.join(os.path.dirname(DB_PATH), "users", "u_x", "calendar.db")
    with pytest.raises(RuntimeError, match="Refusing to open the real"):
        CalendarDB(path=real)

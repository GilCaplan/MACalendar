"""Model helpers (DEVQA Q70): other computers lend the primary their model.

What must hold:
- with no helpers, a model call is exactly what it was — hold() + this machine;
- a helper is used only when it is up, speaks the same gate version, and holds
  the SAME build of the model; a board (seeded) never leaves this machine;
- the person's order decides; this machine is skipped while busy only when a
  helper comes after it, and is always the last resort;
- a helper answers only callers holding a token it issued, for the code on
  its own screen, and stores only hashes;
- changing the helper list is done on the primary itself; the log is the
  admin's.
"""
from __future__ import annotations

import json
import time

import pytest
import requests

import assistant.api.server as server
from assistant import model_protocol
from assistant.model_hosts import router, store


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PATH", tmp_path / "hosts.json")
    router._health.clear()
    router._local.update(models={"llama3.1:8b": "sha-A"}, at=time.time())
    monkeypatch.setattr(router, "_ensure_checker", lambda base: None)
    monkeypatch.delenv("MACALENDAR_LLM_SEED", raising=False)
    yield
    router._health.clear()


def _helper(hid_name="Gaming PC", digest="sha-A", up=True, gate=1):
    hid = store.add(hid_name, "Windows", [f"http://10.0.0.{len(hid_name)}:11436"], "tok")
    router._health[hid] = {"up": up, "url": f"http://10.0.0.{len(hid_name)}:11436",
                           "info": {"gate": gate, "models": {"llama3.1:8b": digest}},
                           "at": time.time(), "why": "" if up else "not reachable"}
    return hid


BASE = "http://localhost:11434"


# -- the plan ---------------------------------------------------------------

def test_no_helpers_means_this_machine_exactly_as_before():
    assert router.plan("llama3.1:8b", BASE) == [("local", BASE, {})]


def test_a_new_helper_goes_first_and_carries_its_token():
    hid = _helper()
    plan = router.plan("llama3.1:8b", BASE)
    assert [p[0] for p in plan] == [hid, "local"]
    assert plan[0][2] == {"Authorization": "Bearer tok"}


def test_a_different_build_of_the_model_is_never_used():
    _helper(digest="sha-B")
    assert [p[0] for p in router.plan("llama3.1:8b", BASE)] == ["local"]


def test_a_helper_without_the_model_is_never_used():
    _helper()
    assert [p[0] for p in router.plan("qwen2.5:7b", BASE)] == ["local"]


def test_a_helper_that_is_down_is_skipped():
    _helper(up=False)
    assert [p[0] for p in router.plan("llama3.1:8b", BASE)] == ["local"]


def test_a_board_never_leaves_this_machine(monkeypatch):
    _helper()
    monkeypatch.setenv("MACALENDAR_LLM_SEED", "7")
    assert [p[0] for p in router.plan("llama3.1:8b", BASE)] == ["local"]


def test_the_order_is_the_persons():
    hid = _helper()
    assert store.set_order(["local", hid])
    assert [p[0] for p in router.plan("llama3.1:8b", BASE)] == ["local", hid]


def test_an_order_that_adds_or_loses_a_machine_is_refused():
    hid = _helper()
    assert not store.set_order([hid])
    assert not store.set_order(["local", hid, "h-ghost"])


def test_re_adding_the_same_machine_replaces_it():
    _helper()
    _helper()
    assert len(store.load()["helpers"]) == 1


def test_the_store_is_private(tmp_path):
    _helper()
    assert (store.PATH.stat().st_mode & 0o777) == 0o600


# -- the call -----------------------------------------------------------------

class _Resp:
    def __init__(self, code=200):
        self.status_code = code


class _Session:
    def __init__(self, fail_on=()):
        self.calls, self.fail_on = [], fail_on

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, headers or {}))
        for bad in self.fail_on:
            if url.startswith(bad):
                raise requests.ConnectionError("down")
        return _Resp()


def test_a_call_goes_to_the_helper_with_the_callers_priority(monkeypatch):
    _helper()
    s = _Session()
    with model_protocol.serving("test"):
        router.post("/api/chat", {"model": "llama3.1:8b"}, 30, BASE, session=s)
    url, headers = s.calls[0]
    assert url.startswith("http://10.0.0.9:11436/api/chat")
    assert headers["X-MACalendar-Priority"] == model_protocol.priority_for("test")


def test_a_helper_that_fails_is_set_aside_and_this_machine_answers():
    _helper()
    s = _Session(fail_on=("http://10.0.0.9",))
    router.post("/api/chat", {"model": "llama3.1:8b"}, 30, BASE, session=s)
    assert [c[0].split("/api")[0] for c in s.calls] == ["http://10.0.0.9:11436", BASE]
    assert [p[0] for p in router.plan("llama3.1:8b", BASE)] == ["local"], "set aside for a minute"


def test_this_machine_overflows_to_a_later_helper_while_busy(monkeypatch):
    hid = _helper()
    store.set_order(["local", hid])
    monkeypatch.setattr(model_protocol, "local_busy", lambda: True)
    s = _Session()
    router.post("/api/chat", {"model": "llama3.1:8b"}, 30, BASE, session=s)
    assert s.calls[0][0].startswith("http://10.0.0.9")


def test_this_machine_is_the_last_resort_even_when_busy(monkeypatch):
    monkeypatch.setattr(model_protocol, "local_busy", lambda: True)
    s = _Session()
    router.post("/api/chat", {"model": "llama3.1:8b"}, 30, BASE, session=s)
    assert s.calls[0][0] == f"{BASE}/api/chat"


def test_the_busy_peek_sees_another_holder(tmp_path, monkeypatch):
    monkeypatch.setattr(model_protocol, "LOCK_PATH", tmp_path / "m.lock")
    assert not model_protocol.local_busy()
    import subprocess, sys
    proc = subprocess.Popen([sys.executable, "-c", (
        "import os, time, fcntl\n"
        f"fd = os.open({str(tmp_path / 'm.lock')!r}, os.O_CREAT | os.O_RDWR)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\nprint('held', flush=True)\ntime.sleep(3)\n")],
        stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        assert model_protocol.local_busy()
    finally:
        proc.kill()


# -- the helper -----------------------------------------------------------------

@pytest.fixture
def helper(tmp_path):
    from assistant.host.helper import Helper
    return Helper(port=0, tokens_path=tmp_path / "tokens.json")


def test_the_code_on_its_screen_buys_a_token_once(helper):
    code = helper.code
    token = helper.claim(code, "MacBook Air")
    assert token and helper.authorize({"Authorization": f"Bearer {token}"})
    assert helper.claim(code, "someone else") is None, "a code works once"
    assert helper.code != code


def test_a_wrong_code_buys_nothing_and_five_pause_claiming(helper):
    for _ in range(5):
        assert helper.claim("NOPE-NOPE", "x") is None
    assert helper.claim(helper.code, "x") is None, "paused after five wrong codes"


def test_no_working_credential_is_ever_stored(helper):
    token = helper.claim(helper.code, "MacBook Air")
    raw = helper.tokens_path.read_text()
    assert token not in raw
    assert (helper.tokens_path.stat().st_mode & 0o777) == 0o600


def test_forgetting_a_primary_revokes_it(helper):
    token = helper.claim(helper.code, "MacBook Air")
    helper.forget(helper.primaries()[0]["id"])
    assert not helper.authorize({"Authorization": f"Bearer {token}"})


def test_a_gate_open_to_the_network_must_check_tokens():
    from assistant.integrations import ollama_gate
    with pytest.raises(ValueError):
        ollama_gate.start(0, BASE, host="0.0.0.0")


def test_the_helper_gate_refuses_a_caller_without_its_token(helper):
    """Through real HTTP on loopback: /api/* needs the token, /gate/info does not."""
    from assistant.integrations import ollama_gate
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    ollama_gate.start(port, "http://127.0.0.1:9", host="127.0.0.1",
                      authorize=helper.authorize, priority_header=True, extra=helper._extra)
    try:
        url = f"http://127.0.0.1:{port}"
        assert requests.post(url + "/api/chat", json={}).status_code == 401
        info = requests.get(url + "/gate/info").json()
        assert info["gate"] == router.GATE_PROTOCOL and "busy" in info
        assert requests.post(url + "/gate/claim", json={"code": "BAD"}).status_code == 403
        tok = requests.post(url + "/gate/claim", json={"code": helper.code, "primary": "p"}).json()["token"]
        # authorised now: the upstream (port 9) is dead, so the gate says 502 —
        # which proves the call got PAST the token check
        assert requests.post(url + "/api/chat", json={},
                             headers={"Authorization": f"Bearer {tok}"}).status_code == 502
    finally:
        ollama_gate.stop(port)


# -- routes ---------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(router, "refresh", lambda base=None: None)
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _remote():
    return {"environ_base": {"REMOTE_ADDR": "100.64.0.7"}}


def test_the_servers_page_lists_this_machine_and_its_helpers_in_order(client, monkeypatch):
    model = server.load_config().ollama.model
    monkeypatch.setattr(router, "local_models", lambda base, max_age=0: {model: "sha-A"})
    hid = _helper()
    router._health[hid]["info"]["models"] = {model: "sha-A"}
    got = client.get("/servers").get_json()
    assert [h["id"] for h in got["hosts"]] == [hid, "local"]
    assert got["this"]["role"] == "primary" and got["hosts"][0]["matched"]


def test_changing_the_helpers_is_done_on_the_primary_itself(client):
    hid = _helper()
    assert client.put("/servers/order", json={"order": ["local", hid]}, **_remote()).status_code == 403
    assert client.delete(f"/servers/helpers/{hid}", **_remote()).status_code == 403
    assert client.post("/servers/helpers", json={"urls": ["http://x"], "code": "C"},
                       **_remote()).status_code == 403
    assert client.put("/servers/order", json={"order": ["local", hid]}).status_code == 200


def test_the_log_is_served(client, tmp_path):
    from assistant.host import logs
    logs.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logs.path().write_text("one\ntwo\nthree\n")
    got = client.get("/servers/logs?lines=2").get_json()
    assert got["lines"] == ["two", "three"]


def test_the_log_is_the_admins_once_there_are_users(client, monkeypatch):
    from assistant.users import registry
    monkeypatch.setattr(registry, "exists", lambda: True)
    assert client.get("/servers/logs", **_remote()).status_code == 401
    assert client.get("/servers/logs").status_code == 200, "on the server itself"


def test_nothing_is_browsed_in_a_test(client):
    assert client.get("/servers/found").get_json() == {"found": []}


# -- logs and the terminal -----------------------------------------------------------

@pytest.mark.parametrize("system,first", [("Darwin", "osascript"), ("Windows", "cmd")])
def test_a_terminal_follows_the_log_on_each_platform(tmp_path, system, first):
    from assistant.host import logs
    cmd = logs.terminal_command(tmp_path / "api.log", system)
    assert cmd[0] == first and str(tmp_path / "api.log") in " ".join(cmd)


def test_the_role_defaults_to_primary_and_round_trips(tmp_path, monkeypatch):
    from assistant.host import role
    monkeypatch.setattr(role, "PATH", tmp_path / "host.json")
    assert role.get() == "primary"
    role.set("helper")
    assert role.get() == "helper"
    with pytest.raises(ValueError):
        role.set("boss")

"""Where one model call goes, and the call itself.

``post`` is the door every generating call on the primary goes through
(``model_protocol.route_post`` is its public name). With no helpers it is
exactly what it replaced — ``hold()`` then POST to this machine's ollama —
so a machine that never adds a helper runs unchanged.

Health is read in the background, never on a command's clock: a daemon thread
asks each helper's ``/gate/info`` every ``CHECK_S`` and the router only reads
what it last heard. A helper nobody has heard from yet is not used.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from assistant.model_hosts import store

logger = logging.getLogger(__name__)

GATE_PROTOCOL = 1
CHECK_S = 20.0
DOWN_S = 60.0
CONNECT_S = 3.0

_health: dict[str, dict] = {}       # hid -> {"up", "url", "info", "at", "down_until", "why"}
_local: dict = {"models": {}, "at": 0.0}
_lock = threading.Lock()
_checker: threading.Thread | None = None


# -- what each machine holds -------------------------------------------------

def _get_json(url: str, headers: dict | None = None, timeout: float = 1.5):
    import requests
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def local_models(base_url: str, max_age: float = CHECK_S) -> dict[str, str]:
    """{model name: digest} on this machine, cached."""
    if time.time() - _local["at"] < max_age:
        return _local["models"]
    try:
        tags = _get_json(f"{base_url}/api/tags")
        models = {m.get("name", ""): m.get("digest", "") for m in tags.get("models", [])}
    except Exception:
        models = _local["models"]
    _local.update(models=models, at=time.time())
    return models


def check(hid: str, helper: dict) -> dict:
    """Ask one helper how it is; the first of its addresses that answers wins."""
    why = "not reachable"
    for url in helper.get("urls", []):
        try:
            info = _get_json(f"{url}/gate/info")
        except Exception:
            continue
        if info.get("gate") != GATE_PROTOCOL:
            why = f"speaks gate version {info.get('gate')}, this needs {GATE_PROTOCOL}"
            return {"up": False, "url": url, "info": info, "at": time.time(), "why": why}
        return {"up": True, "url": url, "info": info, "at": time.time(), "why": ""}
    return {"up": False, "url": "", "info": {}, "at": time.time(), "why": why}


def refresh(base_url: str | None = None) -> None:
    helpers = store.load()["helpers"]
    for hid, h in helpers.items():
        got = check(hid, h)
        with _lock:
            prev = _health.get(hid, {})
            got["down_until"] = prev.get("down_until", 0.0)
            _health[hid] = got
    with _lock:
        for hid in [h for h in _health if h not in helpers]:
            del _health[hid]
    if base_url:
        local_models(base_url, max_age=0)


def _ensure_checker(base_url: str) -> None:
    global _checker
    if _checker is not None and _checker.is_alive():
        return

    def loop():
        while store.load()["helpers"]:
            try:
                refresh(base_url)
            except Exception as exc:                 # never let health kill a call
                logger.debug("helper health check failed: %s", exc)
            time.sleep(CHECK_S)
    _checker = threading.Thread(target=loop, name="model-hosts-health", daemon=True)
    _checker.start()


def health() -> dict[str, dict]:
    with _lock:
        return {k: dict(v) for k, v in _health.items()}


def matched(model: str, info: dict, mine: dict[str, str]) -> tuple[bool, str]:
    """Does this helper hold the SAME model? Same digest when this machine has
    it too; the name alone only when it does not (nothing to compare)."""
    theirs = info.get("models") or {}
    if model not in theirs:
        return False, f"does not have {model}"
    if model in mine and mine[model] and theirs[model] and mine[model] != theirs[model]:
        return False, f"has a different build of {model}"
    return True, ""


# -- the plan and the call ----------------------------------------------------

def plan(model: str, base_url: str) -> list[tuple[str, str, dict]]:
    """``[(hid, url, headers), …]`` in the person's order, eligible only.
    This machine is always in it."""
    data = store.load()
    if not data["helpers"]:
        return [(store.LOCAL, base_url, {})]
    _ensure_checker(base_url)
    # A board is measuring; its tokens must come from one machine.
    if os.environ.get("MACALENDAR_LLM_SEED", "").strip():
        return [(store.LOCAL, base_url, {})]
    mine = local_models(base_url)
    now = time.time()
    out = []
    for hid in data["order"]:
        if hid == store.LOCAL:
            out.append((store.LOCAL, base_url, {}))
            continue
        h = health().get(hid)
        helper = data["helpers"].get(hid)
        if not h or not helper or not h.get("up") or h.get("down_until", 0) > now:
            continue
        ok, _why = matched(model, h.get("info", {}), mine)
        if not ok:
            continue
        out.append((hid, h["url"], {"Authorization": f"Bearer {helper['token']}"}))
    return out


def _mark_down(hid: str, why: str) -> None:
    with _lock:
        h = _health.setdefault(hid, {})
        h["down_until"] = time.time() + DOWN_S
        h["why"] = why
    logger.warning("model helper %s set aside for %ds: %s", hid, int(DOWN_S), why)


def post(path: str, payload: dict, timeout, base_url: str, session=None):
    """Send one generating call; return the ``requests`` response.

    The priority is the caller's (``model_protocol.priority()``), carried to a
    helper in a header so its gate queues the call the same way. Raises what
    ``requests`` raises only when THIS machine's call does — a helper's
    failure is never the command's failure."""
    import requests
    from assistant import model_protocol
    sess = session or requests
    targets = plan(str(payload.get("model") or ""), base_url)
    for i, (hid, url, headers) in enumerate(targets):
        more_after = i < len(targets) - 1
        if hid == store.LOCAL:
            if more_after and model_protocol.local_busy():
                continue                               # overflow to a helper
            with model_protocol.hold():
                return sess.post(f"{url}{path}", json=payload, timeout=timeout)
        read_s = timeout if isinstance(timeout, (int, float)) else 120
        try:
            r = sess.post(f"{url}{path}", json=payload,
                          headers=dict(headers, **{"X-MACalendar-Priority": model_protocol.priority()}),
                          timeout=(CONNECT_S, read_s))
        except requests.RequestException as exc:
            _mark_down(hid, f"{type(exc).__name__}")
            continue
        if r.status_code in (401, 403, 404, 502, 503):
            _mark_down(hid, f"answered {r.status_code}")
            continue
        return r
    # Every helper failed after this machine was skipped as busy: wait for it.
    with model_protocol.hold():
        return sess.post(f"{base_url}{path}", json=payload, timeout=timeout)

"""Servers routes — HTTP only (DEVQA Q70).

    GET    /servers                this machine + every model host, in order,
                                   with health and whether the model matches
    GET    /servers/found          helpers announcing on the network, not yet used
    POST   /servers/helpers        {urls, code} → claim a token, add it (first)
    DELETE /servers/helpers/<id>   stop using it (and tell it to forget us)
    PUT    /servers/order          {order: [ids]} — this machine is "local"
    GET    /servers/logs?lines=N   the last N lines of the server log

Changing which machines run the model is done ON the primary (loopback: the
menu-bar app and the calendar window). The phone reads: the list for anyone
who may use this server, the log for the admin (it holds everyone's commands).
"""

from __future__ import annotations

import logging
import os
import threading
import time

from flask import jsonify, request

from assistant.model_hosts import router, store
from assistant.pairing.routes import is_local

logger = logging.getLogger(__name__)


def _err(msg: str, code: int):
    return jsonify({"error": msg, "code": code}), code


def _local_only():
    if not is_local():
        return _err("change which computers run the model on the primary itself", 403)
    return None


def _cfg():
    from assistant.config import load_config
    return load_config()


def snapshot(port: int) -> dict:
    """What the Servers pages draw."""
    from assistant.host import logs
    from assistant.host.helper import os_name
    from assistant.pairing.addresses import candidate_urls, server_name
    cfg = _cfg()
    base = cfg.ollama.base_url
    data = store.load()
    health = router.health()
    if any(time.time() - health.get(h, {}).get("at", 0) > router.CHECK_S
           for h in data["helpers"]):
        router.refresh(base)
        health = router.health()
    mine = router.local_models(base, max_age=0)
    model = cfg.ollama.model
    hosts = []
    for hid in data["order"]:
        if hid == store.LOCAL:
            hosts.append({"id": store.LOCAL, "kind": "this", "name": server_name(),
                          "os": os_name(), "up": bool(mine), "matched": model in mine,
                          "why": "" if model in mine else f"{model} is not downloaded here",
                          "busy": _busy()})
            continue
        h, helper = health.get(hid, {}), data["helpers"][hid]
        ok, why = router.matched(model, h.get("info", {}), mine) if h.get("up") else (False, h.get("why", "not checked yet"))
        down = h.get("down_until", 0) > time.time()
        hosts.append({"id": hid, "kind": "helper", "name": helper.get("name", hid),
                      "os": (h.get("info") or {}).get("os") or helper.get("os", ""),
                      "urls": helper.get("urls", []), "url": h.get("url", ""),
                      "up": bool(h.get("up")) and not down, "matched": ok,
                      "why": h.get("why", "") if down else why,
                      "busy": bool((h.get("info") or {}).get("busy"))})
    return {"this": {"name": server_name(), "os": os_name(), "role": "primary",
                     "urls": candidate_urls(port), "model": model,
                     "log": str(logs.path())},
            "hosts": hosts, "order": data["order"]}


def _busy() -> bool:
    from assistant import model_protocol
    return model_protocol.local_busy()


def register(app) -> None:
    @app.get("/servers")
    def servers():
        port = int(request.environ.get("SERVER_PORT") or 8080)
        return jsonify(snapshot(port))

    @app.get("/servers/found")
    def servers_found():
        if os.environ.get("MACALENDAR_NO_DISCOVERY"):
            return jsonify({"found": []})
        from assistant.pairing import discovery
        used = {u for h in store.load()["helpers"].values() for u in h.get("urls", [])}
        found = [f for f in discovery.browse(discovery.HELPER_SERVICE)
                 if not set(f.get("urls", [])) & used]
        return jsonify({"found": found})

    @app.post("/servers/helpers")
    def servers_add():
        if (bad := _local_only()) is not None:
            return bad
        import requests
        from assistant.pairing.addresses import server_name
        b = request.get_json(silent=True) or {}
        urls = [u.rstrip("/") for u in (b.get("urls") or []) if isinstance(u, str) and u]
        code = str(b.get("code") or "")
        if not urls or not code:
            return _err("urls and the code shown on the helper are required", 400)
        last = "not reachable"
        for url in urls:
            try:
                r = requests.post(f"{url}/gate/claim", json={"code": code, "primary": server_name()},
                                  timeout=5)
            except requests.RequestException as exc:
                last = f"{url}: {type(exc).__name__}"
                continue
            if r.status_code != 200:
                return _err((r.json() or {}).get("error", f"the helper said {r.status_code}"), 403)
            got = r.json()
            hid = store.add(got.get("name") or url, got.get("os", ""), urls, got["token"])
            threading.Thread(target=router.refresh, args=(_cfg().ollama.base_url,),
                             daemon=True).start()
            logger.info("🧠 Model helper %s (%s) added", got.get("name"), got.get("os"))
            return jsonify({"id": hid, "name": got.get("name"), "os": got.get("os")})
        return _err(f"couldn't reach the helper ({last})", 502)

    @app.delete("/servers/helpers/<hid>")
    def servers_remove(hid: str):
        if (bad := _local_only()) is not None:
            return bad
        gone = store.remove(hid)
        if gone is None:
            return _err("no such helper", 404)
        import requests
        for url in gone.get("urls", []):             # best effort: tell it to forget us
            try:
                requests.post(f"{url}/gate/release",
                              headers={"Authorization": f"Bearer {gone.get('token', '')}"},
                              timeout=2)
                break
            except requests.RequestException:
                continue
        return jsonify({"removed": hid})

    @app.put("/servers/order")
    def servers_order():
        if (bad := _local_only()) is not None:
            return bad
        order = (request.get_json(silent=True) or {}).get("order")
        if not isinstance(order, list) or not store.set_order([str(o) for o in order]):
            return _err("order must list exactly the current machines", 400)
        return jsonify({"order": store.load()["order"]})

    @app.get("/servers/logs")
    def servers_logs():
        from assistant.host import logs
        from assistant.users import registry
        if not is_local() and registry.exists():
            from assistant.users.routes import _need_admin
            _uid, err = _need_admin()
            if err:
                return err
        try:
            n = int(request.args.get("lines", 200))
        except ValueError:
            n = 200
        return jsonify({"file": str(logs.path()), "lines": logs.tail(lines=n)})

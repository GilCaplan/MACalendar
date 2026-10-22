"""`python -m assistant.sync status | reconcile [--apply] [--hub URL]`

`reconcile` is the first sync of a machine whose file already has a life of
its own: it prints, per table, what only this machine has (sent up), what
only the hub has (taken), and rows changed on both (the hub's kept). Nothing
moves without `--apply`, and `--apply` backs the file up first.
"""
from __future__ import annotations

import argparse
import socket
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assistant.sync")
    ap.add_argument("cmd", choices=["status", "reconcile"])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hub", default="")
    a = ap.parse_args(argv)

    from assistant.config import load_config
    from assistant.db import get_db
    from assistant.sync.replica import Replica, http_transport
    cfg = load_config()
    hub = a.hub or cfg.sync.hub
    if not hub:
        print("no hub: set sync.hub in config.yaml or pass --hub", file=sys.stderr)
        return 2
    rep = Replica(get_db().path, cfg.sync.replica_name or socket.gethostname(),
                  http_transport(hub, cfg.sync.api_key, timeout=60))
    print(f"file    {rep.path}\nhub     {hub}\nreplica {rep.name}")
    if a.cmd == "status":
        print(f"cursor  {rep.cursor()}\npending {rep.pending()} rows waiting to go up")
        return 0
    plan = rep.reconcile_plan()
    if not plan["tables"]:
        print("the two copies already agree")
    for t, p in plan["tables"].items():
        print(f"{t:24} same {p['same']:>4} | send {len(p['mac_only']):>3} | take {len(p['hub_only']):>3}"
              f" | same id, different row: send as new {len(p['different_rows_same_id']):>3}"
              f" | changed on both, hub's kept {len(p['edited_both']):>3}")
    if not a.apply:
        print("\n(dry run — add --apply to make it)")
        return 0
    rep.reconcile(plan)
    print(f"\ndone: cursor {rep.cursor()}, pending {rep.pending()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

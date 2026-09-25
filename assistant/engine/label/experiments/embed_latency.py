"""How long the embedding head adds to a commit — one title, warm and cold.

    python -m assistant.engine.label.experiments.embed_latency            # 200 + 200
    python -m assistant.engine.label.experiments.embed_latency -n 50

A label is written at COMMIT time, so the number that matters is one title
through the real client (`embed.vector`: the gate, the socket, the model), with
the in-process cache cleared before every call.

    WARM   the model resident — the ordinary case, KEEP_ALIVE keeps it there
    COLD   the model unloaded (`keep_alive: 0`) before every call — the first
           label after ollama restarted or the model was evicted

Also checks that a vector fetched ONE title at a time matches the one the
trainer fetched in a batch (the artefact was fitted on batched vectors).

**Say which priority you measured.** The default here is background, and a
background `hold()` sleeps 30 ms after every release (the yield gap that lets
a waiting board in) — so a background run reads ~30 ms slower than a commit.
`MACALENDAR_LLM_PRIORITY=live` measures what a live command pays; keep it
short, it competes with the assistant while it runs.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

from assistant.common.scratch_env import scratch_env

_S = pathlib.Path(scratch_env(
    "embed_latency_", keep=("LOCATION", "HEARTBEATS", "HUD_STATE",
                            "DEVICE_SECRET", "DEVICES")))

import argparse      # noqa: E402
import json          # noqa: E402
import time          # noqa: E402

import numpy as np   # noqa: E402

STAGE = pathlib.Path(__file__).resolve().parents[1]


def _unload(url: str) -> None:
    import urllib.request
    from assistant import model_protocol
    from assistant.engine.label import embed as E
    body = json.dumps({"model": E.MODEL, "input": [], "keep_alive": 0}).encode()
    with model_protocol.hold():
        with urllib.request.urlopen(urllib.request.Request(
                f"{url}/api/embed", data=body,
                headers={"Content-Type": "application/json"}), timeout=30) as r:
            r.read()
    time.sleep(0.3)


def _pct(xs):
    a = np.array(xs)
    return f"p50 {np.percentile(a, 50):7.1f} ms · p95 {np.percentile(a, 95):7.1f} ms · max {a.max():7.1f} ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--batch-cache", default=str(pathlib.Path(tempfile.gettempdir())
                                                  / "macalendar_label_embed_cache.jsonl"))
    a = ap.parse_args()
    from assistant.engine.label import embed as E
    E.TIMEOUT_S = 60.0                  # measure the call, do not cut it off
    url = E.DEFAULT_URL
    rows = [json.loads(l) for l in (STAGE / "datasets" / "event_categories.jsonl").open()]
    titles = sorted({r["text"] for r in rows if r["split"] == "test"})
    rng = np.random.default_rng(0)
    titles = [titles[i] for i in rng.choice(len(titles), size=2 * a.n, replace=False)]
    print(f"\nEMBED LATENCY · {time.strftime('%Y-%m-%d %H:%M:%S')} · {E.MODEL} · "
          f"one title per call through embed.vector (gate included), cache cleared each call")

    E.reset()
    E.vector("warm-up call")
    warm = []
    for t in titles[:a.n]:
        E.reset()
        t0 = time.perf_counter()
        v = E.vector(t)
        warm.append((time.perf_counter() - t0) * 1000)
        assert v is not None, "embedding failed during the warm run"
    print(f"  WARM  n={len(warm)}  {_pct(warm)}")

    cold = []
    for i, t in enumerate(titles[a.n:]):
        _unload(url)
        E.reset()
        t0 = time.perf_counter()
        v = E.vector(t)
        cold.append((time.perf_counter() - t0) * 1000)
        if v is None:
            print(f"  cold call {i} failed")
    print(f"  COLD  n={len(cold)}  {_pct(cold)}   (model unloaded before every call)")
    E.vector("reload")                  # leave it resident

    # single-call vectors vs the batched ones the artefact was fitted on
    p = pathlib.Path(a.batch_cache)
    if p.exists():
        have = {}
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            have[r["t"]] = r["v"]
        common = [t for t in titles[:a.n] if t in have][:100]
        if common:
            diffs, cos = [], []
            for t in common:
                E.reset()
                s = E.vector(t)
                b = np.asarray(have[t], dtype=np.float32)
                b /= np.linalg.norm(b)
                diffs.append(float(np.abs(s - b).max()))
                cos.append(float(s @ b))
            print(f"  single vs batched vectors, {len(common)} titles: max |diff| "
                  f"{max(diffs):.2e}, min cosine {min(cos):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

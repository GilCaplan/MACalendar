"""KIND ROUTER — fit and measure "basic rules, otherwise model".

    ./.venv/bin/python -m assistant.engine.decompose_validate.experiments.kind_router_board          # measure
    ./.venv/bin/python -m assistant.engine.decompose_validate.experiments.kind_router_board --fit    # + write the artefact

Gil, 2026-09-24 (DEVQA Q47): *"basic rules, otherwise model"*. The shipped
router is `decompose_validate/kind_router.py`; this board fits its model and
reads it against the incumbent, the tagger (`fastseg.tag`), on the same item
words — per source, per split, with the FIRE RATE (how many items reach the
model at all) beside every number.

Data: the TRAIN halves of FastRule 7,200, LLMJudge v2 and segmentation's corpus
(gold relabelled by rule for Q26/Q47 on 2026-09-24), the loaders and the
leakage rules of `kind_two_stage.py` — a TRAIN item whose words appear in any
TEST set never enters the fit. TRAIN numbers are OUT-OF-FOLD (5 folds grouped
by family); TEST is read once by the model fitted on the whole pool. Real usage
is TEST-only and never fitted on.

Model selection is on TRAIN alone: {logistic regression, HistGradientBoosting}
× {fit on every TRAIN item, fit only on the items no rule decided}, judged by
out-of-fold accuracy on the TRAIN items no rule decided — the only items the
model ever answers.
"""
from __future__ import annotations

import argparse
import collections
import json
import time

from assistant.engine.decompose_validate.experiments import kind_two_stage as K2  # scratch env first

import numpy as np  # noqa: E402

from assistant.engine.decompose_validate import kind_router as KR  # noqa: E402

HERE = K2.HERE

#: Q47 answered (2026-09-24): calling a person is an event, day or no day; a
#: written message, a mention and a named to-do list stay to-dos. Q50
#: (2026-09-25) extended it to a call to a role.
CALL_RULINGS = [
    ("call Mom", "event", "Q47"),
    ("call Mom tomorrow", "event", "Q47"),
    ("remind me to call Morgan tomorrow", "event", "Q47"),
    ("remind me to call Jordan", "event", "Q47"),
    ("phone grandma on sunday", "event", "Q47"),
    ("facetime dad tonight", "event", "Q47"),
    ("catch up with Riley", "event", "Q47"),
    ("email Dana the report", "task", "Q47"),
    ("text Sam tomorrow", "task", "Q47"),
    ("add call mom to my to-do list", "task", "Q47"),
    # Q50 (2026-09-25): a call to a ROLE is an event too — "Two also same
    # thing". Filed with a linked to-do beside it, which is the executor's
    # job; the KIND is event. Was ("call the plumber", "task", "Q47").
    ("call the plumber", "event", "Q50"),
    ("remind me to call the bank tomorrow", "event", "Q50"),
    ("phone my accountant", "event", "Q50"),
    ("email the plumber", "task", "Q50"),
    ("check off call the plumber", "task", "Q50"),
]


def battery() -> list:
    """The 43 sentences of the kind board, with "call Mom" moved to the
    answered Q47, plus the call sentences."""
    out = [(s, ("event" if s == "call Mom" else w), c) for s, w, c in K2.RULINGS
           if s != "call Mom"]
    return out + CALL_RULINGS


def _ruling_conflict(it) -> bool:
    """Gold that a RULING contradicts (a stated clock or an encounter says
    event, gold says task). Read with the rulings' own readers only — never
    with the tagger's other paths, or every tagger error would be dropped."""
    FS = KR._fs()
    from assistant.intent.encounter import is_encounter
    if it["gold"] != "task":
        return False
    t = it["time"] or ""
    clock = FS._STATED_CLOCK.search(t) and not FS._VAGUE_TIME_HEDGE.search(it["text"]) \
        and not FS._DUE_DATE_EDIT.match(it["text"]) and not FS._is_not_calendar(it["text"], t)
    return bool(clock or is_encounter(it["text"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true", help="write models/kind_router.joblib")
    a = ap.parse_args()
    t0 = time.time()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    import subprocess
    head = subprocess.run(["git", "-C", str(K2.ROOT), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    print(f"kind_router_board · started {stamp} · HEAD {head} (working tree)", flush=True)

    fr = K2.load_fastrule()
    fr_split = {}
    for line in K2.FASTRULE.open():
        r = json.loads(line)
        fr_split.setdefault(r["family"], r["split"])
    sources = {"fastrule": fr, "v2": K2.load_v2(), "seg": K2.load_seg(fr_split), "real": K2.load_real()}
    from assistant.intent.cleanup import strip_spoken_noise
    FS = KR._fs()
    items = [it for v in sources.values() for it in v]
    for i, it in enumerate(items):
        if it["src"] != "real":
            it["text"] = strip_spoken_noise(it["text"]) or it["text"]
            it["time"] = strip_spoken_noise(it["time"]) if it["time"] else ""
        it["tagk"], it["path"] = FS.tag_path(it["text"], it["time"])
        it["engine"] = it["tagk"]
        fired = KR.rule_fired(it["text"], it["time"])
        it["reach"] = fired is None and it["tagk"] in KR.KINDS
        it["conflict"] = _ruling_conflict(it)
        if i % 3000 == 0:
            print(f"  {time.strftime('%H:%M:%S')} read {i}/{len(items)}", flush=True)

    test_keys = {(K2._norm(it["text"]), K2._norm(it["time"])) for it in items if it["split"] == "test"}
    pool, seen = [], set()
    for it in items:
        if it["split"] != "train" or it["conflict"]:
            continue
        k = (K2._norm(it["text"]), K2._norm(it["time"]))
        if k in test_keys or k in seen:
            continue
        seen.add(k)
        pool.append(it)
    counts = collections.Counter(KR.head_word(it["text"]) for it in pool)
    heads = {h: i for i, (h, c) in enumerate(counts.most_common()) if c >= 5}
    X = KR.vectorise([(it["text"], it["time"], it["tagk"]) for it in pool], heads)
    y = np.array([it["gold"] == "event" for it in pool], dtype=int)
    groups = np.array([it["family"] for it in pool])
    reach = np.array([it["reach"] for it in pool])
    print(f"  TRAIN pool {len(pool)} items · {len(set(groups))} families · "
          f"{int(reach.sum())} reach the model ({100 * reach.mean():.1f}%) · {len(heads)} head words", flush=True)

    from sklearn.model_selection import GroupKFold
    folds = list(GroupKFold(n_splits=5).split(X, y, groups))
    cands = {}
    for mname in ("lr", "hgb"):
        for scope in ("all", "reach"):
            oof = np.full(len(pool), np.nan)
            for tr, te in folds:
                tr = tr[reach[tr]] if scope == "reach" else tr
                m = K2.make_model(mname).fit(X[tr], y[tr])
                oof[te] = m.predict_proba(X[te])[:, 1]
            r = reach
            acc = float(((oof[r] >= 0.5).astype(int) == y[r]).mean())
            cands[(mname, scope)] = (acc, oof)
            print(f"    candidate {mname:3s} fit-on-{scope:5s}  OOF accuracy on reached TRAIN items "
                  f"{100 * acc:.1f}% (n={int(r.sum())})", flush=True)
    eng_reach = float(np.mean([it["tagk"] == it["gold"] for it in pool if it["reach"]]))
    print(f"    tagger on the same reached items {100 * eng_reach:.1f}%")
    (mname, scope), (best_acc, oof) = max(cands.items(), key=lambda kv: kv[1][0])
    print(f"  CHOSEN {mname} fit-on-{scope} (TRAIN OOF only)", flush=True)
    fit_idx = np.where(reach)[0] if scope == "reach" else np.arange(len(pool))
    model = K2.make_model(mname).fit(X[fit_idx], y[fit_idx])
    blob = {"model": model, "heads": heads, "feature_version": KR.FEATURE_VERSION,
            "meta": {"trained_at": stamp, "git_head": head, "model": mname, "fit_on": scope,
                     "n_pool": len(pool), "n_fit": int(len(fit_idx)),
                     "oof_reached_acc": round(best_acc, 4), "tagger_reached_acc": round(eng_reach, 4),
                     "sources": "FastRule 7,200 + LLMJudge v2 + segmentation corpus, TRAIN halves",
                     "features": KR.feature_names(heads)}}
    if a.fit:
        import joblib
        KR.MODEL_PATH.parent.mkdir(exist_ok=True)
        joblib.dump(blob, KR.MODEL_PATH)
        KR.reset()
        print(f"  wrote {KR.MODEL_PATH}", flush=True)

    # THE RULES OFF (Gil, 2026-09-24: "isolate the rule based on/off just to
    # see the effect"). The same model family, fitted on EVERY item and asked
    # about every item — no rule decides anything. Beside "tagger" (rules
    # alone) and "router" (rules, otherwise model) it separates what the rules
    # are worth from what the model is worth. TRAIN is out-of-fold, TEST is
    # read by the model fitted on the whole pool, exactly like the router.
    _acc_all, oof_all = cands[(mname, "all")]
    model_all = K2.make_model(mname).fit(X, y)
    oof_all_by_id = {id(it): oof_all[i] for i, it in enumerate(pool)}
    # …and STRICTER: the model above still reads the tagger's verdict (the
    # last three features, eng_event/eng_task/eng_other). "Words only" drops
    # them, so no rule reaches the decision even as an input.
    NW = X.shape[1] - 3
    oof_w = np.full(len(pool), np.nan)
    for tr, te in folds:
        oof_w[te] = K2.make_model(mname).fit(X[tr, :NW], y[tr]).predict_proba(X[te, :NW])[:, 1]
    model_w = K2.make_model(mname).fit(X[:, :NW], y)
    oof_w_by_id = {id(it): oof_w[i] for i, it in enumerate(pool)}

    # --- the board: router vs tagger, per source and split
    oof_by_id = {id(it): oof[i] for i, it in enumerate(pool)}
    record = {"started": stamp, "git_head": head, "chosen": f"{mname}:{scope}",
              "candidates": {f"{k[0]}:{k[1]}": v[0] for k, v in cands.items()}, "rows": {}}
    print("\n  KIND — rules alone (tagger) · words only (no rule even as input) · model alone (rules OFF, "
          "reads the tagger's verdict as a feature) · rules, otherwise model (router)")
    print(f"    {'source':9s} {'split':5s} {'n':>6s} {'reach':>12s} {'tagger':>8s} {'words':>8s} {'model':>8s} {'router':>8s} "
          f"{'fixed':>6s} {'broke':>6s} {'net':>5s}   on reached: tagger→router")
    for s, its in sources.items():
        for sp in ("train", "test"):
            sub = [it for it in its if it["split"] == sp and not it["conflict"]]
            if sp == "train":
                sub = [it for it in sub if id(it) in oof_by_id]
            if not sub:
                continue
            reached = [it for it in sub if it["reach"]]
            if sp == "train":
                p = {id(it): oof_by_id[id(it)] for it in reached}
            else:
                P = model.predict_proba(KR.vectorise([(it["text"], it["time"], it["tagk"]) for it in reached],
                                                     heads))[:, 1] if reached else []
                p = {id(it): v for it, v in zip(reached, P)}
            pred = [("event" if p[id(it)] >= 0.5 else "task") if it["reach"] else it["tagk"] for it in sub]
            if sp == "train":
                p_all = [oof_all_by_id[id(it)] for it in sub]
            else:
                p_all = model_all.predict_proba(KR.vectorise(
                    [(it["text"], it["time"], it["tagk"]) for it in sub], heads))[:, 1]
            m_ok = sum(("event" if v >= 0.5 else "task") == it["gold"] for v, it in zip(p_all, sub))
            if sp == "train":
                p_w = [oof_w_by_id[id(it)] for it in sub]
            else:
                p_w = model_w.predict_proba(KR.vectorise(
                    [(it["text"], it["time"], it["tagk"]) for it in sub], heads)[:, :NW])[:, 1]
            w_ok = sum(("event" if v >= 0.5 else "task") == it["gold"] for v, it in zip(p_w, sub))
            n = len(sub)
            eng_ok = sum(it["tagk"] == it["gold"] for it in sub)
            ok = sum(x == it["gold"] for x, it in zip(pred, sub))
            fixed = sum(x == it["gold"] and it["tagk"] != it["gold"] for x, it in zip(pred, sub))
            broke = sum(x != it["gold"] and it["tagk"] == it["gold"] for x, it in zip(pred, sub))
            rn = len(reached)
            r_eng = sum(it["tagk"] == it["gold"] for it in reached)
            r_ok = sum(x == it["gold"] for x, it in zip(pred, sub) if it["reach"])
            conf = sum(1 for it in its if it["split"] == sp and it["conflict"])
            print(f"    {s:9s} {sp:5s} {n:6d} {rn:5d} {100 * rn / n:5.1f}% {100 * eng_ok / n:7.1f}% "
                  f"{100 * w_ok / n:7.1f}% {100 * m_ok / n:7.1f}% {100 * ok / n:7.1f}% {fixed:6d} {broke:6d} {fixed - broke:+5d}   "
                  + (f"{100 * r_eng / rn:.1f}% → {100 * r_ok / rn:.1f}%" if rn else "—")
                  + (f"   ({conf} ruling-conflict gold dropped)" if conf else ""))
            record["rows"][f"{s}|{sp}"] = {"n": n, "reach": rn, "tagger": eng_ok, "words_only": w_ok, "model_only": m_ok,
                                           "router": ok,
                                           "fixed": fixed, "broke": broke, "conflicts_dropped": conf,
                                           "families": len({it["family"] for it in sub})}

    # paths that reach the model, and what the tagger's paths are worth (TRAIN)
    by_path = collections.Counter((it["path"], it["tagk"] == it["gold"]) for it in pool)
    print("\n  TRAIN pool by the tagger's path (n · tagger right):")
    for path in sorted({p for p, _ in by_path}, key=lambda p: -(by_path[(p, True)] + by_path[(p, False)])):
        n = by_path[(path, True)] + by_path[(path, False)]
        print(f"    {path:22s} {n:6d}  {100 * by_path[(path, True)] / n:5.1f}%")

    # rulings battery
    from assistant.engine.segmentation.fastseg.fastseg import fastseg
    print(f"\n  RULINGS battery ({len(battery())} sentences: Q25/Q26/Q27/Q47/Q1 + the 2026-09-04 convention + calls)")
    viol_t, viol_r, viol_m, viol_w, reached_n = [], [], [], [], 0
    for sent, want, cite in battery():
        segs = fastseg(sent)
        sg = segs[0] if segs else {"action": sent, "time": ""}
        kind, why = KR.route(sg["action"], sg["time"] or "", model=blob)
        reached_n += why.startswith("model:")
        tk = FS.tag(sg["action"], sg["time"] or "")
        if tk != want:
            viol_t.append((sent, cite, tk))
        if kind != want:
            viol_r.append((sent, cite, kind, why))
        pm = float(model_all.predict_proba(KR.vectorise([(sg["action"], sg["time"] or "", tk)], heads))[0, 1])
        if ("event" if pm >= 0.5 else "task") != want:
            viol_m.append((sent, cite, round(pm, 2)))
        pw = float(model_w.predict_proba(KR.vectorise([(sg["action"], sg["time"] or "", tk)], heads)[:, :NW])[0, 1])
        if ("event" if pw >= 0.5 else "task") != want:
            viol_w.append((sent, cite, round(pw, 2)))
    n = len(battery())
    print(f"    tagger {n - len(viol_t)}/{n}  violations {viol_t}")
    print(f"    words only (no rule, not even as input) {n - len(viol_w)}/{n}  violations {viol_w}")
    print(f"    model alone (rules OFF) {n - len(viol_m)}/{n}  violations {viol_m}")
    print(f"    router {n - len(viol_r)}/{n}  violations {viol_r}  · {reached_n} reached the model")
    record["battery"] = {"n": n, "tagger_ok": n - len(viol_t), "router_ok": n - len(viol_r),
                         "reached_model": reached_n, "router_violations": viol_r,
                         "model_only_ok": n - len(viol_m), "model_only_violations": viol_m,
                         "words_only_ok": n - len(viol_w), "words_only_violations": viol_w}

    out = HERE / "runs"
    out.mkdir(exist_ok=True)
    pth = out / f"kind_router_{time.strftime('%Y%m%dT%H%M')}.json"
    pth.write_text(json.dumps(record, indent=1, default=str))
    print(f"\n  finished {time.strftime('%Y-%m-%d %H:%M:%S')} ({(time.time() - t0) / 60:.1f} min) · record: {pth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

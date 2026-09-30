"""The learned labellers on the phone (`engine/label/export.py`,
`LabelModel.swift`, `CategoryClassifier.swift`), and the typed-task gap.

The phone could run neither label model: each is a pickled sklearn pipeline,
and the half that answers on the Mac reads an ollama embedding. Its n-gram
half is served as data instead and the phone does the arithmetic — so the
payload, the reference inference and the Swift port are each held here to
what the Mac computes, over every title the label datasets hold (19k+
distinct strings), not a handful.

And the Mac's own create endpoint had the rules alone: `POST /todos` — every
task the phone types, and every one it queued offline — never asked the tag
model voice creation asked.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from assistant.engine.label import export as X
from assistant.engine.label import model as M

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATASETS = ROOT / "assistant/engine/label/datasets"


def _cfg(event=True, task=True, first=False):
    return SimpleNamespace(labels=SimpleNamespace(model_event=event, model_task=task,
                                                  model_first=first))


def _corpus() -> list:
    """Every title and subject the two label datasets hold, plus the shapes a
    dataset never has: punctuation, Hebrew, accents, emoji, runs of spaces."""
    out = set()
    for name in ("event_categories", "task_tags"):
        for line in (DATASETS / f"{name}.jsonl").read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                out.update((row["text"], row["subject"]))
    out.update([
        "", "   ", "Pick up dry-cleaning!", "dinner,  with Avi", "gym\twith dan",
        "Mom's birthday", "re-schedule the re-schedule", "café with Zoë", "שבת dinner",
        "ארוחת שבת", "buy milk 🥛 and eggs", "x", "a b c", "TEAM standup 9:30",
        "éclair", "don't forget ‑ the ‘rent’", "10k run", "C++ homework",
    ])
    return sorted(out)


def _sklearn(model, titles) -> np.ndarray:
    if model.kind == "event":
        return model.pipeline.predict_proba(titles)
    feats = model.pipeline.named_steps["feat"].transform(titles)
    return np.column_stack([e.predict_proba(feats)[:, 1]
                            for e in model.pipeline.named_steps["clf"].estimators_])


# ---------------------------------------------------------------------------
# The payload and the reference inference
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", X.KINDS)
def test_the_payload_alone_reproduces_sklearn(kind):
    """`ngram_proba` reads nothing but the served payload — so if it agrees
    with sklearn, the payload is complete and the recipe is right."""
    payload = X.export(kind, _cfg())
    model = M.LabelModel.load(kind)
    titles = _corpus()
    ref = np.array([X.ngram_proba(payload, t) for t in titles])
    diff = np.abs(ref - _sklearn(model, titles))
    assert diff.max() < 1e-5, f"worst {titles[int(diff.max(axis=1).argmax())]!r}: {diff.max()}"
    assert payload["classes"] == ([str(c) for c in model.pipeline.classes_]
                                  if kind == "event" else model.classes)


@pytest.mark.parametrize("kind", X.KINDS)
def test_the_bar_is_the_one_the_mac_holds_the_ngram_half_to(kind):
    """The phone never has the vector, so it is always the fallback — and the
    bar comes from `ngram_bar`, the same function the Mac's predict uses."""
    assert X.export(kind, _cfg())["bar"] == M.LabelModel.load(kind).ngram_bar()


def test_the_switches_travel_and_move_the_rev():
    on, off, first = (X.export("task", c) for c in (_cfg(), _cfg(task=False), _cfg(first=True)))
    assert (on["enabled"], off["enabled"], first["model_first"]) == (True, False, True)
    assert len({on["rev"], off["rev"], first["rev"]}) == 3
    assert X.export("task", _cfg())["rev"] == on["rev"]       # stable for the same model


def test_a_vectoriser_the_phone_cannot_reproduce_is_refused(monkeypatch):
    """A retrain with different settings must fail HERE, not serve numbers the
    phone computes differently."""
    model = M.LabelModel.load("task")
    vec = dict(model.pipeline.named_steps["feat"].transformer_list)["word"]
    monkeypatch.setattr(vec, "binary", True)
    with pytest.raises(X.UnsupportedModel):
        X._model_part(model)


def test_an_unknown_kind_has_no_payload():
    assert X.export("mood", _cfg()) is None


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_DB", str(tmp_path / "cal.db"))
    import assistant.db as _db
    monkeypatch.setattr(_db, "_db_instance", None)
    from assistant.api import server
    from assistant.config import LabelsConfig
    # The loaded config with only `labels` swapped: CI's has the models off.
    cfg = server.load_config().model_copy(
        update={"labels": LabelsConfig(model_event=True, model_task=True)})
    monkeypatch.setattr(server, "load_config", lambda *a, **k: cfg)
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_the_model_route_serves_once_then_says_unchanged(client):
    full = client.get("/labels/model/task").get_json()
    assert full["kind"] == "task" and full["coef"] and full["rev"]
    again = client.get(f"/labels/model/task?have={full['rev']}").get_json()
    assert again == {"kind": "task", "rev": full["rev"], "unchanged": True}
    assert client.get("/labels/model/task?have=stale").get_json()["coef"] == full["coef"]
    assert client.get("/labels/model/mood").status_code == 404


def test_the_category_table_is_served_and_rides_the_bootstrap(client):
    from assistant.actions.calendar import categories as C
    rules = client.get("/categories/rules").get_json()
    assert [c["name"] for c in rules["categories"]] == [c["name"] for c in C.all_categories()]
    assert set(rules) == {"categories", "people", "rev"}
    boot = client.get("/sync/bootstrap?year=2026&month=9").get_json()
    assert boot["category_rules"]["rev"] == rules["rev"]


def test_a_typed_task_gets_the_model_where_the_rules_are_silent(client, monkeypatch):
    """POST /todos is the phone's typed task and its offline replay. The rules
    keep every title they answer; the model fills a blank — as voice does."""
    class _Model:
        def predict_tags(self, title):
            return (["Errands"], 0.95)
    monkeypatch.setattr(M, "_cached", lambda kind: _Model())
    silent = client.post("/todos", json={"title": "sort out the thing", "tags": []}).get_json()
    fired = client.post("/todos", json={"title": "buy milk", "tags": []}).get_json()
    said = client.post("/todos", json={"title": "fix bike", "tags": ["Work"]}).get_json()
    from assistant.db import get_db
    db = get_db()
    assert db.get_todo(silent["id"])["tags"] == ["Errands"]
    assert db.get_todo(fired["id"])["tags"] == ["Groceries"]
    assert db.get_todo(said["id"])["tags"] == ["Work"]


def test_the_store_infers_with_the_model_too(tmp_path, monkeypatch):
    """`db.create_todo(tags=None)` — calendar sync, the planners, a rename —
    is the third way a task arrives, and it asks the same labeller."""
    class _Model:
        def predict_tags(self, title):
            return (["Errands"], 0.95)
    monkeypatch.setattr(M, "_cached", lambda kind: _Model())
    import assistant.config as config
    monkeypatch.setattr(config, "load_config", lambda *a, **k: _cfg())
    from assistant.db import CalendarDB
    db = CalendarDB(str(tmp_path / "store.db"))
    silent, fired = db.create_todo("sort out the thing"), db.create_todo("buy milk")
    chosen = db.create_todo("sort out the thing", tags=[])
    assert db.get_todo(silent)["tags"] == ["Errands"]
    assert db.get_todo(fired)["tags"] == ["Groceries"]
    assert db.get_todo(chosen)["tags"] == []              # "chosen to be none" stays none


def test_voice_and_the_endpoint_share_one_labeller():
    """`auto_tags` is the one definition; `cfg=None` is rules only."""
    from assistant.actions.todo import action, tagging
    assert action.auto_tags is tagging.auto_tags
    assert tagging.auto_tags("buy milk", None, None) == tagging.suggest_tags("buy milk")


# ---------------------------------------------------------------------------
# The Swift port, against the Mac
# ---------------------------------------------------------------------------

_PEOPLE = ["avi", "dana", "noa"]


class _Batched:
    """A fitted pipeline's answers for known titles, looked up rather than
    recomputed one title at a time (sklearn spends 1-2 ms a call on overhead,
    and the oracle below makes tens of thousands). Shaped like the two ways
    `LabelModel` reads a pipeline: `predict_proba` for events, and
    `named_steps` feat → one-vs-rest estimators for tasks."""

    class _Est:
        def __init__(self, table, i):
            self.table, self.i = table, i

        def predict_proba(self, title):
            p = self.table[title][self.i]
            return [[1 - p, p]]

    def __init__(self, real, titles, proba):
        self.classes_ = getattr(real, "classes_", None)
        self.table = {t: list(row) for t, row in zip(titles, proba)}
        clf = SimpleNamespace(estimators_=[self._Est(self.table, i) for i in range(proba.shape[1])])
        self.named_steps = {"feat": SimpleNamespace(transform=lambda texts: texts[0]), "clf": clf}

    def predict_proba(self, texts):
        return [self.table[texts[0]]]


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"),
                    reason="needs the Swift compiler (the Mac; CI's Linux runner has none)")
def test_the_phone_labels_every_title_as_the_mac_does(tmp_path, monkeypatch):
    """Every title in the label datasets, through LabelModel.swift and
    CategoryClassifier.swift, against sklearn, `categories.classify` and
    `category_for` / `tags_for` with the embedding unavailable — which is
    exactly the Mac's answer with ollama down, the phone's permanent state."""
    from assistant.actions.calendar import categories as C
    from assistant.actions.todo import tagging as T
    monkeypatch.setattr(C, "people_words", lambda: list(_PEOPLE))
    cfg = _cfg()
    event, task = M.LabelModel.load("event"), M.LabelModel.load("task")
    palette = list(T.KEYWORDS) + ["Personal"]
    rules = {"categories": [{"name": c["name"], "color": c["color"], "alt": c.get("alt", c["color"]),
                             "keywords": c["keywords"]} for c in C.all_categories()],
             "people": list(_PEOPLE), "rev": "test"}
    setup = tmp_path / "setup.json"
    setup.write_text(json.dumps({"event": X.export("event", cfg), "task": X.export("task", cfg),
                                 "category_rules": rules, "palette": palette}))
    exe = tmp_path / "parity"
    subprocess.run(["swiftc", "-O", "-parse-as-library",
                    str(ROOT / "assistant/engine/label/experiments/phone_parity.swift"),
                    str(ROOT / "MACalendar-iOS/MACalendar-iOS/LabelModel.swift"),
                    str(ROOT / "MACalendar-iOS/MACalendar-iOS/CategoryClassifier.swift"),
                    "-o", str(exe)], check=True, capture_output=True)

    titles = _corpus()
    # Every fifth title also carries the other fields classify reads, so the
    # attendee, location and description paths are exercised too.
    extras = [("Avi, Dana", "", "") if i % 15 == 0 else ("", "the gym", "") if i % 15 == 5
              else ("", "", "Erev Shabbat, dinner with noa") if i % 15 == 10 else ("", "", "")
              for i in range(len(titles))]
    rows = [{"title": t, "attendees": a, "location": l, "description": d,
             "rule_tags": T.suggest_tags(t, palette)}
            for t, (a, l, d) in zip(titles, extras)]
    proc = subprocess.run([str(exe), str(setup)], input="\n".join(json.dumps(r) for r in rows) + "\n",
                          capture_output=True, text=True, check=True)
    got = [json.loads(l) for l in proc.stdout.splitlines()]
    assert len(got) == len(rows)

    pe, pt = _sklearn(event, titles), _sklearn(task, titles)
    worst = max(float(np.abs(np.array(g["pe"]) - pe[i]).max()) for i, g in enumerate(got))
    assert worst < 1e-5, f"event probabilities differ by {worst}"
    worst = max(float(np.abs(np.array(g["pt"]) - pt[i]).max()) for i, g in enumerate(got))
    assert worst < 1e-5, f"task probabilities differ by {worst}"

    # The oracle's own code path — `predict` / `predict_tags`, the bar, the
    # stacking — runs unchanged; only sklearn's per-title overhead is skipped,
    # by answering from the batch the same pipelines computed above.
    monkeypatch.setattr(M, "_CACHE", {"event": event, "task": task})
    monkeypatch.setattr(event, "pipeline", _Batched(event.pipeline, titles, pe))
    monkeypatch.setattr(task, "pipeline", _Batched(task.pipeline, titles, pt))
    monkeypatch.setattr(M, "_live_tags", lambda names: [
        {p.lower(): p for p in palette}[n.lower()] for n in names if n.lower() in {p.lower() for p in palette}])
    rule_off, cat_off, tag_off = [], [], []
    for r, g in zip(rows, got):
        rule = C.classify(r["title"], r["attendees"], r["location"], r["description"])
        if g["rule"] != rule:
            rule_off.append((r["title"], r["attendees"], r["location"], r["description"], g["rule"], rule))
        want = M.category_for(r["title"], rule, cfg)[0]
        if g["category"] != want:
            cat_off.append((r["title"], g["category"], want))
        want = M.tags_for(r["title"], r["rule_tags"], cfg)[0]
        if g["tags"] != want:
            tag_off.append((r["title"], g["tags"], want))
    assert not rule_off, f"{len(rule_off)}/{len(rows)} rule categories differ: {rule_off[:5]}"
    assert not cat_off, f"{len(cat_off)}/{len(rows)} stacked categories differ: {cat_off[:5]}"
    assert not tag_off, f"{len(tag_off)}/{len(rows)} stacked tags differ: {tag_off[:5]}"

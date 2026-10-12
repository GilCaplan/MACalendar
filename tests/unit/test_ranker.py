"""Ranker: read a table, read a picture's numbers, rank by a recipe.

The table fixture is 40 rows of INVENTED numbers in the shape of a game's
migration export (Gil, 2026-10-12: his real data never goes on GitHub); the
picture is DRAWN here — real screenshots stay out of the repo too.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest
from flask import Flask

from assistant.features import registry
from assistant.features.ranker import ocr, rank, table

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "ranker" / "kingdoms_synthetic.html"


def test_ranker_is_registered():
    f = registry.get("ranker")
    assert f is not None and f.label == "Ranker" and f.order == 45


# ---------------------------------------------------------------- tables

@pytest.fixture(scope="module")
def migration():
    return table.read(FIX.name, FIX.read_bytes())


def test_the_migration_export_reads_with_its_names_labels_and_precision(migration):
    assert len(migration.rows) == 40                    # the filter-box row is not a row
    assert migration.names[:3] == ["Kingdom", "PlayerRank", "Players"]
    assert migration.label("Burned24h") == "🔥 24h"
    first = migration.rows[0]
    assert first["Kingdom"] == 1 and first["Players"] == 3210
    assert first["InactivePercent"] == pytest.approx(12.487123794555664)   # data-raw, not the shown 12
    assert first["Top50Power"] == pytest.approx(2.75e9)                    # shown 2.75B beats data-raw 0


@pytest.mark.parametrize("text,value", [("3.62B", 3.62e9), ("850M", 8.5e8), ("1,234", 1234),
                                        ("12%", 12), ("-4.5", -4.5), ("abc", None), ("", None)])
def test_number(text, value):
    assert table.number(text) == (pytest.approx(value) if value is not None else None)


def test_csv_tsv_and_json_read_the_same():
    csv_t = table.read("t.csv", b"K,Players\n1,10\n2,20\n")
    tsv_t = table.read("t.tsv", b"K\tPlayers\n1\t10\n2\t20\n")
    json_t = table.read("t.json", json.dumps([{"K": 1, "Players": 10}, {"K": 2, "Players": 20}]).encode())
    for t in (csv_t, tsv_t, json_t):
        assert t.names == ["K", "Players"] and [r["Players"] for r in t.rows] == [10, 20]


def test_a_file_with_no_table_says_so():
    with pytest.raises(table.TableError, match="no table"):
        table.read("x.html", b"<html><body><p>hi</p></body></html>")


# ---------------------------------------------------------------- choosing numbers

def test_only_text_that_is_all_numbers_counts():
    lines = ["Chalice District", "#1172", "#153", "#209 #261", "Ruling Guild: #1169",
             "Conqueror: #232 Sunshine96", "Deal Ends In: 06:00:19", "Migration Deal Limit: 10 / 10",
             "#153", "HIGARA"]
    assert ocr.numbers_in(lines) == [1172, 153, 209, 261]


def test_bare_numbers_only_when_there_are_no_hashed_ones():
    assert ocr.numbers_in(["Kingdoms", "12", "40 41", "Time 10:30"]) == [12, 40, 41]
    assert ocr.numbers_in(["#5", "12"]) == [5]


@pytest.mark.skipif(sys.platform != "darwin" or ocr.engine() != "vision",
                    reason="Apple Vision is the Mac's reader")
def test_vision_reads_a_drawn_grid_of_kingdoms(tmp_path):
    """The shape of the real screenshot: a grid of '#n' labels plus a header
    line holding a number that is NOT in the list."""
    from PIL import Image, ImageDraw, ImageFont
    nums = [1172, 153, 209, 261, 313, 319, 350, 464, 544, 557, 572, 723, 727, 758, 817]
    img = Image.new("RGB", (900, 520), (40, 60, 90))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 30)
    except OSError:
        font = ImageFont.load_default()
    d.text((40, 20), "Ruling Guild: #1169   Deal ends in 06:00:19", fill="white", font=font)
    for i, n in enumerate(nums):
        d.text((60 + (i % 5) * 160, 110 + (i // 5) * 120), f"#{n}", fill="white", font=font)
    p = tmp_path / "grid.png"
    img.save(p)
    assert ocr.numbers_from_images([("grid.png", p.read_bytes())]) == nums


# ---------------------------------------------------------------- ranking

def test_migration_recipe_ranks_and_explains(migration):
    res = rank.rank(migration, rank.MIGRATION)
    rows = res["rows"]
    assert len(rows) == 40 and [r["_rank"] for r in rows] == list(range(1, 41))
    assert rows[0]["_score"] >= rows[-1]["_score"]
    top = rows[0]
    assert set(top["_parts"]) == {"Players", "Burned24h", "Strong"}
    assert top["Strong"] == top["Blessed"] + top["Stars"]
    assert [c["label"] for c in res["columns"]][:2] == ["K", "Players"]


def test_numbers_narrow_the_candidates_and_name_the_missing(migration):
    res = rank.rank(migration, rank.MIGRATION, numbers=[1, 711, "#708", 99999])
    assert {int(r["Kingdom"]) for r in res["rows"]} == {1, 711, 708}
    assert res["missing"] == ["99999"]


def test_percentiles_make_scale_irrelevant():
    t = table.Table([("K", "K"), ("big", "big"), ("small", "small")],
                    [{"K": 1, "big": 1e9, "small": 1}, {"K": 2, "big": 2e9, "small": 0}])
    recipe = {"key": "K", "criteria": [{"column": "big", "better": "higher", "weight": 1},
                                       {"column": "small", "better": "higher", "weight": 1}]}
    a, b = rank.rank(t, recipe)["rows"]
    assert a["_score"] == b["_score"] == 50.0


def test_filters_and_weights():
    t = table.Table([("K", "K"), ("x", "x"), ("y", "y")],
                    [{"K": 1, "x": 1, "y": 9}, {"K": 2, "x": 9, "y": 1}, {"K": 3, "x": 5, "y": 5}])
    recipe = {"key": "K", "filters": [{"column": "x", "op": ">=", "value": 2}],
              "criteria": [{"column": "x", "better": "higher", "weight": 3},
                           {"column": "y", "better": "higher", "weight": 1}]}
    rows = rank.rank(t, recipe)["rows"]
    assert [r["K"] for r in rows] == [2, 3]


def test_a_recipe_from_another_table_ranks_by_what_it_can(migration):
    """A saved recipe must not lock Ranker to one export: what a new table
    lacks is left out, with a sentence, and the rest still ranks."""
    other = dict(rank.MIGRATION, criteria=rank.MIGRATION["criteria"] + [
        {"column": "Nope", "better": "higher", "weight": 1}],
        filters=[{"column": "Gone", "op": ">", "value": 1}])
    res = rank.rank(migration, other)
    assert len(res["rows"]) == 40
    assert any("'Nope'" in n for n in res["notes"]) and any("'Gone'" in n for n in res["notes"])
    assert set(res["rows"][0]["_parts"]) == {"Players", "Burned24h", "Strong"}


def test_every_column_shows_unless_the_recipe_narrows_it(migration):
    recipe = {"key": "Kingdom", "criteria": [{"column": "PlayerRank", "better": "lower", "weight": 1}]}
    cols = [c["name"] for c in rank.rank(migration, recipe)["columns"]]
    assert cols[:2] == ["Kingdom", "PlayerRank"] and set(migration.names) <= set(cols)
    narrow = dict(recipe, show=["Kingdom", "Players"])
    assert [c["name"] for c in rank.rank(migration, narrow)["columns"]] == ["Kingdom", "Players"]


def test_the_numbers_find_their_own_column(migration):
    """The picture's numbers are kingdoms; nobody should have to say so."""
    res = rank.rank(migration, {"key": "Players", "criteria": []}, numbers=[1, 711, 708])
    assert res["key"] == "Kingdom" and res["kept"] == 3


def test_no_criteria_keeps_the_table_order(migration):
    rows = rank.rank(migration, {"criteria": []})["rows"]
    assert [r["Kingdom"] for r in rows] == [r["Kingdom"] for r in migration.rows]


# ---------------------------------------------------------------- HTTP

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_RANKER", str(tmp_path / "ranker.json"))
    from assistant.features.ranker.routes import blueprint
    app = Flask(__name__)
    app.register_blueprint(blueprint)
    return app.test_client()


def test_http_round_trip(client):
    first = client.get("/ranker").json
    assert first["preset"] == "My ranking" and first["numbers"] == [] and first["table"] is None
    assert client.post("/ranker/rank", json={}).status_code == 400          # no table yet

    r = client.post("/ranker/rank", data={"table": (io.BytesIO(FIX.read_bytes()), FIX.name),
                                          "numbers": "[1, 711, 708]"},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.json
    assert r.json["kept"] == 3 and r.json["numbers"] == [1, 711, 708]

    # re-rank the remembered table with a different recipe, no file sent
    recipe = {"key": "Kingdom", "criteria": [{"column": "Players", "better": "lower", "weight": 1}]}
    again = client.post("/ranker/rank", json={"recipe": recipe}).json
    assert [int(x["Kingdom"]) for x in again["rows"]] == [711, 708, 1]

    off = client.post("/ranker/rank", json={"use_numbers": False}).json
    assert off["kept"] == 40 and off["numbers"] == [1, 711, 708]            # off keeps the list
    assert client.post("/ranker/rank", json={"use_numbers": True}).json["kept"] == 3
    assert client.put("/ranker/numbers", json={"numbers": []}).json["numbers"] == []
    assert client.post("/ranker/rank", json={}).json["kept"] == 40           # filter off

    saved = client.put("/ranker/presets/Small first", json=recipe).json
    assert saved["preset"] == "Small first" and len(saved["presets"]) == 2
    assert client.delete("/ranker/presets/Small first").status_code == 200
    assert client.delete("/ranker/presets/My ranking").status_code == 409     # keep one

    fresh = client.post("/ranker/new").json                                    # new search
    assert fresh["numbers"] == [] and fresh["table"] is None and len(fresh["presets"]) == 1
    assert client.post("/ranker/rank", json={}).status_code == 400            # nothing to rank yet
    assert client.post("/ranker/numbers").status_code == 400


def test_the_phone_syncs_its_table_and_a_late_replay_changes_nothing(client):
    """The phone reads tables itself and ranks with no Mac (Gil, 2026-10-12:
    "Ranking shouldnt be dependent on the os server… just sync"). It sends the
    table it read as JSON, stamped with when it was chosen; a write queued
    offline and replayed after a newer table was chosen is ignored."""
    assert client.get("/ranker/table").json == {"table": None, "table_at": 0.0}
    t = {"filename": "k.csv", "columns": [{"name": "Kingdom", "label": "Kingdom"},
                                         {"name": "Players", "label": "Players"}],
         "rows": [{"Kingdom": 1.0, "Players": 30.0}, {"Kingdom": 2.0, "Players": 10.0}]}
    put = client.put("/ranker/table", json={"table": t, "table_at": 2000.0})
    assert put.status_code == 200 and put.json["table"]["rows"] == 2 and put.json["table_at"] == 2000.0
    assert client.get("/ranker/table").json["table"] == t
    # the Mac ranks the phone's table without being sent a file
    ranked = client.post("/ranker/rank", json={
        "recipe": {"criteria": [{"column": "Players", "better": "higher", "weight": 1}]}}).json
    assert [r["Kingdom"] for r in ranked["rows"]] == [1.0, 2.0]

    stale = client.put("/ranker/table", json={"table": None, "table_at": 1000.0})
    assert stale.status_code == 200 and stale.json["ignored"] is True
    assert client.get("/ranker/table").json["table"] == t                   # still there

    cleared = client.put("/ranker/table", json={"table": None, "table_at": 3000.0}).json
    assert cleared["table"] is None and cleared["table_at"] == 3000.0
    assert client.put("/ranker/table", json={"table": {"rows": "x"}}).status_code == 400
    assert client.put("/ranker/table", json={}).status_code == 400


def test_the_filter_switch_travels_with_the_number_list(client):
    r = client.put("/ranker/numbers", json={"numbers": [5, 6], "use_numbers": False}).json
    assert r == {"numbers": [5, 6], "use_numbers": False}
    o = client.get("/ranker").json
    assert o["numbers"] == [5, 6] and o["use_numbers"] is False
    # without the switch, the list alone changes and the switch stays
    assert client.put("/ranker/numbers", json={"numbers": [7]}).json["use_numbers"] is False


def test_a_table_chosen_on_the_mac_is_stamped(tmp_path, monkeypatch):
    """The Mac panel writes the store directly; its table must carry a stamp
    newer than the phone's, or the phone would never take it."""
    from assistant.features.ranker import store
    monkeypatch.setenv("MACALENDAR_RANKER", str(tmp_path / "ranker.json"))
    before = store.load()["table_at"]
    data = store.update(last_table={"filename": "a.csv", "columns": [], "rows": []})
    assert data["table_at"] > before
    assert store.new_search()["table_at"] >= data["table_at"]


# ---------------------------------------------------------------- history

T1 = {"filename": "a.csv", "columns": [{"name": "K", "label": "K"}], "rows": [{"K": 1.0}, {"K": 2.0}]}
T2 = {"filename": "b.csv", "columns": [{"name": "K", "label": "K"}], "rows": [{"K": 9.0}]}


def test_a_finished_search_is_kept_in_history(tmp_path, monkeypatch):
    """Gil, 2026-10-12: past searches are kept, to reopen, archive or delete.
    A New search or a different table files the one on screen; the same table
    sent again does not."""
    from assistant.features.ranker import store
    monkeypatch.setenv("MACALENDAR_RANKER", str(tmp_path / "ranker.json"))
    store.update(last_table=T1, numbers=[1])
    store.update(last_table=dict(T1))                       # same table: nothing filed
    assert store.load()["history"] == []
    data = store.update(last_table=T2)                      # a different one: T1 filed
    [e] = data["history"]
    assert e["filename"] == "a.csv" and e["numbers"] == [1] and e["table"]["rows"] == T1["rows"]
    assert not e["archived"]
    data = store.new_search()                               # T2 filed too, newest first
    assert [h["filename"] for h in data["history"]] == ["b.csv", "a.csv"]
    assert data["last_table"] is None


def test_reopening_a_past_search_updates_it_instead_of_copying(tmp_path, monkeypatch):
    from assistant.features.ranker import store
    monkeypatch.setenv("MACALENDAR_RANKER", str(tmp_path / "ranker.json"))
    store.update(last_table=T1, numbers=[1])
    store.new_search()
    hid = store.load()["history"][0]["id"]
    data = store.history_open(hid)
    assert data["last_table"]["rows"] == T1["rows"] and data["numbers"] == [1]
    store.update(numbers=[1, 2])
    data = store.new_search()                               # back in history, once, updated
    assert len(data["history"]) == 1 and data["history"][0]["numbers"] == [1, 2]


def test_history_over_http_archive_delete_and_the_phones_own(client):
    client.put("/ranker/table", json={"table": T1, "table_at": 1.0})
    client.post("/ranker/new")
    [e] = client.get("/ranker/history").json["entries"]
    assert e["rows"] == 2 and "table" not in e                # the list carries no rows
    hid = e["id"]
    assert client.get(f"/ranker/history/{hid}").json["table"]["rows"] == T1["rows"]
    assert client.patch(f"/ranker/history/{hid}", json={"archived": True}).json["archived"] is True
    assert client.patch(f"/ranker/history/{hid}", json={}).status_code == 400
    assert client.patch("/ranker/history/nope", json={"archived": True}).status_code == 404

    phone = {"name": "b.csv", "filename": "b.csv", "table": {"columns": T2["columns"], "rows": T2["rows"]},
             "numbers": [9], "use_numbers": True, "preset": "My ranking", "saved_at": 5.0}
    assert client.put("/ranker/history/phone1", json=phone).json["kept"] is True
    assert client.put("/ranker/history/phone1", json=phone).json["kept"] is True   # replay: idempotent
    assert [x["id"] for x in client.get("/ranker/history").json["entries"]].count("phone1") == 1

    assert client.delete("/ranker/history/phone1").json["deleted"] is True
    assert client.delete("/ranker/history/phone1").status_code == 200              # twice is fine
    listed = client.get("/ranker/history").json
    assert "phone1" in listed["deleted"] and all(x["id"] != "phone1" for x in listed["entries"])
    assert client.put("/ranker/history/phone1", json=phone).json["kept"] is False  # not brought back

    opened = client.post(f"/ranker/history/{hid}/open").json
    assert opened["table"]["rows"] == 2
    assert client.post("/ranker/history/nope/open").status_code == 404


def test_a_table_from_the_phone_does_not_file_a_second_copy(client):
    """The phone files its own history entry, so the Mac must not file the same
    search again when the phone's next table arrives."""
    client.put("/ranker/table", json={"table": T1, "table_at": 1.0})
    client.put("/ranker/table", json={"table": T2, "table_at": 2.0})
    assert client.get("/ranker/history").json["entries"] == []

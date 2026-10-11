"""Ranker: read a table, read a picture's numbers, rank by a recipe.

The table fixture is 40 rows of a real migration export (no player names);
the picture is DRAWN here — the real screenshot carries guild and player names
and stays out of the repo.
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

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "ranker" / "migration_3scrolls.html"


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
    assert first["Kingdom"] == 1 and first["Players"] == 4574
    assert first["InactivePercent"] == pytest.approx(10.013117790222168)   # data-raw, not the shown 10
    assert first["Top50Power"] == pytest.approx(3.62e9)                    # shown 3.62B beats data-raw 0


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


def test_a_recipe_naming_a_missing_column_says_which(migration):
    bad = dict(rank.MIGRATION, criteria=[{"column": "Nope", "better": "higher", "weight": 1}])
    with pytest.raises(rank.RecipeError, match="'Nope'"):
        rank.rank(migration, bad)


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
    assert first["preset"] == rank.MIGRATION["name"] and first["numbers"] == [] and first["table"] is None
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
    assert client.delete(f"/ranker/presets/{rank.MIGRATION['name']}").status_code == 409
    assert client.post("/ranker/numbers").status_code == 400

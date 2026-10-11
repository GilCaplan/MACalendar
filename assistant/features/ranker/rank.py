"""Rank a table's rows by a recipe: keep, combine, score, sort.

A RECIPE (a saved preset) says, in order:

    key        the column holding the identifier the picture's numbers match
    derived    new columns, each the sum of others (Strong ⭐ = Stars150+200+250)
    filters    conditions a row must meet (Scrolls <= 1)
    criteria   what makes a row better: a column, `higher` or `lower` is
               better, and a weight
    show       the columns the result lists

THE SCORE is a weighted average of PERCENTILES, 0-100. Each criterion ranks
the candidates against each other (ties share a rank), so a column measured
in billions and one measured in single digits count only by their weights,
and one extreme kingdom cannot swamp the rest the way a raw sum of values
would. A criterion's percentile is in the result, so "why is this one first"
can be answered by looking.

The NUMBERS from the picture narrow the candidates before anything is ranked,
so a percentile means "against the kingdoms you can actually pick". An empty
list means every row is a candidate.
"""

from __future__ import annotations

from assistant.features.ranker.table import Table, number

OPS = ("<", "<=", ">", ">=", "=", "!=")


class RecipeError(ValueError):
    pass


def _key(v) -> str:
    n = number(v)
    return str(int(n)) if n is not None and n == int(n) else str(v).strip().lstrip("#")


def _check(table: Table, recipe: dict) -> None:
    have = set(table.names) | {d["name"] for d in recipe.get("derived", [])}
    missing = []
    for d in recipe.get("derived", []):
        missing += [c for c in d.get("sum", []) if c not in table.names]
    for f in recipe.get("filters", []):
        if f["column"] not in have:
            missing.append(f["column"])
        if f.get("op") not in OPS:
            raise RecipeError(f"A condition's comparison is one of {' '.join(OPS)}, not {f.get('op')!r}.")
    for c in recipe.get("criteria", []):
        if c["column"] not in have:
            missing.append(c["column"])
        if c.get("better") not in ("higher", "lower"):
            raise RecipeError(f"'{c['column']}': better is higher or lower.")
    if recipe.get("key") and recipe["key"] not in table.names:
        missing.append(recipe["key"])
    if missing:
        raise RecipeError("This table has no column " + ", ".join(sorted(set(map(repr, missing))))
                          + ". Its columns are: " + ", ".join(table.names) + ".")


def _passes(row: dict, f: dict) -> bool:
    v, want = row.get(f["column"]), f.get("value")
    nv, nw = number(v), number(want)
    if nv is not None and nw is not None:
        v, want = nv, nw
    else:
        v, want = str(v).strip().lower(), str(want).strip().lower()
    op = f["op"]
    try:
        return {"<": v < want, "<=": v <= want, ">": v > want, ">=": v >= want,
                "=": v == want, "!=": v != want}[op]
    except TypeError:
        return False


def _percentiles(values: "list[float]") -> "list[float]":
    """Each value's share of the others it beats, ties counted half; 0..1."""
    n = len(values)
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        mid = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            out[order[k]] = mid
        i = j + 1
    return out


def rank(table: Table, recipe: dict, numbers: "list | None" = None) -> dict:
    """{'rows': ranked rows (each with score and per-criterion percentiles),
        'columns': what to show, 'kept': n, 'total': n, 'missing': picture
        numbers with no row in the table}."""
    _check(table, recipe)
    rows = [dict(r) for r in table.rows]
    for d in recipe.get("derived", []):
        for r in rows:
            r[d["name"]] = sum(number(r.get(c)) or 0.0 for c in d["sum"])

    key = recipe.get("key") or table.names[0]
    missing: "list[str]" = []
    if numbers:
        wanted = {_key(n) for n in numbers}
        present = {_key(r.get(key)) for r in rows}
        missing = sorted(wanted - present, key=lambda s: (len(s), s))
        rows = [r for r in rows if _key(r.get(key)) in wanted]
    total = len(rows)
    rows = [r for r in rows if all(_passes(r, f) for f in recipe.get("filters", []))]

    criteria = [c for c in recipe.get("criteria", []) if float(c.get("weight", 1)) > 0]
    weight = sum(float(c.get("weight", 1)) for c in criteria) or 1.0
    for r in rows:
        r["_parts"] = {}
    for c in criteria:
        vals = [number(r.get(c["column"])) for r in rows]
        vals = [v if v is not None else float("-inf") for v in vals]
        pct = _percentiles(vals) if rows else []
        for r, p in zip(rows, pct):
            r["_parts"][c["column"]] = round(100 * (p if c["better"] == "higher" else 1 - p), 1)
    for r in rows:
        r["_score"] = round(sum(float(c.get("weight", 1)) * r["_parts"][c["column"]]
                                for c in criteria) / weight, 1) if criteria else 0.0
    rows.sort(key=lambda r: -r["_score"])
    for i, r in enumerate(rows, 1):
        r["_rank"] = i

    labels = dict(table.columns)
    labels.update({d["name"]: d.get("label", d["name"]) for d in recipe.get("derived", [])})
    show = recipe.get("show") or [key] + [c["column"] for c in criteria]
    return {"columns": [{"name": n, "label": labels.get(n, n)} for n in show if n in labels],
            "rows": rows, "kept": len(rows), "total": total, "missing": missing, "key": key}


#: The first preset: Gil's migration pick (2026-10-11). More players, more
#: castles burned in the last day (an ACTIVE kingdom), and fewer strong players
#: — ✨ blessed and ⭐ starred counted together as "strong".
MIGRATION = {
    "name": "Migration — active, populous, few strong players",
    "key": "Kingdom",
    "derived": [
        {"name": "Blessed", "label": "✨", "sum": ["Blessed50", "Blessed100", "Blessed150"]},
        {"name": "Stars", "label": "⭐", "sum": ["Stars150", "Stars200", "Stars250"]},
        {"name": "Strong", "label": "Strong", "sum": ["Blessed50", "Blessed100", "Blessed150",
                                                     "Stars150", "Stars200", "Stars250"]},
    ],
    "filters": [],
    "criteria": [
        {"column": "Players", "better": "higher", "weight": 1},
        {"column": "Burned24h", "better": "higher", "weight": 1},
        {"column": "Strong", "better": "lower", "weight": 1},
    ],
    "show": ["Kingdom", "Players", "InactivePercent", "Burned24h", "Blessed", "Stars",
             "PlayerRank", "ScrollsRequired"],
}

"""Read a table from whatever the person has: an HTML page, CSV, TSV or JSON.

No pandas: the project does not carry it, and a table here is a few hundred
rows. The HTML reader takes the FIRST `<table>`, its header from the first
header row, and each cell's value from the most precise thing the page offers:

- `data-raw` when it agrees with the visible text (the migration export keeps
  `10.013117790222168` there and shows `10`), else the visible text, because
  the same export puts `0` in `data-raw` for a power shown as `3.62B`;
- `3.62B` / `850M` / `12K` read as numbers, `12%` and `1,234` too.

A column's NAME is its `data-column` attribute when there is one (a stable
identifier — `Burned24h`), and its LABEL is what the header shows (the export's fire-emoji header).
Presets refer to names, the screen shows labels.
"""

from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser

_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
_NUM = re.compile(r"^([-+]?\d+(?:\.\d+)?)\s*([kmbt])?%?$", re.I)


class TableError(ValueError):
    """A file that holds no table this can read, said as a sentence."""


def number(text) -> float | None:
    """`3.62B` -> 3.62e9, `1,234` -> 1234, `12%` -> 12; None for words."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    s = str(text or "").strip().replace(",", "").replace(" ", "")
    m = _NUM.match(s)
    if not m:
        return None
    v = float(m.group(1))
    return v * _SUFFIX[m.group(2).lower()] if m.group(2) else v


class Table:
    """Columns (name, label) and rows of {name: value}; a value is a float
    when the cell reads as a number, else the text."""

    def __init__(self, columns: list[tuple[str, str]], rows: list[dict]) -> None:
        self.columns = columns
        self.rows = rows

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.columns]

    def label(self, name: str) -> str:
        return dict(self.columns).get(name, name)

    def to_json(self) -> dict:
        return {"columns": [{"name": n, "label": l} for n, l in self.columns], "rows": self.rows}


# ---------------------------------------------------------------- HTML

class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables = 0
        self.depth = 0            # inside the first table
        self.header: list[tuple[str, str]] = []
        self.rows: list[list[tuple[str, str | None]]] = []
        self._row: list | None = None
        self._cell: dict | None = None
        self._in_head = False
        self._header_done = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tables += 1
            if self.tables == 1:
                self.depth = 1
            return
        if self.depth != 1:
            return
        if tag == "thead":
            self._in_head = True
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"tag": tag, "text": "", "raw": a.get("data-raw"), "col": a.get("data-column")}

    def handle_endtag(self, tag):
        if tag == "table" and self.depth == 1:
            self.depth = 2            # done; ignore later tables
            return
        if self.depth != 1:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            row, self._row = self._row, None
            if not row:
                return
            is_header = not self._header_done and (self._in_head or all(c["tag"] == "th" for c in row))
            if is_header:
                # The first header row names the columns; a second one (the
                # migration export's filter inputs) has no text and is skipped.
                if any(c["text"].strip() or c["col"] for c in row):
                    self.header = [((c["col"] or c["text"].strip()), c["text"].strip()) for c in row]
                    self._header_done = True
                return
            if self._in_head or all(c["tag"] == "th" for c in row) or not any(c["text"].strip() for c in row):
                return            # a second header row (filter boxes), or an empty one
            self.rows.append([(c["text"].strip(), c["raw"]) for c in row])
        elif tag == "thead":
            self._in_head = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def _cell_value(text: str, raw: str | None):
    shown = number(text)
    r = number(raw) if raw is not None else None
    if r is not None and shown is not None and abs(r - shown) <= max(1.0, abs(shown) * 0.01):
        return r                          # the precise copy of what is shown
    if shown is not None:
        return shown
    return text


def _unique(names: list[str]) -> list[str]:
    seen: dict = {}
    out = []
    for n in names:
        n = n or "column"
        k = seen.get(n, 0)
        seen[n] = k + 1
        out.append(n if k == 0 else f"{n} {k + 1}")
    return out


def from_html(text: str) -> Table:
    p = _HTML()
    p.feed(text)
    if p.tables == 0:
        raise TableError("That page has no table in it.")
    width = max([len(p.header)] + [len(r) for r in p.rows])
    if not p.rows:
        raise TableError("The page's table has no rows.")
    header = p.header + [(f"column {i + 1}", f"column {i + 1}") for i in range(len(p.header), width)]
    names = _unique([n for n, _ in header])
    cols = [(n, (l or n)) for n, (_, l) in zip(names, header)]
    rows = [{names[i]: _cell_value(t, raw) for i, (t, raw) in enumerate(r)} for r in p.rows]
    return Table(cols, rows)


# ---------------------------------------------------------------- CSV / TSV / JSON

def from_delimited(text: str) -> Table:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    reader = list(csv.reader(io.StringIO(text), dialect))
    reader = [r for r in reader if any(c.strip() for c in r)]
    if len(reader) < 2:
        raise TableError("That file has a header but no rows." if reader else "That file is empty.")
    names = _unique([h.strip() for h in reader[0]])
    rows = [{names[i]: _cell_value(c, None) for i, c in enumerate(r[:len(names)])} for r in reader[1:]]
    return Table([(n, n) for n in names], rows)


def from_json(text: str) -> Table:
    data = json.loads(text)
    if isinstance(data, dict):
        for k in ("rows", "data", "records"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    if not isinstance(data, list) or not data or not all(isinstance(r, dict) for r in data):
        raise TableError("A JSON table is a list of objects, one per row.")
    names: list[str] = []
    for r in data:
        for k in r:
            if k not in names:
                names.append(str(k))
    rows = [{n: _cell_value(r.get(n, ""), None) if not isinstance(r.get(n), (int, float)) else float(r[n])
             for n in names} for r in data]
    return Table([(n, n) for n in names], rows)


def read(filename: str, data: bytes) -> Table:
    """Pick the reader from the name, then from the content."""
    text = data.decode("utf-8-sig", errors="replace")
    low = (filename or "").lower()
    head = text.lstrip()[:200].lower()
    if low.endswith((".html", ".htm")) or head.startswith(("<!doctype", "<html", "<table")):
        return from_html(text)
    if low.endswith(".json") or head.startswith(("[", "{")):
        return from_json(text)
    if low.endswith((".csv", ".tsv", ".txt")) or "," in text or "\t" in text:
        return from_delimited(text)
    raise TableError(f"{filename or 'That file'}: send an .html, .csv, .tsv or .json table.")

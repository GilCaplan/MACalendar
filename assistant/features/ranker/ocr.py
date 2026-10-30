"""The numbers in a picture — every unique one, in the order they appear.

READING the text is Apple Vision on a Mac (`vision_numbers.swift`, compiled
once into a cache folder), Tesseract where there is no Vision. Both run on this
machine: nothing leaves it (`tests/unit/test_offline.py`).

CHOOSING which text is a number is `numbers_in()`, and it is strict on purpose.
A game screenshot carries numbers that are not the list — "Ruling Guild:
#1169", "Conqueror: #232", a timer "06:00:19", "Limit: 10 / 10". The list's
entries are pieces of text that are NOTHING BUT a number (`#1172`), while the
noise sits inside a sentence. So a piece counts only when it is all numbers;
`#`-numbers are preferred, and bare numbers are used only when a picture has no
`#` at all. On the Chalice District screenshot this kept exactly the 30
kingdoms and none of the 8 stray numbers around them.

The person sees the list and can edit it before ranking; a picture is a
starting point, not a verdict.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

SWIFT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_numbers.swift")

_HASHED = re.compile(r"^(?:#\s?\d{1,7}[\s,;|]*)+$")
_BARE = re.compile(r"^(?:\d{1,7}[\s,;|]*)+$")


class OCRError(RuntimeError):
    """No way to read text on this machine, or the picture could not be read."""


def numbers_in(lines: list[str]) -> list[int]:
    """Unique numbers, first-seen order, from recognised pieces of text."""
    hashed, bare = [], []
    for line in lines:
        s = line.strip()
        if _HASHED.match(s):
            hashed += re.findall(r"#\s?(\d+)", s)
        elif _BARE.match(s):
            bare += re.findall(r"\d+", s)
    found = hashed or bare
    seen, out = set(), []
    for n in (int(x) for x in found):
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _reading_order(rows: list[list[str]]) -> list[str]:
    """Vision returns pieces in no particular order; a list should read like the
    screen. Rows are pieces whose tops are within half a line of each other,
    then left to right; pictures in the order given."""
    pieces = [(int(i), float(top), float(left), float(h), text) for i, top, left, h, _c, text in rows]
    line = sorted(h for *_, h, _t in pieces)[len(pieces) // 2] if pieces else 0.02
    pieces.sort(key=lambda p: (p[0], p[1]))
    out, row = [], []
    for p in pieces:
        if row and (p[0] != row[0][0] or p[1] - row[0][1] > line / 2):
            out += [q[4] for q in sorted(row, key=lambda q: q[2])]
            row = []
        row.append(p)
    out += [q[4] for q in sorted(row, key=lambda q: q[2])]
    return out


def _cache_dir() -> str:
    base = (os.path.expanduser("~/Library/Caches") if sys.platform == "darwin"
            else os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"))
    try:
        os.makedirs(os.path.join(base, "MACalendar"), exist_ok=True)
        return os.path.join(base, "MACalendar")
    except OSError:
        return tempfile.gettempdir()


def _vision_binary() -> str | None:
    """The compiled helper, built on first use; None where Vision is not available."""
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        return None
    with open(SWIFT, "rb") as f:
        tag = hashlib.sha1(f.read()).hexdigest()[:10]
    out = os.path.join(_cache_dir(), f"vision_numbers-{tag}")
    if not os.path.exists(out):
        tmp = out + f".{os.getpid()}.tmp"
        r = subprocess.run(["swiftc", "-O", SWIFT, "-o", tmp], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise OCRError("Could not build the picture reader: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        os.replace(tmp, out)
    return out


def engine() -> str:
    if sys.platform == "darwin" and shutil.which("swiftc"):
        return "vision"
    if shutil.which("tesseract"):
        return "tesseract"
    return "none"


def read_lines(paths: list[str]) -> list[str]:
    """Every piece of text Vision (or Tesseract) recognises in the pictures."""
    if not paths:
        return []
    binary = _vision_binary()
    if binary:
        r = subprocess.run([binary, *paths], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise OCRError("Could not read that picture: " + (r.stderr.strip() or "unknown error"))
        return _reading_order([ln.split("\t", 5) for ln in r.stdout.splitlines() if ln.count("\t") >= 5])
    if shutil.which("tesseract"):
        lines = []
        for p in paths:
            r = subprocess.run(["tesseract", p, "-", "--psm", "11"], capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise OCRError("Could not read that picture: " + r.stderr.strip())
            lines += [ln for ln in r.stdout.splitlines() if ln.strip()]
        return lines
    raise OCRError("Reading numbers from a picture needs a Mac (Apple Vision) or Tesseract "
                   "installed. You can type the numbers instead.")


def numbers_from_images(images: list[tuple[str, bytes]]) -> list[int]:
    """(filename, bytes) pictures -> their unique numbers, all pictures together."""
    with tempfile.TemporaryDirectory(prefix="ranker-") as d:
        paths = []
        for i, (name, data) in enumerate(images):
            ext = os.path.splitext(name or "")[1].lower() or ".png"
            p = os.path.join(d, f"{i}{ext}")
            with open(p, "wb") as f:
                f.write(data)
            paths.append(p)
        return numbers_in(read_lines(paths))

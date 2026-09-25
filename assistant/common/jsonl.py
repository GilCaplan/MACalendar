"""JSON-lines files: one object per line, read tolerantly.

A torn last line (a writer killed mid-append) and a blank line are expected in
an append-only log, not corruption, so readers skip them rather than failing.
`tail` is the incremental read both buses do — everything written since the
byte offset a reader last stopped at, restarting if the file was trimmed.
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable, Iterator


def rows(lines: Iterable[str]) -> Iterator[Any]:
    """Each line parsed; blank and unparseable lines skipped."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue                    # a half-written line; re-read next time


def tail(path: str, offset: int) -> "tuple[list, int]":
    """(rows written since `offset`, the new offset). A file now SHORTER than
    the offset was trimmed or replaced: nothing is returned and the reader
    restarts from the file's current end."""
    try:
        current = os.path.getsize(path)
    except OSError:
        return [], 0
    if current < offset:
        return [], current
    if current == offset:
        return [], offset
    try:
        with open(path, encoding="utf-8") as f:
            f.seek(offset)
            out = list(rows(f))
            return out, f.tell()
    except OSError:
        return [], offset

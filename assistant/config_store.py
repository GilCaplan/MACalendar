"""Write settings back to config.yaml — section-scoped, comment-preserving.

The settings dialog used to persist by ~15 global regex substitutions over the
raw file ("rate: \\d+" → first match anywhere), each new setting hand-rolling
its own pattern. A yaml round-trip would be simpler but destroys the file's
comments, which is why the surgery existed. This module keeps the good part
(comments and layout survive) and fixes the bad parts:

  • every rewrite is scoped to its TOP-LEVEL SECTION, so `rate:` under `tts:`
    can never clobber a `rate:` somewhere else;
  • a key missing from an older config is inserted at its section's end;
  • a missing section is appended whole;
  • inline comments on a rewritten line are preserved.

    set_values({"tts": {"mute": True, "rate": 180}, "ui": {"theme": "dark"}})

## Two defects found in the wild, 2026-09-15

Real `config.yaml`, real corruption, no test had either shape:

1. **A value containing `#` was read as its own trailing comment.**
   `ui.accent_color: "#f5a524"` — the old value-vs-comment split had no idea
   a `#` can sit INSIDE a quoted string, so
   it read the value as `"` and the rest, `#f5a524"`, as a comment — which
   then got preserved and RE-APPENDED on every subsequent save, compounding
   into `"#f5a524"#f5a524'` after enough settings-dialog round trips.
   `_VALUE` now matches a whole quoted string or flow-list as one unit before
   ever considering where a comment could start.
2. **Rewriting a key left its OLD value's continuation lines behind.**
   `nlu.event_keywords` had been written as a YAML block list (`- meeting` /
   `- appointment` / `- activity`) at some point; a later rewrite to the flow
   form only replaced the `event_keywords:` header line, leaving the three
   `-` lines as now-orphaned siblings — invalid YAML, and `AppConfig` refused
   to load at all. A rewrite now swallows any block-list lines immediately
   following the key it is replacing.
"""
from __future__ import annotations

import os
import re

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

#: A value as ONE unit before a comment is ever considered: a whole quoted
#: string or flow-list first (either may legitimately contain "#"), a bare
#: scalar otherwise. Order matters — the quoted/flow-list branches must be
#: tried before the catch-all, or a value like "#f5a524" is never reached as
#: a single alternative.
_VALUE = r'(?:"[^"]*"|\[[^\]]*\]|[^#]*?)'
#: A YAML block-list item — "- meeting" at any indent. A key rewritten to a
#: flow form must swallow these or they survive as orphaned siblings.
_LIST_ITEM_RE = re.compile(r"^\s*-\s")


def _flow_key(name) -> str:
    """A mapping key as YAML flow style needs it: bare when plain, quoted
    otherwise ("Meal": 0 is fine; a name with a colon or a hash is not)."""
    name = str(name)
    if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_ .\-]*", name) and not name.strip() != name:
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        # A MAPPING as a one-line flow mapping — `{Work: 15, Meal: 0}`. Until
        # 2026-09-22 a dict fell through to the string case and was written as
        # a quoted Python repr, which YAML read back as a STRING; the settings
        # dialog carried its own writer for `notifications.category_leads`
        # because of it. Keys are sorted so the file is stable across saves.
        return "{" + ", ".join(f"{_flow_key(k)}: {_literal(v)}" for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))) + "}"
    return f'"{value}"'


def _replace_key(lines: "list[str]", i: int, end: int, header: str, value) -> int:
    """Overwrite `lines[i]` (a matched `key:` line) with the new value,
    consuming any YAML block-list lines that were the OLD value's
    continuation. Returns how many lines the span shrank by.

    `header` is normalized to end in exactly one space before the value —
    the captured group can be the bare `key:` with nothing after it (a block
    list's header line), and `key:[value]` with no space is exactly the
    ambiguous shape that read back as one giant scalar rather than a mapping
    (the `nlu.event_keywords` corruption this fixes)."""
    j = i + 1
    indent = len(lines[i]) - len(lines[i].lstrip())
    while j < end and (_LIST_ITEM_RE.match(lines[j])
                       # ...or a block MAPPING's children: any non-blank line
                       # indented deeper than the key it hangs off (2026-09-22,
                       # with the dict case above)
                       or (lines[j].strip() and not lines[j].lstrip().startswith("#")
                           and len(lines[j]) - len(lines[j].lstrip()) > indent)):
        j += 1
    lines[i:j] = [header.rstrip() + " " + _literal(value)]
    return (j - i) - 1


def _section_span(lines: "list[str]", section: str) -> "tuple[int, int] | None":
    """(start, end) of the section's body: after `section:` up to the next
    top-level key. None if the section doesn't exist."""
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^{re.escape(section)}\s*:\s*(#.*)?$", ln):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*\s*:", lines[j]):   # next top-level key
            end = j
            break
    return start, end


def set_values(updates: "dict[str, dict]", path: str = CONFIG_PATH) -> bool:
    """Apply {section: {key: value}} to the yaml file in place.

    Returns False (and writes nothing) if the file doesn't exist — a missing
    config.yaml is a setup problem the dialog reports, not one to mask by
    creating a comment-less file."""
    if not os.path.exists(path):
        return False
    with open(path, "r") as f:
        lines = f.read().splitlines()

    for section, kv in updates.items():
        if section == "":
            # top-level scalars (theme:, confirmation_level:, …)
            for key, value in kv.items():
                pat = re.compile(rf"^({re.escape(key)}\s*:\s*)({_VALUE})(\s*#.*)?$")
                for i, ln in enumerate(lines):
                    m = pat.match(ln)
                    if m:
                        _replace_key(lines, i, len(lines), m.group(1), value)
                        # a comment on the old line is discarded here on
                        # purpose: unlike a section key, there is no `end`
                        # to bound how far a stray "#" search could run, and
                        # top-level scalars in this file carry no comments
                        # worth preserving today.
                        if m.group(3):
                            lines[i] = lines[i].rstrip() + m.group(3)
                        break
                else:
                    lines.append(f"{key}: {_literal(value)}")
            continue
        span = _section_span(lines, section)
        if span is None:
            lines.append(f"{section}:")
            for key, value in kv.items():
                lines.append(f"  {key}: {_literal(value)}")
            continue
        start, end = span
        for key, value in kv.items():
            pat = re.compile(rf"^(\s+{re.escape(key)}\s*:\s*)({_VALUE})(\s*#.*)?$")
            for i in range(start, end):
                m = pat.match(lines[i])
                if m:
                    shrank = _replace_key(lines, i, end, m.group(1), value)
                    if m.group(3):
                        lines[i] = lines[i].rstrip() + m.group(3)
                    end -= shrank
                    break
            else:
                # insert before the section's trailing blank lines
                at = end
                while at > start and not lines[at - 1].strip():
                    at -= 1
                lines.insert(at, f"  {key}: {_literal(value)}")
                end += 1
        # spans of later sections may have shifted; recompute nothing — each
        # section is located fresh from the current lines on its own turn.

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return True

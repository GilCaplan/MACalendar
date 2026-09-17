"""Editing config.yaml as TEXT, so the comments survive.

`yaml.safe_load` → mutate → `yaml.dump` is the obvious way to change one
setting, and it silently destroys every comment in the file. It did: flipping
the Coursework tab from the phone rewrote the user's config.yaml and took the
whole commentary with it — the notes explaining what each block is for, why
`jude.priority` is background, which values are safe to change. Every VALUE
survived, which is exactly why nobody noticed until the file was read again.

`config.yaml` is gitignored, so there is no copy to restore from. That makes
this a one-way loss and worth avoiding rather than detecting.

A round-trip YAML library (ruamel) would solve it and is a dependency this
project does not have and should not take for one setting. So: find the line,
change the line, leave every other byte alone.

Deliberately narrow. It edits a SCALAR at a known path in a mapping that is
already there, or appends one — which covers the settings a client is allowed
to change. It does not rewrite structure, and anything it cannot find it
reports rather than guessing.
"""

from __future__ import annotations

import re

_SCALARS = {True: "true", False: "false", None: "null"}


def _fmt(value) -> str:
    if isinstance(value, bool) or value is None:
        return _SCALARS[value]
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    # Quote anything that could be read back as another type, or that carries
    # a character YAML treats specially.
    if text == "" or re.search(r'[:#\[\]{}",\']|^\s|\s$', text) or text.lower() in (
            "true", "false", "null", "yes", "no", "on", "off"):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def set_nested(text: str, parent: str, key: str, value) -> str:
    """Set `parent: { key: value }`, preserving everything else byte for byte.

    Creates the parent block at the end of the file if it is absent, and adds
    the key to an existing block if only that is missing.
    """
    lines = text.split("\n")
    parent_re = re.compile(rf"^{re.escape(parent)}\s*:\s*(#.*)?$")

    start = next((i for i, l in enumerate(lines) if parent_re.match(l)), None)
    if start is None:
        block = [f"{parent}:", f"  {key}: {_fmt(value)}"]
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines + [""] + block + [""])

    # The block runs until the next line at column 0 that is not blank and not
    # a comment — a comment after the block belongs to whatever follows it, so
    # stopping at one would insert into somebody else's documentation.
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line.startswith((" ", "\t")) and not line.lstrip().startswith("#"):
            end = i
            break

    key_re = re.compile(rf"^(\s+){re.escape(key)}\s*:\s*(.*?)(\s+#.*)?$")
    for i in range(start + 1, end):
        m = key_re.match(lines[i])
        if m:
            indent, _old, trailing = m.group(1), m.group(2), m.group(3) or ""
            lines[i] = f"{indent}{key}: {_fmt(value)}{trailing}"
            return "\n".join(lines)

    # Present block, absent key: insert after the last real entry in it, so a
    # trailing blank line or comment stays where the author put it.
    insert = start + 1
    indent = "  "
    for i in range(start + 1, end):
        if lines[i].strip() and not lines[i].lstrip().startswith("#"):
            insert = i + 1
            indent = re.match(r"^(\s*)", lines[i]).group(1) or "  "
    lines.insert(insert, f"{indent}{key}: {_fmt(value)}")
    return "\n".join(lines)


def set_top(text: str, key: str, value) -> str:
    """Set a TOP-LEVEL scalar, preserving the rest of the file."""
    lines = text.split("\n")
    key_re = re.compile(rf"^{re.escape(key)}\s*:\s*(.*?)(\s+#.*)?$")
    for i, line in enumerate(lines):
        m = key_re.match(line)
        if m:
            lines[i] = f"{key}: {_fmt(value)}{m.group(2) or ''}"
            return "\n".join(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines + [f"{key}: {_fmt(value)}", ""])

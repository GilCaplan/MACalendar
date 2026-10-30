"""Generate DOCUMENTATION/API_REFERENCE.md from this project's Flask routes.

Each endpoint's first docstring line is used as its description, so the doc
cannot drift from the code. Run after adding endpoints:

    python -m scripts.gen_api_reference

It also rewrites the "Endpoints" figure on the published architecture page
(`DOCUMENTATION/artifacts/architecture.html`), which `test_artifact_claims`
holds to `endpoint_count()`. That number used to be typed by hand, so every
new tab's routes turned the build red until someone remembered the page.

SEVERAL SOURCES, not one. `server.py` holds the voice, vocab, memory, config
and observance routes, but an INTEGRATION (assistant/integrations/CONVENTION.md)
and a FEATURE (assistant/features/CONVENTION.md) each register their own on a
Blueprint inside their folder. Scanning only `server.py` silently dropped all
six `/jude/*` endpoints from this reference the day they moved out — a
generated doc that quietly stops covering a surface is worse than one that was
never generated, because it still looks complete.
"""

from __future__ import annotations

import ast
import os
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "DOCUMENTATION", "API_REFERENCE.md")


def _sources() -> list[str]:
    """server.py, then every integration's and every feature's routes.py.

    TWO globs, not one: an integration's routes.py sits at
    `assistant/<name>/routes.py` and a feature's one level deeper at
    `assistant/features/<name>/routes.py`, and `*` does not cross a slash.
    """
    import glob
    found = [os.path.join(ROOT, "assistant", "api", "server.py")]
    found += sorted(glob.glob(os.path.join(ROOT, "assistant", "*", "routes.py")))
    found += sorted(glob.glob(os.path.join(ROOT, "assistant", "features", "*", "routes.py")))
    return found


def _url_prefix(tree: ast.Module) -> str:
    """The `url_prefix=` of a module-level Blueprint, so its paths are absolute.

    A blueprint declares `@blueprint.get("/status")` and mounts it under
    `/jude`, so without this the reference documents a `/status` that does not
    exist and omits the `/jude/status` that does.
    """
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Blueprint"):
            for kw in node.keywords:
                if kw.arg == "url_prefix" and isinstance(kw.value, ast.Constant):
                    return str(kw.value.value).rstrip("/")
    return ""


ARCHITECTURE = os.path.join(ROOT, "DOCUMENTATION", "artifacts", "architecture.html")


def endpoint_count() -> int:
    """Route DECORATORS across server.py and every blueprint — the figure the
    architecture page quotes. (Not the reference's row count: a `route()` with
    several methods is one decorator and several rows.)"""
    import glob
    import re
    files = [os.path.join(ROOT, "assistant", "api", "server.py")]
    files += sorted(glob.glob(os.path.join(ROOT, "assistant", "*", "routes.py")))
    files += sorted(glob.glob(os.path.join(ROOT, "assistant", "features", "*", "routes.py")))
    pat = re.compile(r"@(?:app|blueprint)\.(?:get|post|patch|delete|put)\(")
    return sum(len(pat.findall(open(f, encoding="utf-8").read())) for f in files)


def _write_architecture_count() -> None:
    import re
    with open(ARCHITECTURE, encoding="utf-8") as f:
        html = f.read()
    n = endpoint_count()
    new, hits = re.subn(r"(<dt>Endpoints</dt><dd>)\d+(</dd>)", rf"\g<1>{n}\g<2>", html)
    if hits != 1:
        raise SystemExit(f"architecture.html: expected one Endpoints figure, found {hits}")
    if new != html:
        with open(ARCHITECTURE, "w", encoding="utf-8") as f:
            f.write(new)
    print(f"{n} route decorators → {os.path.relpath(ARCHITECTURE, ROOT)}")


def main() -> None:
    groups: OrderedDict[str, list[tuple[str, str, str]]] = OrderedDict()
    for src in _sources():
        _collect(ast.parse(open(src, encoding="utf-8").read()), groups)
    _write(groups)
    _write_architecture_count()


def _collect(tree, groups) -> None:
    prefix = _url_prefix(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ("get", "post", "put", "patch", "delete", "route") and dec.args:
                raw = dec.args[0].value if isinstance(dec.args[0], ast.Constant) else "?"
                path = (prefix + raw) if prefix else raw
                method = dec.func.attr.upper()
                if method == "ROUTE":
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            method = "/".join(e.value for e in kw.value.elts if isinstance(e, ast.Constant))
                doc = (ast.get_docstring(node) or "").strip().splitlines()
                desc = doc[0] if doc else ""
                group = path.strip("/").split("/")[0] or "root"
                groups.setdefault(group, []).append((method, path, desc))


def _write(groups) -> None:
    lines = ["# API reference", "",
             "Generated from `assistant/api/server.py` and each integration's and "
             "feature's `routes.py` by `python -m scripts.gen_api_reference` — "
             "do not edit by hand.",
             "All endpoints are served by the Mac at `http://<tailscale-ip>:8080`; the iOS app is the only client. "
             "Path parameters use Flask syntax (`<int:id>`).", ""]
    for group, items in groups.items():
        lines += [f"## /{group}", "", "| Method | Path | What it does |", "|---|---|---|"]
        for m, p, d in sorted(items, key=lambda x: (x[1], x[0])):
            safe = d.replace("|", "\\|")
            lines.append(f"| `{m}` | `{p}` | {safe} |")
        lines.append("")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{sum(len(v) for v in groups.values())} endpoints → {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    sys.exit(main())

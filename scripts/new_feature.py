"""Scaffold a new tab: every file and every registration line, in one command.

    python scripts/new_feature.py recipes --label Recipes --icon fork.knife --order 35
    python scripts/new_feature.py recipes ... --store recipes.db    # it keeps its own file
    python scripts/new_feature.py recipes ... --no-mac              # phone only (like Teach)
    python scripts/new_feature.py recipes ... --dry-run             # say what it would do

`assistant/features/CONVENTION.md` is the contract and its checklist is the
list of steps; this script does each one it can and prints the rest. The
steps it cannot do are judgement (what the tab is FOR, its FEATURES.md entry)
and are held by `tests/unit/test_new_tab_checklist.py`, which goes red naming
the step if it is skipped.

The steps, as named in CONVENTION.md's checklist:

- **Feature folder**: `assistant/features/<name>/` with `feature.py`,
  `routes.py`, `__init__.py`.
- **Registry line**: the import and the tuple entry in `registry.py`.
- **Mac panel**: `assistant/calendar_ui/<name>_view.py`, a `FeaturePanel`.
- **iOS tab**: `Features/<Name>/<Name>View.swift` and its `FeatureRegistry.swift`
  entry, in `order`.
- **Xcode project**: the Swift files added with `scripts/xcode_add.py`.
- **Store redirect**: with `--store`, the env override in `tests/conftest.py`,
  `scratch_env.STORES` and CLAUDE.md.
- **Tests**: `tests/unit/test_<name>.py`.
- **API reference**: `scripts/gen_api_reference.py` (also rewrites the
  architecture page's endpoint count).
- **Offline writes**: printed — every phone write goes through
  `APIClient.mutate` (`tests/unit/test_ios_offline.py`).
- **FEATURES.md entry**: printed — a table row and a section.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEATURES = os.path.join(ROOT, "assistant", "features")
IOS_APP = os.path.join(ROOT, "MACalendar-iOS", "MACalendar-iOS")


def pascal(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("_"))


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


class Plan:
    """Collected writes, so --dry-run and a refusal leave the tree untouched."""

    def __init__(self, dry: bool) -> None:
        self.dry = dry
        self.writes: "list[tuple[str, str, str]]" = []     # (path, content, what)

    def new(self, path: str, content: str) -> None:
        if os.path.exists(path):
            raise SystemExit(f"refusing to overwrite {os.path.relpath(path, ROOT)}")
        self.writes.append((path, content, "create"))

    def edit(self, path: str, content: str) -> None:
        self.writes.append((path, content, "edit"))

    def apply(self) -> None:
        for path, content, what in self.writes:
            print(f"{'would ' if self.dry else ''}{what:6} {os.path.relpath(path, ROOT)}")
            if self.dry:
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)


# ---------------------------------------------------------------- the steps

def feature_folder(plan: Plan, a) -> None:
    d = os.path.join(FEATURES, a.name)
    cls = pascal(a.name) + "Feature"
    panel = "" if a.no_mac else f'''
    def panel(self):
        # Imported lazily: the API server builds this registry with no display.
        from assistant.calendar_ui.{a.name}_view import {pascal(a.name)}View
        return {pascal(a.name)}View
'''
    plan.new(os.path.join(d, "__init__.py"),
             f'"""The {a.label} feature. See `assistant/features/CONVENTION.md`."""\n\n'
             f"from assistant.features.{a.name}.feature import {cls}  # noqa: F401\n")
    plan.new(os.path.join(d, "feature.py"), f'''"""{a.label} — declared once, read by the registry and both clients."""

from __future__ import annotations

from assistant.features.base import Feature


class {cls}(Feature):
    """TODO: one line on what this tab is for."""

    name = "{a.name}"
    label = "{a.label}"
    icon = "{a.icon}"
    order = {a.order}
    pinned = False
    default_visible = True
{panel}
    def blueprint(self):
        from assistant.features.{a.name}.routes import blueprint
        return blueprint
''')
    store = ""
    if a.store:
        var = "MACALENDAR_" + a.name.upper()
        store = f'''

# This tab's own file, per user. `{var}` is redirected by tests/conftest.py
# and scratch_env.STORES, so a suite or a board never writes the real one.
DEFAULT_PATH = os.path.expanduser("~/.assistant_tools/{a.store}")


def store_path() -> str:
    from assistant.users import paths
    return paths.resolve(os.environ.get("{var}") or DEFAULT_PATH)
'''
    plan.new(os.path.join(d, "routes.py"), f'''"""{a.label}'s HTTP surface: `/{a.name}*`.

HTTP only — routes, request shapes, CRUD. No parsing or execution: that is the
engine's (CLAUDE.md). After adding a route, run `python -m scripts.gen_api_reference`.
"""

from __future__ import annotations
{"" if not a.store else chr(10) + "import os" + chr(10)}
from flask import Blueprint

blueprint = Blueprint("{a.name}", __name__){store}
''')


def registry_line(plan: Plan, a) -> None:
    path = os.path.join(FEATURES, "registry.py")
    src = _read(path)
    cls = pascal(a.name) + "Feature"
    imports = re.findall(r"^        from assistant\.features\.\w+ import \w+\n", src, re.M)
    if not imports:
        raise SystemExit("registry.py: could not find the feature imports")
    line = f"        from assistant.features.{a.name} import {cls}\n"
    block = "".join(imports)
    src = src.replace(block, "".join(sorted(imports + [line])), 1)
    m = re.search(r"for factory in \((.*?)\):", src, re.S)
    names = [n.strip() for n in m.group(1).split(",") if n.strip()]
    names.append(cls)
    body = ""
    line_ = "        for factory in ("
    for i, n in enumerate(names):
        piece = n + (", " if i < len(names) - 1 else "")
        if len(line_) + len(piece) > 84:
            body += line_.rstrip() + "\n"
            line_ = "                        "
        line_ += piece
    body += line_ + "):"
    src = src[:m.start()] + body.lstrip() + src[m.end():]
    plan.edit(path, src)


def mac_panel(plan: Plan, a) -> None:
    if a.no_mac:
        return
    plan.new(os.path.join(ROOT, "assistant", "calendar_ui", f"{a.name}_view.py"), f'''"""{a.label} — the Mac panel. Contract: `calendar_ui/feature_panel.py`."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from assistant.calendar_ui.feature_panel import FeaturePanel


class {pascal(a.name)}View(FeaturePanel):
    feature_name = "{a.name}"

    def __init__(self, db=None, config=None, dark: bool = True) -> None:
        super().__init__()
        self._db = db
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self._empty = QLabel("{a.label} has nothing to show yet.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

    def reload(self) -> None:
        """THE contract verb: re-read and redraw."""

    def apply_theme(self, dark: bool) -> None:
        pass

    def apply_ui_config(self, ui) -> None:
        pass
''')


def ios_tab(plan: Plan, a) -> "list[str]":
    if a.no_ios:
        return []
    P = pascal(a.name)
    rel = f"MACalendar-iOS/Features/{P}/{P}View.swift"
    plan.new(os.path.join(ROOT, "MACalendar-iOS", rel), f'''import SwiftUI

/// {a.label}. Declared in `Features/FeatureRegistry.swift`; the Mac side is
/// `assistant/features/{a.name}/`. Every write goes through `APIClient.mutate`
/// so it queues when the Mac is away (`tests/unit/test_ios_offline.py`).
struct {P}View: View {{
    @EnvironmentObject var api: APIClient

    var body: some View {{
        NavigationStack {{
            VStack(spacing: 8) {{
                Image(systemName: "{a.icon}")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
                Text("{a.label} has nothing to show yet.")
                    .foregroundStyle(.secondary)
            }}
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationTitle("{a.label}")
        }}
    }}
}}
''')
    path = os.path.join(IOS_APP, "Features", "FeatureRegistry.swift")
    src = _read(path)
    entry = (f'        Feature(name: "{a.name}", label: "{a.label}", icon: "{a.icon}",\n'
             f'                order: {a.order}{", needsMac: true" if a.needs_mac else ""},\n'
             f'                make: {{ AnyView({P}View()) }}),\n')
    starts = [(m.start(), int(re.search(r"order:\s*(\d+)", src[m.start():]).group(1)))
              for m in re.finditer(r"^        Feature\(name:", src, re.M)]
    later = [s for s, o in starts if o > a.order]
    if later:
        # Keep any comment block that sits directly above the entry with it.
        at = later[0]
        while True:
            prev = src.rfind("\n", 0, at - 1) + 1
            if src[prev:at].lstrip().startswith("//"):
                at = prev
            else:
                break
    else:
        at = src.index("    ]", starts[-1][0])
    plan.edit(path, src[:at] + entry + src[at:])
    return [rel]


def store_redirect(plan: Plan, a) -> None:
    if not a.store:
        return
    var = "MACALENDAR_" + a.name.upper()
    conf = os.path.join(ROOT, "tests", "conftest.py")
    src = _read(conf)
    m = re.search(r'(\("MACALENDAR_\w+", "[^"]+"\))\):\n    _os\.environ\.setdefault', src)
    if not m:
        raise SystemExit("tests/conftest.py: could not find the end of the store list")
    src = src[:m.end(1)] + f',\n                    # the {a.label} tab\'s own file.\n                    ("{var}", "{a.store}")' + src[m.end(1):]
    plan.edit(conf, src)
    se = os.path.join(ROOT, "assistant", "common", "scratch_env.py")
    src = _read(se)
    key = a.name.upper()
    src = src.replace("\n}\n\n#: setdefault", f'\n    "{key}": ("{var}", "{a.store}"),\n}}\n\n#: setdefault', 1)
    plan.edit(se, src)
    cl = os.path.join(ROOT, "CLAUDE.md")
    src = _read(cl)
    anchor = re.search(r"^    MACALENDAR_FLASHCARDS .*\n(?:^ {31}.*\n)*", src, re.M)
    if anchor:
        line = f"    {var:<26} the {a.label} tab's own store\n"
        src = src[:anchor.end()] + line + src[anchor.end():]
        plan.edit(cl, src)


def tests(plan: Plan, a) -> None:
    plan.new(os.path.join(ROOT, "tests", "unit", f"test_{a.name}.py"), f'''"""{a.label}: the feature's own tests. Replace the placeholder with real ones."""

from __future__ import annotations

from assistant.features import registry


def test_{a.name}_is_registered():
    f = registry.get("{a.name}")
    assert f is not None and f.label == "{a.label}" and f.order == {a.order}
''')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("name", help="lowercase identity: config key, URL, both clients")
    ap.add_argument("--label", required=True)
    ap.add_argument("--icon", required=True, help="SF Symbol name")
    ap.add_argument("--order", type=int, required=True, help="sparse slot, unused (see CONVENTION.md)")
    ap.add_argument("--store", help="file name of this tab's own per-user store, e.g. recipes.db")
    ap.add_argument("--no-mac", action="store_true", help="no Mac panel (phone only)")
    ap.add_argument("--no-ios", action="store_true", help="no phone tab")
    ap.add_argument("--needs-mac", action="store_true", help="phone tab hidden in phone-only mode")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if not re.fullmatch(r"[a-z][a-z0-9_]*", a.name):
        raise SystemExit("name: lowercase letters, digits and _ — it is a URL segment and a config key")
    sys.path.insert(0, ROOT)
    from assistant.features import registry
    taken = {f.name: f.order for f in registry.all_features()}
    if a.name in taken or os.path.exists(os.path.join(FEATURES, a.name)):
        raise SystemExit(f"a feature called {a.name!r} already exists")
    if a.order in taken.values():
        clash = next(n for n, o in taken.items() if o == a.order)
        raise SystemExit(f"order {a.order} is {clash}'s; pick a free slot — taken: "
                         + ", ".join(f"{o} {n}" for n, o in sorted(taken.items(), key=lambda x: x[1])))

    plan = Plan(a.dry_run)
    feature_folder(plan, a)
    registry_line(plan, a)
    mac_panel(plan, a)
    swift = ios_tab(plan, a)
    store_redirect(plan, a)
    tests(plan, a)
    plan.apply()

    if not a.dry_run:
        if swift:
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "xcode_add.py"), *swift], check=True)
        subprocess.run([sys.executable, "-m", "scripts.gen_api_reference"], cwd=ROOT, check=True)

    print(f"""
Done. Still yours, and each is held by a test that names it:
  - FEATURES.md entry: a row in the table and a ### section (what / where / how).
  - Offline writes: every phone write goes through APIClient.mutate, with a
    client_token on creates; anything that must not replay goes in
    tests/unit/test_ios_offline.py NOT_QUEUEABLE with a reason.
  - The docstring TODO in assistant/features/{a.name}/feature.py.
Then: ./.venv/bin/python -m pytest tests/unit/test_{a.name}.py tests/unit/test_features.py \\
      tests/unit/test_new_tab_checklist.py -q
and build the phone: cd MACalendar-iOS && xcodebuild -project MACalendar-iOS.xcodeproj \\
      -scheme MACalendar-iOS -destination 'generic/platform=iOS Simulator' build""")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The steps of adding a tab that nothing else would notice you skipped.

`assistant/features/CONVENTION.md` lists every step of adding a feature, and
`scripts/new_feature.py` does most of them. These are the ones whose omission
is SILENT: the tab works, every other test is green, and the damage shows up
later somewhere else. Each failure message names the step.

Bought with the Flashcards tab (2026-10-11), whose store had to be added to
three hand-kept lists, whose 8 Swift files needed 36 hand-written project
lines, and whose routes turned the published-page check red over a number
typed into HTML.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

from assistant.features import registry

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _store_vars_in(folder: pathlib.Path) -> set[str]:
    out = set()
    for p in folder.rglob("*.py"):
        out |= set(re.findall(r"""environ(?:\.get\(|\[)\s*["'](MACALENDAR_[A-Z_]+)["']""", p.read_text()))
    return out - {"MACALENDAR_CONFIG"}        # config is scratched separately in conftest


def test_every_feature_store_is_scratched_for_tests_and_boards():
    """A feature that opens its own file must be redirected by `tests/conftest.py`
    (or the suite writes into the real one — what you are studying, timing or
    tracking) and by `scratch_env.STORES` (or a board does)."""
    from assistant.common.scratch_env import STORES
    conftest = (ROOT / "tests" / "conftest.py").read_text()
    boards = {var for var, _ in STORES.values()}
    missing = []
    for f in registry.all_features():
        for var in _store_vars_in(ROOT / "assistant" / "features" / f.name):
            if f'"{var}"' not in conftest:
                missing.append(f"{f.name}: {var} is not redirected in tests/conftest.py")
            if var not in boards:
                missing.append(f"{f.name}: {var} is not in assistant/common/scratch_env.py STORES")
    assert not missing, "\n".join(missing)


def test_every_feature_store_is_named_in_claude_md():
    claude = (ROOT / "CLAUDE.md").read_text()
    for f in registry.all_features():
        for var in _store_vars_in(ROOT / "assistant" / "features" / f.name):
            assert var in claude, (f"{f.name}: add {var} to CLAUDE.md's list of personal stores "
                                   "(\"Personal data lives outside the repo\")")


def test_every_feature_has_a_features_md_entry():
    """FEATURES.md is the catalog, and "a shipped feature adds its entry there
    in the same change" (CLAUDE.md)."""
    table = [ln for ln in (ROOT / "DOCUMENTATION" / "FEATURES.md").read_text().splitlines()
             if ln.startswith("|")]
    text = "\n".join(table).lower()
    for f in registry.all_features():
        assert f.label.lower() in text, (
            f"{f.name}: add a row for {f.label!r} to the table in DOCUMENTATION/FEATURES.md, "
            "and a ### section below it")


def test_every_mac_panel_names_its_feature():
    """The window ties a panel to its sidebar row and its visibility switch by
    `feature_name`; a copied panel that keeps the old name hides the wrong tab."""
    for f in registry.all_features():
        if not f.has_mac_panel:
            continue
        src = (ROOT / "assistant" / "features" / f.name / "feature.py").read_text()
        m = re.search(r"from (assistant\.calendar_ui\.\w+) import (\w+)", src)
        if not m:
            continue
        panel = (ROOT / pathlib.Path(*m.group(1).split("."))).with_suffix(".py").read_text()
        assert re.search(rf'feature_name\s*=\s*["\']{f.name}["\']', panel), (
            f"{m.group(1)}.{m.group(2)} must set feature_name = {f.name!r}")


def test_every_mac_panel_has_a_drawn_sidebar_icon():
    """A feature without `mac_icon` got a bare dot that sat off the line in the
    sidebar (Flashcards and Ranker, 2026-10-11)."""
    from assistant.calendar_ui import icons
    for f in registry.all_features():
        if f.has_mac_panel:
            assert f.mac_icon and icons.exists(f.mac_icon), (
                f"{f.name}: set mac_icon to a drawing in assistant/calendar_ui/icons "
                "(scripts/sync_icons.py --add <name> after drawing it in ../GraphicsLibrary)")


def test_every_swift_file_is_in_the_xcode_project():
    """A .swift file under a target's folder that the project does not compile
    is invisible: the build succeeds without it. `scripts/xcode_add.py` adds one."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "xcode_add.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr +
                               "\nrun: python scripts/xcode_add.py <those paths>")


def test_xcode_add_writes_a_project_xcode_can_read(tmp_path):
    """Adding a file to a new nested folder, twice, gives the same valid project
    as adding it once."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import xcode_add
    finally:
        sys.path.pop(0)
    proj = tmp_path / "project.pbxproj"
    proj.write_text(pathlib.Path(xcode_add.PBXPROJ).read_text())
    paths = ["MACalendar-iOS/Features/Zz/ZzView.swift", "MACalendar-iOS/Features/Zz/Sub/ZzModel.swift",
             "MACalendarUITests/ZzUITests.swift"]
    assert xcode_add.main(["--project", str(proj), *paths]) == 0
    once = proj.read_text()
    assert xcode_add.main(["--project", str(proj), *paths]) == 0
    assert proj.read_text() == once
    p = xcode_add.Project(once)
    compiled = p.compiled()
    assert {paths[0], paths[1]} <= compiled["MACalendar-iOS"]
    assert paths[2] in compiled["MACalendarUITests"]
    if sys.platform == "darwin":
        r = subprocess.run(["plutil", "-convert", "json", "-o", "/dev/null", str(proj)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_the_scaffold_knows_every_step_the_convention_lists():
    """CONVENTION.md's checklist and `scripts/new_feature.py` describe the same
    steps — a step added to one and not the other is how the lists drift."""
    conv = (ROOT / "assistant" / "features" / "CONVENTION.md").read_text()
    scaffold = (ROOT / "scripts" / "new_feature.py").read_text()
    steps = re.findall(r"^- \[ \] \*\*(.+?)\*\*", conv, re.M)
    assert len(steps) >= 8, "CONVENTION.md lost its checklist"
    for step in steps:
        assert step in scaffold, f"scripts/new_feature.py does not mention the step {step!r}"


def test_the_scaffold_still_runs():
    """A generator rots silently and only breaks when next used (CLAUDE.md) —
    so use it every build, as a dry run that writes nothing."""
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "new_feature.py"), "zz_probe",
                        "--label", "Zz Probe", "--icon", "star", "--order", "997",
                        "--store", "zz_probe.db", "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    for step in ("feature.py", "registry.py", "_view.py", "View.swift", "FeatureRegistry.swift",
                 "conftest.py", "scratch_env.py", "test_zz_probe.py"):
        assert step in r.stdout, f"the scaffold no longer writes {step}:\n{r.stdout}"
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    assert before == after, "--dry-run wrote something"

"""DOCUMENTATION/CODE_SIZE.md must not lie about how big the project is.

A line count typed into a README is stale the next day, and nobody notices
because nothing checks it — the same failure mode `test_artifact_claims` exists
for on the published pages. So the table is GENERATED
(`python -m scripts.code_stats --write`) and this is the guard that says when
it needs regenerating.

It deliberately tolerates drift (`code_stats.DRIFT_PCT`). Every commit moves
the line count, and a test that went red on each one would be turned off within
a week; what this catches is the doc being wrong enough to mislead someone.
"""

from __future__ import annotations

import pathlib

import pytest

from scripts import code_stats

README = pathlib.Path(__file__).resolve().parents[2] / "README.md"


@pytest.fixture(scope="module")
def stats():
    return code_stats.collect()


def test_the_written_breakdown_is_not_stale(stats):
    pct, was = code_stats.drift(stats)
    claimed = was.get("total_lines") if was else None
    assert pct <= code_stats.DRIFT_PCT, (
        f"DOCUMENTATION/CODE_SIZE.md claims {claimed} lines, the tree has "
        f"{stats['total_lines']} ({pct:.1f}% off, tolerance "
        f"{code_stats.DRIFT_PCT:g}%). Run: python -m scripts.code_stats --write")


def test_every_source_file_lands_in_a_category(stats):
    """An uncategorised file is silently missing from the table. A new
    top-level folder is the usual cause — add a rule to
    `scripts/code_stats.category()`."""
    assert not stats["uncategorised"], (
        "scripts/code_stats.category() has no rule for: "
        + ", ".join(stats["uncategorised"]))


def test_the_categories_add_up_to_the_total(stats):
    """Each file counted once and only once — otherwise the rows are a
    plausible-looking table that sums to something else."""
    assert sum(nl for _c, (_nf, nl) in stats["rows"]) == stats["total_lines"]
    assert sum(nf for _c, (nf, _nl) in stats["rows"]) == stats["total_files"]


def test_the_readme_points_at_the_generated_file_and_carries_no_count():
    """The README LINKS to the breakdown rather than repeating it. A number
    copied into a second place is a number that will disagree with the first."""
    text = README.read_text(encoding="utf-8")
    assert "DOCUMENTATION/CODE_SIZE.md" in text, (
        "README.md no longer links to the code-size breakdown")

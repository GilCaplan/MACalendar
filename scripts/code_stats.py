"""Generate DOCUMENTATION/CODE_SIZE.md — how big this project is, by category.

    python -m scripts.code_stats            # print the report
    python -m scripts.code_stats --write    # rewrite DOCUMENTATION/CODE_SIZE.md
    python -m scripts.code_stats --check    # exit 1 if the file has drifted
    python -m scripts.code_stats --install-hook   # refresh it on every commit

A hand-typed line count is stale the day after it is written, so this counts
from `git ls-files` — tracked files only, so a virtualenv or a scratch run can
never inflate it — and writes the doc. The README links to the output rather
than carrying a number of its own, for the same reason.

`--check` is what `tests/unit/test_code_size.py` runs. It tolerates DRIFT_PCT
so that ordinary work does not turn the build red for editing code; what it
catches is the doc being wrong enough to mislead.

Categories are a judgement call and the point is that they are ONE judgement
call, written down in `category()` below, applied to every file, with nothing
counted twice and the total reconciling to the plain per-language count.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "DOCUMENTATION", "CODE_SIZE.md")

# Source, as in "someone wrote these lines". Data files (the 3,000-utterance
# corpus, fitted weights, fixtures) are counted separately and never folded in:
# they dwarf the code and would make the headline meaningless.
SOURCE_EXT = (".py", ".swift", ".sh", ".command")
DATA_EXT = (".json", ".jsonl", ".csv")
PROSE_EXT = (".md", ".html")

# How far the written doc may drift before it counts as stale. Every commit
# moves these numbers; only a big move makes the doc actually wrong.
DRIFT_PCT = 2.0

# The machine-readable copy of the headline, so the drift check reads numbers
# rather than re-parsing a markdown table.
STAMP_RE = re.compile(r"<!-- code-stats: (\{.*?\}) -->")

# --- the categories --------------------------------------------------------
#
# Order matters: the first rule that matches wins, so the narrow ones come
# first. Anything that falls through lands in UNCATEGORISED and the report
# names the file, which is how a new top-level folder gets noticed.

REVIEW_PANEL = {
    "assistant/calendar_ui/thinking_panel.py",   # the card itself
    "assistant/thinking_hud.py",                 # the always-on-top app
    "assistant/trace.py",                        # BRAIN_VERSION, CHAINS
    "assistant/trace_bus.py",                    # the durable feed
    "scripts/shoot_panel.py",                    # the screenshot tool
}

MAC_APP_FILES = {
    "assistant/main.py", "assistant/hotkey.py", "assistant/pipeline.py",
    "assistant/app.py", "assistant/notifier.py",
}

C_PANEL = "Review panel (Mac card + iOS timeline)"
C_TESTS = "Test code"
C_RETIRED = "Retired (old brain, kept on purpose)"
C_IOS = "iOS application"
C_ENGINE = "Engine (the brain, shipped path)"
C_BOARDS = "Engine experiments & boards (not in the answer path)"
C_MODEL = "Model / Ollama code"
C_MIC = "Microphone / speech (record, STT, TTS)"
C_API = "API server (the front door)"
C_MAC = "Mac application (calendar GUI)"
C_DOMAIN = "Actions, storage & domain (DB, config, observance, .ics)"
C_TOOLING = "Dataset & measurement tooling"
C_LAUNCH = "Launch scripts"

# Printed under the table, because every one of these is arguable and a reader
# comparing this to their own `wc -l` deserves to know which way we went.
JUDGEMENT_CALLS = [
    "`llmjudge/` and `llmseg/` count as **Model**, not Engine — they are stages "
    "that exist to call the model.",
    "`intent/` (rule parser, classifiers, command memory) counts as **Engine**.",
    "iOS `Voice/` and `VoiceButton.swift` count as **Microphone**, not iOS.",
    "`trace.py` / `trace_bus.py` count as **Review panel** — they exist to feed it.",
    "A stage folder's `experiments/`, `datasets/` and `eval_metrics/` are "
    "**boards**, not the shipped engine.",
]


def category(f: str) -> "str | None":
    if f in REVIEW_PANEL or f.endswith("Views/ThinkingView.swift"):
        return C_PANEL
    if f.startswith("tests/"):
        return C_TESTS
    if f.startswith("retired/"):
        return C_RETIRED
    if f.endswith(".swift"):
        if "/Voice/" in f or f.endswith("VoiceButton.swift"):
            return C_MIC
        return C_IOS
    if f.startswith("assistant/engine/"):
        if any(p in f for p in ("/experiments/", "/datasets/", "/eval_metrics/")):
            return C_BOARDS
        if f == "assistant/engine/llm.py" or "/llmjudge/" in f or "/llmseg/" in f:
            return C_MODEL
        return C_ENGINE
    if f.startswith("assistant/intent/"):
        return C_ENGINE
    if f.startswith(("assistant/audio/", "assistant/stt/", "assistant/tts/")) \
            or f == "assistant/api/audio_utils.py":
        return C_MIC
    if f.startswith("assistant/api/"):
        return C_API
    if f.startswith("assistant/calendar_ui/") or f in MAC_APP_FILES:
        return C_MAC
    if f.startswith("assistant/"):
        return C_DOMAIN
    if f.startswith("scripts/"):
        return C_TOOLING
    if f.endswith((".sh", ".command")):
        return C_LAUNCH
    return None


# --- counting --------------------------------------------------------------

def tracked() -> "list[str]":
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f]


def lines(path: str) -> int:
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def collect() -> dict:
    by_cat: dict = collections.defaultdict(lambda: [0, 0])
    by_ext: dict = collections.defaultdict(lambda: [0, 0])
    loose: "list[str]" = []
    data = [0, 0]
    prose = [0, 0]

    for f in tracked():
        ext = os.path.splitext(f)[1]
        n = None
        if ext in SOURCE_EXT:
            n = lines(f)
            cat = category(f)
            if cat is None:
                loose.append(f)
                cat = "UNCATEGORISED"
            by_cat[cat][0] += 1
            by_cat[cat][1] += n
            by_ext[ext][0] += 1
            by_ext[ext][1] += n
        elif ext in DATA_EXT:
            data[0] += 1
            data[1] += lines(f)
        elif ext in PROSE_EXT:
            prose[0] += 1
            prose[1] += lines(f)

    rows = sorted(by_cat.items(), key=lambda kv: -kv[1][1])
    return {
        "rows": rows,
        "by_ext": dict(by_ext),
        "uncategorised": loose,
        "data": data,
        "prose": prose,
        "total_files": sum(v[0] for v in by_cat.values()),
        "total_lines": sum(v[1] for v in by_cat.values()),
    }


# Categories that exist to build or verify the product rather than to BE it.
# "Live product" is the total minus these — the number worth quoting.
NOT_PRODUCT = (C_TESTS, C_RETIRED, C_BOARDS, C_TOOLING)


def render(s: dict) -> str:
    live = s["total_lines"] - sum(v[1] for k, v in s["rows"] if k in NOT_PRODUCT)
    stamp = json.dumps({"total_files": s["total_files"],
                        "total_lines": s["total_lines"]}, sort_keys=True)

    out = [
        "# Code size, by category",
        "",
        f"<!-- code-stats: {stamp} -->",
        "**Generated — do not edit by hand.** The pre-commit hook "
        "(`python -m scripts.code_stats --install-hook`) rewrites this whenever "
        "the numbers move, so it describes the commit it ships in. By hand: "
        "`python -m scripts.code_stats --write`; "
        "`--check` says whether it is current, and "
        "`tests/unit/test_code_size.py` fails once it is more than "
        f"{DRIFT_PCT:g}% out.",
        "",
        f"**{s['total_lines']:,} lines of source across {s['total_files']} files.** "
        f"Of that, **{live:,} lines are the live product** — the rest is tests, "
        "the retired brain, the measurement boards and the dataset tooling.",
        "",
        "| category | files | lines |",
        "|---|---:|---:|",
    ]
    for cat, (nf, nl) in s["rows"]:
        out.append(f"| {cat} | {nf} | {nl:,} |")
    out += [
        f"| **TOTAL** | **{s['total_files']}** | **{s['total_lines']:,}** |",
        "",
        "### By language",
        "",
        "| | files | lines |",
        "|---|---:|---:|",
    ]
    names = {".py": "Python", ".swift": "Swift", ".sh": "shell",
             ".command": "launch script"}
    for ext, (nf, nl) in sorted(s["by_ext"].items(), key=lambda kv: -kv[1][1]):
        out.append(f"| {names.get(ext, ext)} | {nf} | {nl:,} |")
    out += [
        "",
        "Not counted above, and deliberately so:",
        "",
        f"- **Data** — the utterance corpus, fitted weights and fixtures: "
        f"{s['data'][1]:,} lines across {s['data'][0]} files. Bigger than the "
        "code, and not written by hand.",
        f"- **Prose** — markdown and the published HTML explainers: "
        f"{s['prose'][1]:,} lines across {s['prose'][0]} files.",
        "",
        "### How the categories are drawn",
        "",
        "Every tracked source file lands in exactly one category, so the rows "
        "sum to the total and nothing is double counted. The rules live in "
        "`scripts/code_stats.py`'s `category()`; the arguable ones:",
        "",
    ]
    out += [f"- {c}" for c in JUDGEMENT_CALLS]
    if s["uncategorised"]:
        out += ["", "**Uncategorised — add a rule for these:**", ""]
        out += [f"- `{f}`" for f in s["uncategorised"]]
    out.append("")
    return "\n".join(out)


def written_stamp() -> "dict | None":
    try:
        with open(OUT, encoding="utf-8") as fh:
            m = STAMP_RE.search(fh.read())
    except OSError:
        return None
    return json.loads(m.group(1)) if m else None


def drift(s: dict) -> "tuple[float, dict | None]":
    """(percent the written doc is off by, what it claims). inf if missing."""
    was = written_stamp()
    if not was or not s["total_lines"]:
        return float("inf"), was
    delta = abs(was.get("total_lines", 0) - s["total_lines"])
    return 100.0 * delta / s["total_lines"], was


HOOKS_DIR = os.path.join("scripts", "hooks")


def install_hook(remove: bool = False) -> int:
    """Point git at `scripts/hooks/`, so the doc refreshes itself on commit.

    `core.hooksPath` rather than copying into `.git/hooks`: the hook is then a
    versioned file that everyone gets with the repo, and editing it is an
    ordinary commit instead of a thing each machine has its own copy of. The
    cost is that it REPLACES `.git/hooks` wholesale, so anything already living
    there stops running — checked for and reported rather than silently taken
    over.
    """
    if remove:
        subprocess.run(["git", "config", "--unset", "core.hooksPath"],
                       cwd=ROOT, check=False)
        print("hook removed — git is back to .git/hooks")
        return 0

    existing = [f for f in os.listdir(os.path.join(ROOT, ".git", "hooks"))
                if not f.endswith(".sample")] \
        if os.path.isdir(os.path.join(ROOT, ".git", "hooks")) else []
    if existing:
        print("NOT installed: .git/hooks already has " + ", ".join(existing) +
              ", and setting core.hooksPath would stop them running.\n"
              "Move them into scripts/hooks/ first, or install by hand.",
              file=sys.stderr)
        return 1

    hook = os.path.join(ROOT, HOOKS_DIR, "pre-commit")
    os.chmod(hook, 0o755)
    subprocess.run(["git", "config", "core.hooksPath", HOOKS_DIR],
                   cwd=ROOT, check=True)
    print(f"installed — core.hooksPath={HOOKS_DIR}\n"
          "CODE_SIZE.md now refreshes itself on every commit that moves it.\n"
          "Undo with: python -m scripts.code_stats --uninstall-hook")
    return 0


def main(argv: "list[str]") -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="rewrite CODE_SIZE.md")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if CODE_SIZE.md has drifted")
    ap.add_argument("--install-hook", action="store_true",
                    help="refresh the doc automatically on every commit")
    ap.add_argument("--uninstall-hook", action="store_true",
                    help="stop refreshing it automatically")
    args = ap.parse_args(argv)

    if args.install_hook or args.uninstall_hook:
        return install_hook(remove=args.uninstall_hook)

    s = collect()
    text = render(s)

    if args.check:
        pct, was = drift(s)
        if pct > DRIFT_PCT:
            claimed = was.get("total_lines") if was else "nothing"
            print(f"CODE_SIZE.md says {claimed}, the tree is "
                  f"{s['total_lines']} ({pct:.1f}% off). "
                  f"Run: python -m scripts.code_stats --write", file=sys.stderr)
            return 1
        print(f"CODE_SIZE.md is current ({pct:.1f}% drift, {s['total_lines']} lines)")
        return 0

    if args.write:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {os.path.relpath(OUT, ROOT)} "
              f"({s['total_lines']:,} lines, {s['total_files']} files)")
        return 0

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

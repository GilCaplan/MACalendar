"""Add Swift files to the iOS app target — the project lists every file by hand.

    python -m scripts.ios_add_files Engine LocalEngine.swift LocalCommand.swift

The first argument is a folder under `MACalendar-iOS/MACalendar-iOS/`; it
becomes (or joins) a group of that name beside `Voice`. Each file gets a file
reference, a build file, and a place in the APP target's Sources phase (the
phase that already compiles `OfflineReader.swift`). Ids are fresh, in the
project's own hand-numbered style, and a file already listed is left alone —
so running it twice changes nothing.

Why a script: the project file is not generated, and three hand edits per
file across four sections is how a file ends up in the tree but not the build.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PBX = ROOT / "MACalendar-iOS" / "MACalendar-iOS.xcodeproj" / "project.pbxproj"


def fresh_id(text: str, seed: int) -> str:
    n = seed
    while True:
        cand = f"AE{n:06X}0000000000000000"[:24]
        if cand not in text:
            return cand
        n += 1


def before_marker(text: str, section: str, entry: str) -> str:
    """`entry` (one line, two tabs in) just before `/* End <section> section */`,
    keeping the marker's own indentation (this project indents two of them)."""
    return re.sub(r"(\t*)/\* End " + section + r" section \*/",
                  lambda m: f"\t\t{entry}\n{m.group(1)}/* End {section} section */", text, count=1)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder, files = argv[0], argv[1:]
    text = PBX.read_text()
    for f in files:
        if not (ROOT / "MACalendar-iOS" / "MACalendar-iOS" / folder / f).exists():
            print(f"no such file: {folder}/{f}", file=sys.stderr)
            return 2
    # the group: reuse it, or make it beside Voice in the same parent
    gm = re.search(r"(\w{24}) /\* " + re.escape(folder) + r" \*/ = \{\n\t+isa = PBXGroup;", text)
    if gm:
        group_id = gm.group(1)
    else:
        group_id = fresh_id(text, 0x10)
        voice = re.search(r"(\w{24}) /\* Voice \*/ = \{", text).group(1)
        # add to the parent group's children, after Voice
        text = re.sub(r"(\t+)" + voice + r" /\* Voice \*/,\n",
                      lambda m: f"{m.group(0)}{m.group(1)}{group_id} /* {folder} */,\n", text, count=1)
        block = (f"{group_id} /* {folder} */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n\t\t\t);\n"
                 f"\t\t\tpath = {folder};\n\t\t\tsourceTree = \"<group>\";\n\t\t}};")
        text = before_marker(text, "PBXGroup", block)
    # the app's Sources phase: the one compiling OfflineReader.swift
    phase = re.search(r"isa = PBXSourcesBuildPhase;\n\t+buildActionMask = \d+;\n\t+files = \(\n"
                      r"(?:(?!\);).)*?OfflineReader\.swift in Sources", text, re.S)
    if not phase:
        print("could not find the app's Sources phase", file=sys.stderr)
        return 2
    added = 0
    for i, f in enumerate(files):
        if re.search(r"/\* " + re.escape(f) + r" \*/ = \{isa = PBXFileReference", text):
            continue
        ref = fresh_id(text, 0x100 + i * 2)
        text_tmp = text + ref
        bld = fresh_id(text_tmp, 0x100 + i * 2 + 1)
        text = before_marker(text, "PBXFileReference",
                             f"{ref} /* {f} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; "
                             f"path = {f}; sourceTree = \"<group>\"; }};")
        text = before_marker(text, "PBXBuildFile",
                             f"{bld} /* {f} in Sources */ = {{isa = PBXBuildFile; fileRef = {ref} /* {f} */; }};")
        text = re.sub(r"(\t\t" + group_id + r" /\* " + re.escape(folder) + r" \*/ = \{\n\t+isa = PBXGroup;\n\t+children = \(\n)",
                      lambda m: m.group(1) + f"\t\t\t\t{ref} /* {f} */,\n", text, count=1)
        phase = re.search(r"isa = PBXSourcesBuildPhase;\n\t+buildActionMask = \d+;\n\t+files = \(\n"
                          r"(?:(?!\);).)*?OfflineReader\.swift in Sources", text, re.S)
        start = phase.start()
        head = text.index("files = (\n", start) + len("files = (\n")
        text = text[:head] + f"\t\t\t\t{bld} /* {f} in Sources */,\n" + text[head:]
        added += 1
    PBX.write_text(text)
    print(f"{added} file(s) added to {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

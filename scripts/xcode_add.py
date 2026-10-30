"""Add Swift files to the iPhone project — the step every new tab tripped on.

    python scripts/xcode_add.py MACalendar-iOS/Features/Thing/ThingView.swift [...]
    python scripts/xcode_add.py --check          # list .swift files the project misses

`project.pbxproj` lists every source file FOUR times (a file reference, its
folder group, a build file, the target's Sources phase), by hand-picked 24-hex
ids. The Flashcards tab needed 36 such lines; get one wrong and the file is
silently not compiled, or Xcode refuses to open the project. This writes them.

Paths are relative to `MACalendar-iOS/` (the folder holding the .xcodeproj).
The TARGET comes from the first folder — `MACalendar-iOS/` is the app,
`MACalendarUITests/` the UI tests, `MACalendarWidgets/` the widgets — and the
GROUPS follow the folders, created when missing. Running it twice changes
nothing. Ids are derived from the path, so two people adding the same file get
the same lines rather than a merge conflict of random ids.

`tests/unit/test_ios_project.py` runs `--check`: a .swift file under a target
folder that the project does not compile fails the build. (`Tools/` holds the
command-line tools and is no target's, on purpose.)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys

IOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "MACalendar-iOS")
PBXPROJ = os.path.join(IOS, "MACalendar-iOS.xcodeproj", "project.pbxproj")

#: first folder -> native target name
TARGETS = {
    "MACalendar-iOS": "MACalendar-iOS",
    "MACalendarUITests": "MACalendarUITests",
    "MACalendarWidgets": "MACalendarWidgets",
}

_START = re.compile(r"^\t+([0-9A-F]{24,32})(?: /\* (.*?) \*/)? = \{", re.M)


class Project:
    def __init__(self, text: str) -> None:
        self.text = text
        self.objects: dict[str, tuple[str, str]] = {}     # id -> (comment, body)
        for m in _START.finditer(text):
            if m.group(1) in self.objects:
                # PBXProject's TargetAttributes re-use target ids as keys,
                # deeper down; the definition is the first occurrence.
                continue
            line_end = text.index("\n", m.end())
            if text[m.end():line_end].rstrip().endswith("};"):
                body = text[m.end():line_end]
            else:
                close = text.index("\n\t\t};", m.end())
                body = text[m.end():close]
            self.objects[m.group(1)] = (m.group(2) or "", body)

    # -- reading

    def isa(self, oid: str) -> str:
        m = re.search(r"isa = (\w+);", self.objects[oid][1])
        return m.group(1) if m else ""

    def field(self, oid: str, name: str) -> str | None:
        m = re.search(rf"\b{name} = (\"[^\"]*\"|[^;]+);", self.objects[oid][1])
        return m.group(1).strip('"') if m else None

    def children(self, oid: str) -> list[str]:
        m = re.search(r"children = \((.*?)\);", self.objects[oid][1], re.S)
        return re.findall(r"([0-9A-F]{24,32})", m.group(1)) if m else []

    def main_group(self) -> str:
        return re.search(r"mainGroup = ([0-9A-F]{24,32});", self.text).group(1)

    def child_named(self, group: str, name: str) -> str | None:
        for c in self.children(group):
            if c in self.objects and (self.field(c, "path") or self.field(c, "name")) == name:
                return c
        return None

    def sources_phase(self, target: str) -> str:
        for oid in self.objects:
            if self.isa(oid) == "PBXNativeTarget" and self.field(oid, "name") == target:
                for ph in re.findall(r"([0-9A-F]{24,32})", re.search(
                        r"buildPhases = \((.*?)\);", self.objects[oid][1], re.S).group(1)):
                    if self.isa(ph) == "PBXSourcesBuildPhase":
                        return ph
        raise SystemExit(f"no Sources phase for target {target!r}")

    def phase_files(self, phase: str) -> list[str]:
        m = re.search(r"files = \((.*?)\);", self.objects[phase][1], re.S)
        return re.findall(r"([0-9A-F]{24,32})", m.group(1)) if m else []

    def compiled(self) -> dict[str, set[str]]:
        """target -> every source path (relative to MACalendar-iOS/) it compiles."""
        paths: dict = {}

        def walk(group, prefix):
            for c in self.children(group):
                if c not in self.objects:
                    continue
                p = self.field(c, "path")
                here = os.path.join(prefix, p) if p else prefix
                if self.isa(c) == "PBXGroup":
                    walk(c, here)
                elif self.isa(c) == "PBXFileReference":
                    paths[c] = os.path.normpath(here)
        walk(self.main_group(), "")
        out = {}
        for target in TARGETS.values():
            refs = {self.field(b, "fileRef") for b in self.phase_files(self.sources_phase(target))}
            refs = {r.split()[0] for r in refs if r}
            out[target] = {paths[r] for r in refs if r in paths}
        return out

    # -- writing

    def _new_id(self, seed: str) -> str:
        n = 0
        while True:
            oid = hashlib.sha1(f"{seed}#{n}".encode()).hexdigest()[:24].upper()
            if oid not in self.objects and oid not in self.text:
                return oid
            n += 1

    def _insert_section(self, section: str, line: str) -> None:
        m = re.search(rf"^[\t ]*/\* End {section} section \*/", self.text, re.M)
        self.text = self.text[:m.start()] + line + "\n" + self.text[m.start():]

    def _append_list(self, oid: str, key: str, entry: str) -> None:
        start = re.search(rf"^\t\t{oid}(?: /\* .*? \*/)? = \{{", self.text, re.M)
        lst = re.compile(rf"(\t\t\t{key} = \(\n)(.*?)(\t\t\t\);)", re.S)
        mm = lst.search(self.text, start.end())
        self.text = self.text[:mm.end(2)] + f"\t\t\t\t{entry},\n" + self.text[mm.end(2):]
        self.__init__(self.text)

    def add(self, rel: str, target: str | None = None) -> bool:
        rel = os.path.normpath(rel)
        parts = rel.split(os.sep)
        target = target or TARGETS.get(parts[0])
        if target is None:
            raise SystemExit(f"{rel}: first folder must be one of {', '.join(TARGETS)}")
        group = self.main_group()
        for i, folder in enumerate(parts[:-1]):
            nxt = self.child_named(group, folder)
            if nxt is None:
                nxt = self._new_id("group:" + "/".join(parts[:i + 1]))
                self._insert_section("PBXGroup", (
                    f"\t\t{nxt} /* {folder} */ = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n"
                    f"\t\t\t);\n\t\t\tpath = {folder};\n\t\t\tsourceTree = \"<group>\";\n\t\t}};"))
                self.__init__(self.text)
                self._append_list(group, "children", f"{nxt} /* {folder} */")
            group = nxt
        name = parts[-1]
        ref = self.child_named(group, name)
        changed = False
        if ref is None:
            ref = self._new_id("file:" + rel)
            q = f'"{name}"' if re.search(r"[^\w.]", name) else name
            self._insert_section("PBXFileReference", (
                f"\t\t{ref} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = "
                f"sourcecode.swift; path = {q}; sourceTree = \"<group>\"; }};"))
            self.__init__(self.text)
            self._append_list(group, "children", f"{ref} /* {name} */")
            changed = True
        phase = self.sources_phase(target)
        if not any((self.field(b, "fileRef") or "").startswith(ref) for b in self.phase_files(phase)):
            bf = self._new_id(f"build:{target}:" + rel)
            self._insert_section("PBXBuildFile", (
                f"\t\t{bf} /* {name} in Sources */ = {{isa = PBXBuildFile; "
                f"fileRef = {ref} /* {name} */; }};"))
            self.__init__(self.text)
            self._append_list(phase, "files", f"{bf} /* {name} in Sources */")
            changed = True
        return changed


def missing(project: Project) -> list[str]:
    compiled = project.compiled()
    out = []
    for folder, target in TARGETS.items():
        root = os.path.join(IOS, folder)
        for dirpath, _, files in os.walk(root):
            for f in files:
                if f.endswith(".swift"):
                    rel = os.path.normpath(os.path.relpath(os.path.join(dirpath, f), IOS))
                    if rel not in compiled[target]:
                        out.append(rel)
    return sorted(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", help="paths relative to MACalendar-iOS/")
    ap.add_argument("--target", help="override the target the folder implies")
    ap.add_argument("--check", action="store_true", help="list .swift files the project misses")
    ap.add_argument("--project", default=PBXPROJ)
    a = ap.parse_args(argv)
    with open(a.project, encoding="utf-8") as f:
        project = Project(f.read())
    if a.check:
        gone = missing(project)
        for g in gone:
            print("not compiled:", g)
        return 1 if gone else 0
    changed = [rel for rel in a.files if project.add(rel, a.target)]
    if changed:
        with open(a.project, "w", encoding="utf-8") as f:
            f.write(project.text)
    for rel in a.files:
        print(("added    " if rel in changed else "present  ") + rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())

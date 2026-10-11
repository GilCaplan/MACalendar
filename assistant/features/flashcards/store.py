"""Flashcards' own store: subjects, sets, cards, progress, and their pictures.

A separate SQLite file beside the calendar (`flashcards.db`, override
`MACALENDAR_FLASHCARDS`), resolved per user like every personal store
(`users.paths.resolve`). Separate because nothing here joins to the calendar,
and a study deck of a few thousand cards has no business inside the database
the engine writes events into. Pictures live in `flashcards_media/<set id>/`
next to it, under the path the set file used, so a card keeps saying
`images/map.jpg` and the server maps it.

Three ways a card gets in, one rule for all of them (`cardformat.normalise`):
importing a set file (`import_doc`), the editor (`add_card` / `update_card`),
and the INBOX — a folder any agent can drop a set file or .zip into, picked up
on the next `import_inbox()` and moved to `inbox/imported/` (or
`inbox/failed/` beside a `.error.txt` saying why).

Progress survives a re-import: a card is matched by `cardformat.key` (its
content minus tags, page and explanation), so correcting a file and importing
it again resets only the cards whose substance changed.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import random
import re
import shutil
import sqlite3
import zipfile
from contextlib import contextmanager

from assistant.features.flashcards import cardformat, fsrs

DEFAULT_PATH = os.path.expanduser("~/.assistant_tools/flashcards.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  client_token TEXT UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sets (
  id INTEGER PRIMARY KEY,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  slug TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
  lang TEXT NOT NULL DEFAULT '', dir TEXT NOT NULL DEFAULT 'ltr',
  client_token TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(subject_id, slug));
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY,
  set_id INTEGER NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, type TEXT NOT NULL, body TEXT NOT NULL,
  key TEXT NOT NULL, client_token TEXT UNIQUE,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(set_id, key));
CREATE TABLE IF NOT EXISTS progress (
  card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  item TEXT NOT NULL DEFAULT '',
  stability REAL, difficulty REAL, due TEXT NOT NULL, last TEXT NOT NULL,
  reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(card_id, item));
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  item TEXT NOT NULL DEFAULT '', grade INTEGER NOT NULL, at TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '', client_token TEXT UNIQUE);
"""


class FlashcardError(ValueError):
    """Something the caller asked for that cannot be done, said as a sentence."""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(d: _dt.datetime) -> str:
    return d.astimezone(_dt.timezone.utc).isoformat(timespec="seconds")


def _parse(s: str) -> _dt.datetime:
    d = _dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def _slug(name: str) -> str:
    s = re.sub(r"[^\w-]+", "-", name.strip().lower(), flags=re.U).strip("-")
    return s or "set"


def _safe_rel(path: str) -> str:
    """A picture path from a set file, refused if it climbs out of its folder."""
    p = os.path.normpath(str(path).strip().lstrip("/"))
    if p.startswith("..") or os.path.isabs(p) or not p or p == ".":
        raise FlashcardError(f"Picture path {path!r} must stay inside the set's folder.")
    return p


class FlashcardStore:
    def __init__(self, path: "str | None" = None) -> None:
        if path is None:
            from assistant.users import paths as _paths
            path = _paths.resolve(os.environ.get("MACALENDAR_FLASHCARDS") or DEFAULT_PATH)
        self.path = path
        base = os.path.dirname(os.path.abspath(path))
        self.media_dir = os.path.join(base, "flashcards_media")
        self.inbox_dir = os.path.join(base, "flashcards_inbox")
        os.makedirs(base, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------ library

    def library(self, now: "_dt.datetime | None" = None) -> "list[dict]":
        """Every subject with its sets and their counts — the tab's front page."""
        now_s = _iso(now or _now())
        with self._conn() as c:
            subjects = [dict(r) for r in c.execute(
                "SELECT id, name FROM subjects ORDER BY name COLLATE NOCASE")]
            sets = [dict(r) for r in c.execute(
                "SELECT id, subject_id, slug, name, source, lang, dir, updated_at "
                "FROM sets ORDER BY id")]
            cards = c.execute("SELECT id, set_id, type, body FROM cards").fetchall()
            prog = {(r["card_id"], r["item"]): r["due"] for r in c.execute(
                "SELECT card_id, item, due FROM progress")}
        counts: dict = {}
        for r in cards:
            cnt = counts.setdefault(r["set_id"], {"cards": 0, "items": 0, "seen": 0, "due": 0})
            cnt["cards"] += 1
            for it in cardformat.items(json.loads(r["body"])):
                cnt["items"] += 1
                due = prog.get((r["id"], it))
                if due is not None:
                    cnt["seen"] += 1
                    cnt["due"] += due <= now_s
        for s in sets:
            s.update(counts.get(s["id"], {"cards": 0, "items": 0, "seen": 0, "due": 0}))
        for sub in subjects:
            sub["sets"] = [s for s in sets if s["subject_id"] == sub["id"]]
        return subjects

    # ------------------------------------------------------------ subjects / sets

    def subject_id(self, name: str, *, create: bool = True, client_token: str = "") -> int:
        name = (name or "").strip()
        if not name:
            raise FlashcardError("A subject needs a name.")
        with self._conn() as c:
            if client_token:
                r = c.execute("SELECT id FROM subjects WHERE client_token=?", (client_token,)).fetchone()
                if r:
                    return r["id"]
            r = c.execute("SELECT id FROM subjects WHERE name=?", (name,)).fetchone()
            if r:
                return r["id"]
            if not create:
                raise FlashcardError(f"No subject called {name!r}.")
            return c.execute(
                "INSERT INTO subjects(name, client_token, created_at) VALUES (?,?,?)",
                (name, client_token or None, _iso(_now()))).lastrowid

    def rename_subject(self, subject_id: int, name: str) -> None:
        name = (name or "").strip()
        if not name:
            raise FlashcardError("A subject needs a name.")
        with self._conn() as c:
            try:
                n = c.execute("UPDATE subjects SET name=? WHERE id=?", (name, subject_id)).rowcount
            except sqlite3.IntegrityError:
                raise FlashcardError(f"There is already a subject called {name!r}.")
        if not n:
            raise FlashcardError(f"No subject {subject_id}.")

    def delete_subject(self, subject_id: int) -> None:
        for s in self._sets_of(subject_id):
            self.delete_set(s)
        with self._conn() as c:
            c.execute("DELETE FROM subjects WHERE id=?", (subject_id,))

    def _sets_of(self, subject_id: int) -> "list[int]":
        with self._conn() as c:
            return [r["id"] for r in c.execute("SELECT id FROM sets WHERE subject_id=?", (subject_id,))]

    def create_set(self, subject: "int | str", name: str, *, slug: str = "",
                   source: str = "", lang: str = "", dir: str = "",
                   client_token: str = "") -> int:
        sid = subject if isinstance(subject, int) else self.subject_id(subject)
        name = (name or "").strip()
        if not name:
            raise FlashcardError("A set needs a name.")
        slug = _slug(slug or name)
        direction = (dir or ("rtl" if lang in ("he", "ar", "yi", "fa") else "ltr")).lower()
        if direction not in ("ltr", "rtl"):
            raise FlashcardError("'dir' is ltr or rtl.")
        now = _iso(_now())
        with self._conn() as c:
            if client_token:
                r = c.execute("SELECT id FROM sets WHERE client_token=?", (client_token,)).fetchone()
                if r:
                    return r["id"]
            if not c.execute("SELECT 1 FROM subjects WHERE id=?", (sid,)).fetchone():
                raise FlashcardError(f"No subject {sid}.")
            base, n = slug, 2
            while c.execute("SELECT 1 FROM sets WHERE subject_id=? AND slug=?", (sid, slug)).fetchone():
                slug, n = f"{base}-{n}", n + 1
            return c.execute(
                "INSERT INTO sets(subject_id, slug, name, source, lang, dir, client_token,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, slug, name, source or "", lang or "", direction,
                 client_token or None, now, now)).lastrowid

    def update_set(self, set_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("name", "source", "lang", "dir", "subject_id")}
        if "subject" in fields:
            allowed["subject_id"] = self.subject_id(str(fields["subject"]))
        if "dir" in allowed and allowed["dir"] not in ("ltr", "rtl"):
            raise FlashcardError("'dir' is ltr or rtl.")
        if "name" in allowed and not str(allowed["name"]).strip():
            raise FlashcardError("A set needs a name.")
        if not allowed:
            return
        sets = ", ".join(f"{k}=?" for k in allowed)
        with self._conn() as c:
            n = c.execute(f"UPDATE sets SET {sets}, updated_at=? WHERE id=?",
                          (*allowed.values(), _iso(_now()), set_id)).rowcount
        if not n:
            raise FlashcardError(f"No set {set_id}.")

    def delete_set(self, set_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sets WHERE id=?", (set_id,))
        shutil.rmtree(os.path.join(self.media_dir, str(set_id)), ignore_errors=True)

    def get_set(self, set_id: int) -> dict:
        """One set with every card and its progress — what the phone caches."""
        with self._conn() as c:
            s = c.execute("SELECT s.*, sub.name AS subject FROM sets s JOIN subjects sub "
                          "ON sub.id = s.subject_id WHERE s.id=?", (set_id,)).fetchone()
            if s is None:
                raise FlashcardError(f"No set {set_id}.")
            rows = c.execute("SELECT id, position, body FROM cards WHERE set_id=? "
                             "ORDER BY position, id", (set_id,)).fetchall()
            prog = c.execute("SELECT p.* FROM progress p JOIN cards k ON k.id=p.card_id "
                             "WHERE k.set_id=?", (set_id,)).fetchall()
        by_card: dict = {}
        for p in prog:
            by_card.setdefault(p["card_id"], {})[p["item"]] = _prog_out(p)
        out = {k: s[k] for k in ("id", "subject_id", "subject", "slug", "name", "source",
                                 "lang", "dir", "updated_at")}
        out["cards"] = [{"id": r["id"], "position": r["position"], **json.loads(r["body"]),
                         "items": cardformat.items(json.loads(r["body"])),
                         "progress": by_card.get(r["id"], {})} for r in rows]
        return out

    def export_doc(self, set_id: int) -> dict:
        """The set as a set file again — round-trips through `import_doc`."""
        s = self.get_set(set_id)
        doc = {"subject": s["subject"], "set": s["name"], "set_id": s["slug"]}
        for k in ("lang", "dir", "source"):
            if s[k]:
                doc[k] = s[k]
        doc["cards"] = [{k: v for k, v in c.items() if k not in ("id", "position", "items", "progress")}
                        for c in s["cards"]]
        return doc

    # ------------------------------------------------------------ cards

    def add_card(self, set_id: int, card: dict, *, client_token: str = "") -> int:
        clean = cardformat.normalise(card)
        self._check_images(set_id, [clean])
        k = cardformat.key(clean)
        now = _iso(_now())
        with self._conn() as c:
            if client_token:
                r = c.execute("SELECT id FROM cards WHERE client_token=?", (client_token,)).fetchone()
                if r:
                    return r["id"]
            if not c.execute("SELECT 1 FROM sets WHERE id=?", (set_id,)).fetchone():
                raise FlashcardError(f"No set {set_id}.")
            if c.execute("SELECT 1 FROM cards WHERE set_id=? AND key=?", (set_id, k)).fetchone():
                raise FlashcardError("That set already has this exact card.")
            pos = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM cards WHERE set_id=?",
                            (set_id,)).fetchone()[0]
            cid = c.execute(
                "INSERT INTO cards(set_id, position, type, body, key, client_token, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (set_id, pos, clean["type"], json.dumps(clean, ensure_ascii=False), k,
                 client_token or None, now, now)).lastrowid
            c.execute("UPDATE sets SET updated_at=? WHERE id=?", (now, set_id))
            return cid

    def update_card(self, card_id: int, card: dict) -> None:
        clean = cardformat.normalise(card)
        with self._conn() as c:
            r = c.execute("SELECT set_id, body FROM cards WHERE id=?", (card_id,)).fetchone()
            if r is None:
                raise FlashcardError(f"No card {card_id}.")
        self._check_images(r["set_id"], [clean])
        old = json.loads(r["body"])
        now = _iso(_now())
        with self._conn() as c:
            try:
                c.execute("UPDATE cards SET type=?, body=?, key=?, updated_at=? WHERE id=?",
                          (clean["type"], json.dumps(clean, ensure_ascii=False),
                           cardformat.key(clean), now, card_id))
            except sqlite3.IntegrityError:
                raise FlashcardError("That set already has this exact card.")
            # Progress on items that no longer exist (a blank removed, a label
            # dropped) is meaningless; the rest is kept.
            gone = set(cardformat.items(old)) - set(cardformat.items(clean))
            for it in gone:
                c.execute("DELETE FROM progress WHERE card_id=? AND item=?", (card_id, it))
            c.execute("UPDATE sets SET updated_at=? WHERE id=?", (now, r["set_id"]))

    def delete_card(self, card_id: int) -> None:
        with self._conn() as c:
            n = c.execute("DELETE FROM cards WHERE id=?", (card_id,)).rowcount
        if not n:
            raise FlashcardError(f"No card {card_id}.")

    # ------------------------------------------------------------ pictures

    def media_path(self, set_id: int, rel: str) -> str:
        return os.path.join(self.media_dir, str(set_id), _safe_rel(rel))

    def save_media(self, set_id: int, rel: str, data: bytes) -> str:
        path = self.media_path(set_id, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return _safe_rel(rel)

    def _check_images(self, set_id: int, cards: "list[dict]", pending: "dict | None" = None) -> None:
        for card in cards:
            for rel in cardformat.images(card):
                rel = _safe_rel(rel)
                if pending and rel in pending:
                    continue
                if not os.path.exists(self.media_path(set_id, rel)):
                    raise FlashcardError(
                        f"The picture {rel!r} is not in this set. Import the set as a .zip "
                        "holding the picture beside the set file, or add the picture first.")

    # ------------------------------------------------------------ import

    def import_doc(self, doc: dict, *, media: "dict[str, bytes] | None" = None,
                   mode: str = "replace", base_dir: "str | None" = None) -> "list[dict]":
        """Import one set file (or a file with `sets:`). Returns a summary per set.

        `mode="replace"` makes the set exactly the file: cards no longer in it
        are removed. `mode="append"` only adds cards the set does not have —
        the mode for an agent adding to a set somebody is already studying.
        Either way a card already present keeps its progress.
        """
        if mode not in ("replace", "append"):
            raise FlashcardError("mode is 'replace' or 'append'.")
        if not isinstance(doc, dict):
            raise FlashcardError("A set file is a mapping with subject, set and cards.")
        subject = str(doc.get("subject") or "").strip()
        if not subject:
            raise FlashcardError("The file needs a 'subject' (the group its sets belong to).")
        if "sets" in doc:
            shared = {k: doc[k] for k in ("lang", "dir", "source") if k in doc}
            return [x for s in doc["sets"] for x in self.import_doc(
                {"subject": subject, **shared, **s}, media=media, mode=mode, base_dir=base_dir)]
        name = str(doc.get("set") or "").strip()
        if not name:
            raise FlashcardError("The file needs a 'set' name.")
        raw = doc.get("cards")
        if not isinstance(raw, list) or not raw:
            raise FlashcardError(f"Set {name!r} has no cards.")
        errors, cards = [], []
        for i, card in enumerate(raw):
            try:
                cards.append(cardformat.normalise(card, where=f"{name}, card {i + 1}"))
            except cardformat.CardError as e:
                errors.append(str(e))
        if errors:
            more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
            raise FlashcardError("; ".join(errors[:5]) + more)

        # Pictures: from the zip, else beside the file on disk.
        pending: dict = {}
        for card in cards:
            for rel in cardformat.images(card):
                rel = _safe_rel(rel)
                if media and rel in media:
                    pending[rel] = media[rel]
                elif base_dir and os.path.isfile(os.path.join(base_dir, rel)):
                    with open(os.path.join(base_dir, rel), "rb") as f:
                        pending[rel] = f.read()

        sid = self.subject_id(subject)
        slug = _slug(str(doc.get("set_id") or name))
        with self._conn() as c:
            r = c.execute("SELECT id FROM sets WHERE subject_id=? AND slug=?", (sid, slug)).fetchone()
        set_id = r["id"] if r else self.create_set(
            sid, name, slug=slug, source=str(doc.get("source") or ""),
            lang=str(doc.get("lang") or ""), dir=str(doc.get("dir") or ""))
        if r:
            self.update_set(set_id, name=name, **{k: str(doc[k]) for k in ("source", "lang", "dir") if doc.get(k)})
        self._check_images(set_id, cards, pending)
        for rel, data in pending.items():
            self.save_media(set_id, rel, data)

        now = _iso(_now())
        added = kept = 0
        with self._conn() as c:
            have = {row["key"]: row["id"] for row in c.execute(
                "SELECT id, key FROM cards WHERE set_id=?", (set_id,))}
            seen: set = set()
            start = 0 if mode == "replace" else c.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM cards WHERE set_id=?", (set_id,)).fetchone()[0]
            for pos, card in enumerate(cards, start):
                k = cardformat.key(card)
                if k in seen:
                    continue            # the same card twice in one file
                seen.add(k)
                body = json.dumps(card, ensure_ascii=False)
                if k in have:
                    kept += 1
                    if mode == "replace":
                        c.execute("UPDATE cards SET position=?, body=?, updated_at=? WHERE id=?",
                                  (pos, body, now, have[k]))
                    continue
                c.execute("INSERT INTO cards(set_id, position, type, body, key, created_at, updated_at)"
                          " VALUES (?,?,?,?,?,?,?)", (set_id, pos, card["type"], body, k, now, now))
                added += 1
            removed = 0
            if mode == "replace":
                stale = [cid for key_, cid in have.items() if key_ not in seen]
                for cid in stale:
                    c.execute("DELETE FROM cards WHERE id=?", (cid,))
                removed = len(stale)
            c.execute("UPDATE sets SET updated_at=? WHERE id=?", (now, set_id))
        return [{"subject": subject, "set": name, "set_id": set_id, "added": added,
                 "kept": kept, "removed": removed}]

    def import_file(self, filename: str, data: bytes, *, mode: str = "replace") -> "list[dict]":
        """A .yaml/.yml/.json set file, or a .zip of set files and their pictures."""
        low = filename.lower()
        if low.endswith(".zip"):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                raise FlashcardError(f"{filename} is not a readable .zip.")
            names = [n for n in zf.namelist() if not n.endswith("/") and "__MACOSX" not in n]
            docs = [n for n in names if n.lower().endswith((".yaml", ".yml", ".json"))]
            if not docs:
                raise FlashcardError(f"{filename} holds no .yaml or .json set file.")
            out = []
            for d in sorted(docs):
                folder = os.path.dirname(d)
                media = {os.path.relpath(n, folder) if folder else n: zf.read(n)
                         for n in names if n not in docs and (not folder or n.startswith(folder + "/"))}
                out += self.import_doc(_load(d, zf.read(d)), media=media, mode=mode)
            return out
        if low.endswith((".yaml", ".yml", ".json")):
            return self.import_doc(_load(filename, data), mode=mode)
        raise FlashcardError(f"{filename}: import a .yaml, .json or .zip file.")

    def import_path(self, path: str, *, mode: str = "replace") -> "list[dict]":
        """A file on disk; pictures are looked for beside it."""
        with open(path, "rb") as f:
            data = f.read()
        if path.lower().endswith(".zip"):
            return self.import_file(os.path.basename(path), data, mode=mode)
        return self.import_doc(_load(path, data), mode=mode, base_dir=os.path.dirname(os.path.abspath(path)))

    def import_inbox(self) -> "list[dict]":
        """Import every set file dropped into the inbox; move each one out after.

        This is the agent door: write a set file (FORMAT.md) into
        `flashcards_inbox/` and it is in the tab the next time the tab loads.
        A file whose name contains `.append.` adds to its set instead of
        replacing it. Pictures sit beside the file under the paths it names.
        """
        os.makedirs(self.inbox_dir, exist_ok=True)
        results = []
        # Replacing files first: an `.append.` file for the same set must land
        # on top of the replacement, not be wiped by it.
        for name in sorted(os.listdir(self.inbox_dir), key=lambda n: (".append." in n.lower(), n)):
            path = os.path.join(self.inbox_dir, name)
            if not os.path.isfile(path) or not name.lower().endswith((".yaml", ".yml", ".json", ".zip")):
                continue
            mode = "append" if ".append." in name.lower() else "replace"
            try:
                res = self.import_path(path, mode=mode)
                dest = os.path.join(self.inbox_dir, "imported")
                results += [{**r, "file": name} for r in res]
            except Exception as e:      # noqa: BLE001 — one bad file must not block the rest
                dest = os.path.join(self.inbox_dir, "failed")
                os.makedirs(dest, exist_ok=True)
                with open(os.path.join(dest, name + ".error.txt"), "w", encoding="utf-8") as f:
                    f.write(str(e) + "\n")
                results.append({"file": name, "error": str(e)})
            os.makedirs(dest, exist_ok=True)
            stamp = _now().strftime("%Y%m%d-%H%M%S")
            shutil.move(path, os.path.join(dest, f"{stamp}-{name}"))
        return results

    # ------------------------------------------------------------ study

    def study(self, set_ids: "list[int]", *, mode: str = "smart", types: "list[str] | None" = None,
              limit: int = 20, now: "_dt.datetime | None" = None, seed: "int | None" = None) -> "list[dict]":
        """A session's queue across one, several or all sets, mixed.

        smart: items due now (most overdue first), then new ones.
        all:   every item, shuffled.
        exam:  multiple-choice only, shuffled — the shape of the officer exam.
        """
        if mode not in ("smart", "all", "exam"):
            raise FlashcardError("mode is smart, all or exam.")
        if not set_ids:
            raise FlashcardError("Pick at least one set to study.")
        rng = random.Random(seed)
        now_s = _iso(now or _now())
        marks = ",".join("?" * len(set_ids))
        with self._conn() as c:
            rows = c.execute(
                f"SELECT k.id, k.set_id, k.body, s.name AS set_name, s.dir FROM cards k "
                f"JOIN sets s ON s.id=k.set_id WHERE k.set_id IN ({marks})", list(set_ids)).fetchall()
            prog = {(r["card_id"], r["item"]): dict(r) for r in c.execute(
                f"SELECT p.* FROM progress p JOIN cards k ON k.id=p.card_id WHERE k.set_id IN ({marks})",
                list(set_ids))}
        want = {"mc"} if mode == "exam" else (set(types) if types else set(cardformat.TYPES))
        due, new = [], []
        for r in rows:
            card = json.loads(r["body"])
            if card["type"] not in want:
                continue
            for it in cardformat.items(card):
                p = prog.get((r["id"], it))
                entry = {"card_id": r["id"], "item": it, "set_id": r["set_id"], "set": r["set_name"],
                         "dir": r["dir"], "card": card, "progress": _prog_out(p) if p else None}
                if p is None:
                    new.append(entry)
                elif mode != "smart" or p["due"] <= now_s:
                    due.append(entry)
        if mode == "smart":
            due.sort(key=lambda e: e["progress"]["due"])
            rng.shuffle(new)
            queue = due + new
        else:
            queue = due + new
            rng.shuffle(queue)
        return queue[:limit] if limit and limit > 0 else queue

    def review(self, card_id: int, item: str, grade: int, *, at: "str | None" = None,
               source: str = "", client_token: str = "") -> dict:
        """Record one answer and move the item. `at` is when it happened, so a
        review the phone queued on a train schedules from the train, not from
        the moment it synced."""
        if grade not in (1, 2, 3, 4):
            raise FlashcardError("grade is 1 (again), 2 (hard), 3 (good) or 4 (easy).")
        when = _parse(at) if at else _now()
        with self._conn() as c:
            if client_token and c.execute("SELECT 1 FROM reviews WHERE client_token=?",
                                          (client_token,)).fetchone():
                p = c.execute("SELECT * FROM progress WHERE card_id=? AND item=?", (card_id, item)).fetchone()
                return _prog_out(p) if p else {}
            r = c.execute("SELECT body FROM cards WHERE id=?", (card_id,)).fetchone()
            if r is None:
                raise FlashcardError(f"No card {card_id}.")
            if item not in cardformat.items(json.loads(r["body"])):
                raise FlashcardError(f"Card {card_id} has no item {item!r}.")
            p = c.execute("SELECT * FROM progress WHERE card_id=? AND item=?", (card_id, item)).fetchone()
            if p is not None and _parse(p["last"]) > when:
                # An older answer arriving after a newer one (two devices, one
                # offline): log it, but do not let it rewind the schedule.
                c.execute("INSERT INTO reviews(card_id, item, grade, at, source, client_token)"
                          " VALUES (?,?,?,?,?,?)", (card_id, item, grade, _iso(when), source, client_token or None))
                return _prog_out(p)
            elapsed = (when - _parse(p["last"])).total_seconds() / 86400 if p else 0.0
            s, d = fsrs.next_state(p["stability"] if p else None, p["difficulty"] if p else None,
                                   elapsed, grade)
            due = when + (_dt.timedelta(minutes=fsrs.RELEARN_MINUTES) if grade == 1
                          else _dt.timedelta(days=fsrs.interval_days(s)))
            reps = (p["reps"] if p else 0) + 1
            lapses = (p["lapses"] if p else 0) + (grade == 1 and p is not None)
            c.execute("INSERT INTO progress(card_id, item, stability, difficulty, due, last, reps, lapses)"
                      " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(card_id, item) DO UPDATE SET"
                      " stability=excluded.stability, difficulty=excluded.difficulty, due=excluded.due,"
                      " last=excluded.last, reps=excluded.reps, lapses=excluded.lapses",
                      (card_id, item, s, d, _iso(due), _iso(when), reps, lapses))
            c.execute("INSERT INTO reviews(card_id, item, grade, at, source, client_token) VALUES (?,?,?,?,?,?)",
                      (card_id, item, grade, _iso(when), source, client_token or None))
            return _prog_out(c.execute("SELECT * FROM progress WHERE card_id=? AND item=?",
                                       (card_id, item)).fetchone())

    def reset_progress(self, set_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM progress WHERE card_id IN (SELECT id FROM cards WHERE set_id=?)", (set_id,))


def _prog_out(p) -> dict:
    return {k: p[k] for k in ("stability", "difficulty", "due", "last", "reps", "lapses")}


def _load(name: str, data: bytes) -> dict:
    text = data.decode("utf-8-sig")
    try:
        if name.lower().endswith(".json"):
            return json.loads(text)
        import yaml
        return yaml.safe_load(text)
    except Exception as e:          # noqa: BLE001
        raise FlashcardError(f"{os.path.basename(name)} could not be read: {e}")

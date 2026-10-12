"""FlashcardsView — the Mac's Flashcards tab: library, study round, editor.

Three pages in one stack, and an editor dialog:

  LIBRARY   subjects (collapsible, remembered per subject in the Mac's UI
            state) -> sets with a checkbox, card / due counts
            and a thin seen-progress bar; study options (mode, card types,
            round size) and a Study button that says how many cards the round
            will hold; Import…, New subject, New set; the agent INBOX path.
            Every subject header and set row has a "⋯" menu, also on
            right-click: Archive takes it out of the list and the round (kept
            whole, under "Archived (N)" at the bottom, collapsed), Delete asks
            first. Double-click a subject's name to rename it.
  STUDY     one card at a time, drawn per type from `FlashcardStore.study()`'s
            queue entries. Self-graded types end on Again / Hard / Good / Easy
            with the next interval on each button; mc and order mark
            themselves. An Again comes back 4-7 cards later in the same round.
  SUMMARY   right on the first attempt, per set, and the misses — with
            "Practise the mistakes".
  EDITOR    `SetEditorDialog`: the set's cards, a form per type, saved through
            the same `cardformat.normalise` every other door uses, so a bad
            card is a sentence under the form rather than a crash.

The panel talks to `FlashcardStore` directly, as the other Mac panels talk to
`CalendarDB`; nothing here parses or schedules — `store.study`, `store.review`
and `fsrs` do. The store is injectable (`store=`) so tests use a scratch file;
without one, each `reload()` re-resolves the per-user path, so switching user
switches decks.

A set whose `dir` is rtl (Hebrew, Arabic) lays its cards out right-to-left.
"""

from __future__ import annotations

import collections
import datetime as _dt
import html
import io
import os
import random
import re
import unicodedata
import zipfile
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from assistant.calendar_ui import styles as _styles
from assistant.calendar_ui.feature_panel import FeaturePanel
from assistant.features.flashcards import cardformat, fsrs
from assistant.features.flashcards.cardformat import CardError
from assistant.features.flashcards.store import FlashcardError, FlashcardStore

TYPE_LABELS = {
    "basic": "Basic", "image": "Picture", "cloze": "Cloze", "mc": "Choice",
    "order": "Order", "typed": "Typed", "occlusion": "Labels",
}
MODES = (("smart", "Spaced review"), ("all", "All cards"), ("exam", "Multiple-choice exam"))
ROUND_SIZES = ((20, "20"), (50, "50"), (100, "100"), (0, "All"))
GRADES = ((1, "Again"), (2, "Hard"), (3, "Good"), (4, "Easy"))
GOOD = "#2fae5c"
CARD_FONTS = ["Times New Roman", "Georgia", "serif"]

_NIQQUD = re.compile("[֑-ׇ]")


# ---------------------------------------------------------------- helpers

def normalise_word(word: str) -> str:
    """A word as the typed-answer check compares it: niqqud and punctuation
    stripped, case folded — "התקוה," and "התקוה" are the same word."""
    word = _NIQQUD.sub("", word)
    word = "".join(ch for ch in word if not unicodedata.category(ch).startswith("P"))
    return word.casefold()


def missing_words(answer: str, typed: str) -> "list[tuple[str, bool]]":
    """The answer's tokens (whitespace kept) with True on each word the typed
    text did not contain — counted, so a word typed once covers one use."""
    have = collections.Counter(w for w in (normalise_word(t) for t in typed.split()) if w)
    out = []
    for tok in re.split(r"(\s+)", answer):
        if not tok or tok.isspace():
            out.append((tok, False))
            continue
        n = normalise_word(tok)
        if not n:
            out.append((tok, False))
        elif have[n] > 0:
            have[n] -= 1
            out.append((tok, False))
        else:
            out.append((tok, True))
    return out


def format_interval(days: float) -> str:
    if days < 1:
        return f"{max(1, round(days * 1440))} min"
    if days < 30:
        return f"{round(days)}d"
    if days < 365:
        return f"{days / 30:.1f}mo"
    return f"{days / 365:.1f}y"


def interval_hint(progress: "dict | None", grade: int, now: "_dt.datetime | None" = None) -> str:
    """What the grade button will do to this item — the store's own arithmetic."""
    if grade == 1:
        return f"{fsrs.RELEARN_MINUTES} min"
    now = now or _dt.datetime.now(_dt.timezone.utc)
    s0 = d0 = None
    elapsed = 0.0
    if progress and progress.get("stability") is not None:
        s0, d0 = progress["stability"], progress["difficulty"]
        try:
            last = _dt.datetime.fromisoformat(str(progress["last"]).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=_dt.timezone.utc)
            elapsed = max(0.0, (now - last).total_seconds() / 86400)
        except (KeyError, ValueError):
            pass
    s, _ = fsrs.next_state(s0, d0, elapsed, grade)
    return format_interval(fsrs.interval_days(s))


def question_answer(entry: dict) -> "tuple[str, str]":
    """One line each for the summary's list of misses."""
    card, item = entry["card"], entry["item"]
    t = card["type"]
    if t in ("basic", "image"):
        front = card.get("front") or "(picture)"
        return (card["back"], front) if item == "rev" else (front, card["back"])
    if t == "cloze":
        n = int(item[1:]) if item.startswith("c") else 0
        gaps = cardformat.CLOZE.findall(card["text"])
        return cloze_text(card["text"], n, revealed=False, rich=False), gaps[n] if n < len(gaps) else ""
    if t == "mc":
        return card["question"], card["answer"]
    if t == "order":
        return card["prompt"], " → ".join(card["steps"])
    if t == "typed":
        return card["front"], card["answer"]
    if t == "occlusion":
        labels = card["labels"]
        if item.startswith("l"):
            i = int(item[1:])
            return card.get("prompt") or "Hidden label", labels[i]["text"] if i < len(labels) else ""
        return card.get("prompt") or "Hidden labels", ", ".join(l["text"] for l in labels)
    return "", ""


def cloze_text(text: str, n: int, *, revealed: bool, rich: bool = True, accent: str = "") -> str:
    """The cloze with its n-th gap hidden (or filled in) and the rest plain."""
    out, last = [], 0
    for i, m in enumerate(cardformat.CLOZE.finditer(text)):
        plain = text[last:m.start()]
        out.append(html.escape(plain) if rich else plain)
        gap = m.group(1)
        if i == n:
            if not rich:
                out.append("…")
            elif revealed:
                out.append(f'<b style="color:{accent}">{html.escape(gap)}</b>')
            else:
                out.append(f'<span style="color:{accent}">[ … ]</span>')
        else:
            out.append(html.escape(gap) if rich else gap)
        last = m.end()
    tail = text[last:]
    out.append(html.escape(tail) if rich else tail)
    s = "".join(out)
    return s.replace("\n", "<br>") if rich else s


def _palette(dark: bool) -> dict:
    ramp = _styles.accent_tokens(_styles.get_accent())
    return {
        "bg": _styles.D_WHITE if dark else _styles.WHITE,
        "bg2": _styles.D_GRAY_BG if dark else _styles.GRAY_BG,
        "surface": _styles.D_GRAY_LIGHT if dark else _styles.GRAY_LIGHT,
        "border": _styles.D_GRAY_BORDER if dark else _styles.GRAY_BORDER,
        "mid": _styles.D_GRAY_MID if dark else _styles.GRAY_MID,
        "text": _styles.D_GRAY_DARK if dark else _styles.GRAY_DARK,
        "muted": _styles.D_GRAY_TEXT if dark else _styles.GRAY_TEXT,
        "accent": ramp["accent"],
        "on_accent": ramp["on_accent"],
        "soft": ramp["accent_soft_dark"] if dark else ramp["accent_soft_light"],
        "good": GOOD,
        "bad": _styles.DESTRUCTIVE_DARK if dark else _styles.DESTRUCTIVE,
        "mask": "#2a2b31" if dark else "#d9d7d0",
    }


def _rgba(hex_color: str, a: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})"


def _qss(p: dict) -> str:
    return f"""
QFrame#fc_face {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; }}
QFrame#fc_face QLabel {{ background: transparent; border: none; }}
QLabel#fc_muted {{ color: {p['muted']}; }}
QLabel#fc_title {{ font-size: 20px; font-weight: 600; }}
QLabel#fc_subject {{ font-size: 14px; font-weight: 600; }}
QLabel#fc_due {{ color: {p['accent']}; font-weight: 600; }}
QLabel#fc_error {{ color: {p['bad']}; }}
QLabel#fc_reveal {{ color: {p['accent']}; }}
QLabel#fc_path {{ font-family: {_styles.MONO_FONT}; color: {p['muted']}; }}
QLabel#fc_big {{ font-size: 40px; font-weight: 700; color: {p['accent']}; }}
QFrame#fc_rule {{ background: {p['border']}; border: none; max-height: 1px; min-height: 1px; }}
QProgressBar#fc_thin {{ border: none; background: {p['border']}; border-radius: 2px;
    max-height: 4px; min-height: 4px; }}
QProgressBar#fc_thin::chunk {{ background: {p['accent']}; border-radius: 2px; }}
QPushButton#fc_chip {{ padding: 3px 10px; border: 1px solid {p['border']}; border-radius: 4px;
    background: transparent; color: {p['muted']}; }}
QPushButton#fc_chip:hover {{ border-color: {p['mid']}; color: {p['text']}; }}
QPushButton#fc_chip:checked {{ background: {p['soft']}; color: {p['text']}; border-color: {p['accent']}; }}
QPushButton#fc_link {{ border: none; background: transparent; color: {p['muted']}; padding: 0 4px; }}
QPushButton#fc_link:hover {{ color: {p['accent']}; }}
QToolButton#fc_toggle {{ border: none; background: transparent; color: {p['muted']}; }}
QWidget#fc_setrow:hover {{ background: {p['bg2']}; }}
QFrame#fc_tile {{ background: {p['bg']}; border: 1px solid {p['border']}; border-radius: 6px; }}
QFrame#fc_tile:hover {{ border-color: {p['accent']}; }}
QFrame#fc_tile[state="right"] {{ border: 2px solid {p['good']}; background: {_rgba(p['good'], 0.14)}; }}
QFrame#fc_tile[state="wrong"] {{ border: 2px solid {p['bad']}; background: {_rgba(p['bad'], 0.14)}; }}
QFrame#fc_tile[state="placed"] {{ border: 1px solid {p['accent']}; background: {p['soft']}; }}
QFrame#fc_tile[state="off"] {{ border: 1px dashed {p['border']}; background: transparent; }}
QFrame#fc_tile[state="off"] QLabel {{ color: {p['mid']}; }}
QFrame#fc_tile QLabel {{ background: transparent; border: none; }}
QPlainTextEdit, QListWidget {{ background: {p['bg2']}; border: 1px solid {p['border']};
    border-radius: 4px; padding: 4px; }}
QPlainTextEdit:focus {{ border-color: {p['accent']}; }}
QLabel#fc_num {{ color: {p['muted']}; font-family: {_styles.MONO_FONT}; }}
"""


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def _clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


def _card_font(w: QWidget, px: int, bold: bool = False) -> None:
    """The card face's serif, set as a stylesheet: the app-wide sheet gives
    every QWidget a 13px UI font, and a sheet beats setFont()."""
    fams = ", ".join(f'"{f}"' if " " in f else f for f in CARD_FONTS)
    w.setStyleSheet(f"font-family: {fams}; font-size: {px}px;"
                    + (" font-weight: 600;" if bold else ""))


def _align(rtl: bool) -> Qt.AlignmentFlag:
    h = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
    return h | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter


def _label(text: str = "", name: str = "", *, wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _button(text: str, name: str = "", cb: "Callable | None" = None, *, focus: bool = False) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if cb is not None:
        b.clicked.connect(lambda _=False: cb())
    if not focus:
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def _ui_state():
    """Which subjects are folded shut — window chrome, per machine, so it
    lives in the same QSettings as the settings dialog's folds (redirected by
    MACALENDAR_UI_STATE), never in the flashcards store the phone syncs."""
    from assistant.calendar_ui.settings_dialog import _ui_state as state
    return state()


_COLLAPSED_KEY = "flashcards/collapsed_subjects"


def _load_collapsed() -> set:
    try:
        raw = _ui_state().value(_COLLAPSED_KEY, "", type=str) or ""
        return {int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()}
    except Exception:                               # noqa: BLE001
        return set()


def _save_collapsed(ids: set) -> None:
    try:
        st = _ui_state()
        st.setValue(_COLLAPSED_KEY, ",".join(str(i) for i in sorted(ids)))
        st.sync()
    except Exception:                               # noqa: BLE001
        pass


def _alive(widget) -> bool:
    """False once Qt has deleted the widget (the card moved on)."""
    try:
        from PyQt6 import sip
        return not sip.isdeleted(widget)
    except Exception:                               # noqa: BLE001
        return False


_ENGLISH_KEY = "flashcards/english_open"


def _english_open() -> bool:
    """Whether the question's English is unfolded — remembered per machine,
    so someone who always wants it opens it once."""
    try:
        return bool(_ui_state().value(_ENGLISH_KEY, False, type=bool))
    except Exception:                               # noqa: BLE001
        return False


def _save_english_open(on: bool) -> None:
    try:
        st = _ui_state()
        st.setValue(_ENGLISH_KEY, bool(on))
        st.sync()
    except Exception:                               # noqa: BLE001
        pass


def english_prompt(card: dict, item: str) -> "str | None":
    """The question in English (`en`, Gil 2026-10-12), or None. A cloze's
    English without gaps would give the answer away, so it waits."""
    en = card.get("en") or {}
    kind, rev = card["type"], item == "rev"
    if kind in ("basic", "image"):
        return en.get("back" if rev else "front")
    if kind == "cloze":
        t = en.get("text")
        if not t or not cardformat.CLOZE.search(t):
            return None
        return cloze_text(t, int(item[1:]) if item.startswith("c") else 0, revealed=False, rich=False)
    if kind == "mc":
        return en.get("question")
    if kind in ("order", "occlusion"):
        return en.get("prompt")
    if kind == "typed":
        return en.get("front")
    return None


def prompt_line(card: dict, item: str) -> str:
    """The question as plain text — what the copy button copies."""
    kind, rev = card["type"], item == "rev"
    if kind in ("basic", "image"):
        return (card.get("back") if rev else card.get("front")) or ""
    if kind == "cloze":
        return cloze_text(card["text"], int(item[1:]) if item.startswith("c") else 0,
                          revealed=False, rich=False)
    if kind == "mc":
        return card["question"] + "\n" + "\n".join(card["choices"])
    if kind == "order":
        return card["prompt"] + "\n" + "\n".join(card["steps"])
    return card.get("front") or card.get("prompt") or ""


def answer_line(card: dict, item: str) -> str:
    """The answer as plain text — what the answer's copy button copies."""
    kind, rev = card["type"], item == "rev"
    if kind == "basic":
        return card["front"] if rev else card["back"]
    if kind == "image":
        return "" if rev else card["back"]
    if kind == "cloze":
        return cardformat.CLOZE.sub(lambda m: m.group(1), card["text"])
    if kind in ("mc", "typed"):
        return card["answer"]
    if kind == "order":
        return "\n".join(card["steps"])
    if kind == "occlusion" and item.startswith("l"):
        i = int(item[1:])
        return card["labels"][i]["text"] if i < len(card["labels"]) else ""
    return ""


def english_answer(card: dict, item: str) -> "str | None":
    """The answer in English, shown straight under the answer."""
    en = card.get("en") or {}
    kind, rev = card["type"], item == "rev"
    if kind == "basic":
        return en.get("front" if rev else "back")
    if kind == "image":
        return None if rev else en.get("back")
    if kind == "cloze":
        t = en.get("text")
        if not t:
            return None
        return cardformat.CLOZE.sub(lambda m: m.group(1), t)
    if kind in ("mc", "typed"):
        return en.get("answer")
    if kind == "order":
        return " → ".join(en["steps"]) if en.get("steps") else None
    if kind == "occlusion" and item.startswith("l"):
        labels, i = en.get("labels") or [], int(item[1:])
        return labels[i] if i < len(labels) else None
    return None


def _rule() -> QFrame:
    f = QFrame()
    f.setObjectName("fc_rule")
    return f


# ---------------------------------------------------------------- widgets

class Tile(QFrame):
    """A clickable answer tile (mc choice, order step) whose text WRAPS — a
    QPushButton cannot, and Hebrew choices run to a line and a half."""

    clicked = pyqtSignal()

    def __init__(self, text: str, number: str = "", *, rtl: bool = False, px: int = 17, parent=None):
        super().__init__(parent)
        self.setObjectName("fc_tile")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text = text
        self._enabled = True
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(10)
        self.num = QLabel(number)
        self.num.setObjectName("fc_num")
        self.num.setVisible(bool(number))
        self.body = QLabel(text)
        self.body.setWordWrap(True)
        _card_font(self.body, px)
        self.body.setAlignment(_align(rtl))
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.num, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.body, 1)

    def set_number(self, s: str) -> None:
        self.num.setText(s)
        self.num.setVisible(bool(s))

    def set_state(self, state: str) -> None:
        self.setProperty("state", state)
        _repolish(self)

    def set_clickable(self, on: bool) -> None:
        self._enabled = on
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self._enabled and ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class PictureCanvas(QWidget):
    """A picture scaled to a width, with label boxes painted over it.

    Boxes are percent [x, y, w, h] of the picture, so they are mapped onto the
    widget's OWN rect — the widget is sized to the picture's aspect, which is
    what keeps a box on the printed label at any scale.

    mode:  plain (no boxes) · one (all masked, `target` in accent) ·
           all (click a box to reveal it) · edit (drag to draw a new box).
    """

    box_clicked = pyqtSignal(int)
    box_drawn = pyqtSignal(list)
    box_selected = pyqtSignal(int)

    def __init__(self, path: str = "", labels=(), mode: str = "plain", parent=None):
        super().__init__(parent)
        self.labels = [dict(l) for l in labels]
        self.mode = mode
        self.target = -1
        self.revealed: set = set()
        self.selected = -1
        self.colors = _palette(True)
        self._drag: "tuple[QPointF, QPointF] | None" = None
        self._scaled: Optional[QPixmap] = None
        self.set_picture(path)

    def set_picture(self, path: str) -> None:
        self.path = path
        self._pix = QPixmap(path) if path and os.path.exists(path) else QPixmap()
        self._scaled = None
        self.update()

    def has_picture(self) -> bool:
        return not self._pix.isNull()

    def fit(self, width: int, max_h: "int | None" = None, max_scale: float = 1.6) -> None:
        width = max(80, int(width))
        if self._pix.isNull():
            self.setFixedSize(width, 80)
            return
        pw, ph = self._pix.width(), self._pix.height()
        s = min(width / pw, max_scale)
        if max_h:
            s = min(s, max_h / ph)
        self.setFixedSize(max(1, int(pw * s)), max(1, int(ph * s)))

    def resizeEvent(self, ev):  # noqa: N802
        self._scaled = None
        super().resizeEvent(ev)

    def box_rect(self, i: int) -> QRectF:
        x, y, w, h = self.labels[i]["box"]
        W, H = self.width(), self.height()
        return QRectF(x / 100 * W, y / 100 * H, w / 100 * W, h / 100 * H)

    def box_at(self, pos) -> int:
        for i in range(len(self.labels) - 1, -1, -1):
            if self.box_rect(i).adjusted(-2, -2, 2, 2).contains(QPointF(pos)):
                return i
        return -1

    def paintEvent(self, ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.colors
        if self._pix.isNull():
            p.setPen(QColor(c["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       f"Picture missing: {os.path.basename(self.path) or '(none)'}")
            return
        if self._scaled is None or self._scaled.size() != self.size():
            self._scaled = self._pix.scaled(self.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(0, 0, self._scaled)
        if self.mode == "plain":
            return
        accent, mask = QColor(c["accent"]), QColor(c["mask"])
        for i in range(len(self.labels)):
            r = self.box_rect(i)
            if self.mode == "edit":
                fill = QColor(accent)
                fill.setAlpha(110 if i == self.selected else 60)
                p.fillRect(r, fill)
                p.setPen(QPen(accent, 2 if i == self.selected else 1))
                p.drawRect(r)
                continue
            if i in self.revealed:
                p.setPen(QPen(accent, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r.adjusted(-1, -1, 1, 1))
                continue
            is_target = self.mode == "one" and i == self.target
            p.fillRect(r, accent if is_target else mask)
            p.setPen(QPen(QColor(c["on_accent"]) if is_target else QColor(c["border"]), 1))
            p.drawRect(r)
            if is_target and r.height() >= 11:
                f = p.font()
                f.setPixelSize(int(min(r.height() - 2, 16)))
                f.setBold(True)
                p.setFont(f)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, "?")
        if self._drag is not None:
            p.setPen(QPen(accent, 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(self._drag[0], self._drag[1]).normalized())

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        if self.mode == "all":
            i = self.box_at(pos)
            if i >= 0 and i not in self.revealed:
                self.revealed.add(i)
                self.update()
                self.box_clicked.emit(i)
        elif self.mode == "edit":
            self._drag = (pos, pos)

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self.mode == "edit" and self._drag is not None:
            self._drag = (self._drag[0], ev.position())
            self.update()

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self.mode != "edit" or self._drag is None:
            return
        a, b = self._drag[0], ev.position()
        self._drag = None
        r = QRectF(a, b).normalized().intersected(QRectF(self.rect()))
        if r.width() < 5 or r.height() < 5:
            i = self.box_at(a)
            if i >= 0:
                self.selected = i
                self.box_selected.emit(i)
            self.update()
            return
        W, H = max(1, self.width()), max(1, self.height())
        box = [round(r.x() / W * 100, 2), round(r.y() / H * 100, 2),
               round(r.width() / W * 100, 2), round(r.height() / H * 100, 2)]
        self.update()
        self.box_drawn.emit(box)


class _SetRow(QWidget):
    """A library row: a click anywhere on it ticks its checkbox."""

    check: Optional[QCheckBox] = None

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if (self.check is not None and ev.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(ev.pos())):
            self.check.toggle()
        super().mouseReleaseEvent(ev)


class _SubjectName(QLabel):
    """A subject header's name: double-click renames it."""

    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(ev)


class _StudyPage(QWidget):
    """The study page takes the keyboard: Space and 1-8 go to the view."""

    def __init__(self, handler: Callable, parent=None):
        super().__init__(parent)
        self._handler = handler
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, ev):  # noqa: N802
        if not self._handler(ev):
            super().keyPressEvent(ev)


# ---------------------------------------------------------------- the panel

class FlashcardsView(FeaturePanel):
    feature_name = "flashcards"

    def __init__(self, db=None, config=None, dark: bool = True, *,
                 store: "FlashcardStore | None" = None, parent=None):
        super().__init__(parent)
        self._db = db
        self._fixed_store = store is not None
        self._store = store if store is not None else FlashcardStore()
        self._dark = dark
        self._library: list = []
        self._selected: set = set()
        self._collapsed: set = _load_collapsed()   # subject ids folded shut
        self._archived_open = False                # the Archived section
        self._archived_box: Optional[QWidget] = None
        self._set_boxes: dict = {}
        self._set_dir: dict = {}
        self._rng = random.Random()
        # the round
        self._queue: list = []
        self._idx = 0
        self._round_mode = "smart"
        self._first: "dict[tuple, dict]" = {}
        self._cur: dict = {}
        self._canvas: Optional[PictureCanvas] = None
        self._canvas_max_h: "int | None" = None
        self._build()
        self.apply_theme(dark)
        self.reload()

    # ------------------------------------------------------------ build

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()
        outer.addWidget(self._pages)
        self._lib_page = self._build_library()
        self._study_page = self._build_study()
        self._sum_page = self._build_summary()
        for w in (self._lib_page, self._study_page, self._sum_page):
            self._pages.addWidget(w)

    def _build_library(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 16, 20, 12)
        v.setSpacing(10)

        top = QHBoxLayout()
        title = _label("Flashcards", "fc_title", wrap=False)
        top.addWidget(title)
        top.addStretch(1)
        self._import_btn = _button("Import…", "", self._import)
        self._new_subject_btn = _button("New subject", "", self._new_subject)
        self._new_set_btn = _button("New set", "", self._new_set)
        for b in (self._import_btn, self._new_subject_btn, self._new_set_btn):
            top.addWidget(b)
        v.addLayout(top)

        sel = QHBoxLayout()
        sel.setSpacing(4)
        sel.addWidget(_label("Select", "fc_muted", wrap=False))
        self._all_btn = _button("all", "fc_link", lambda: self._select_all(True))
        self._none_btn = _button("none", "fc_link", lambda: self._select_all(False))
        sel.addWidget(self._all_btn)
        sel.addWidget(self._none_btn)
        sel.addSpacing(12)
        self._status = _label("", "fc_muted", wrap=False)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sel.addWidget(self._status, 1)
        v.addLayout(sel)

        self._lib_scroll = QScrollArea()
        self._lib_scroll.setWidgetResizable(True)
        self._lib_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._lib_body = QWidget()
        self._lib_layout = QVBoxLayout(self._lib_body)
        self._lib_layout.setContentsMargins(0, 0, 6, 0)
        self._lib_layout.setSpacing(2)
        self._lib_scroll.setWidget(self._lib_body)
        v.addWidget(self._lib_scroll, 1)

        v.addWidget(_rule())
        # study options
        opts = QVBoxLayout()
        opts.setSpacing(6)

        def chip_row(caption: str, items, exclusive: bool):
            row = QHBoxLayout()
            row.setSpacing(4)
            cap = _label(caption, "fc_muted", wrap=False)
            cap.setFixedWidth(64)
            row.addWidget(cap)
            group = QButtonGroup(self)
            group.setExclusive(exclusive)
            btns = {}
            for key, text in items:
                b = _button(text, "fc_chip")
                b.setCheckable(True)
                group.addButton(b)
                btns[key] = b
                row.addWidget(b)
            row.addStretch(1)
            return row, group, btns

        mrow, self._mode_group, self._mode_btns = chip_row("Mode", MODES, True)
        self._mode_btns["smart"].setChecked(True)
        trow, self._type_group, self._type_btns = chip_row(
            "Cards", list(TYPE_LABELS.items()), False)
        for b in self._type_btns.values():
            b.setChecked(True)
        rrow, self._size_group, self._size_btns = chip_row("Round", ROUND_SIZES, True)
        self._size_btns[20].setChecked(True)
        self._type_row = QWidget()
        self._type_row.setLayout(trow)
        trow.setContentsMargins(0, 0, 0, 0)
        for g in (self._mode_group, self._type_group, self._size_group):
            g.buttonClicked.connect(lambda _b: self._options_changed())

        bottom = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addLayout(mrow)
        left.addWidget(self._type_row)
        left.addLayout(rrow)
        bottom.addLayout(left, 1)
        self._study_btn = _button("Study", "primary", self._start_study)
        self._study_btn.setMinimumSize(180, 44)
        bottom.addWidget(self._study_btn, 0, Qt.AlignmentFlag.AlignBottom)
        opts.addLayout(bottom)
        v.addLayout(opts)

        v.addWidget(_rule())
        inbox = QHBoxLayout()
        inbox.setSpacing(8)
        inbox.addWidget(_label("Agent inbox", "fc_muted", wrap=False))
        self._inbox_lbl = _label("", "fc_path", wrap=False)
        self._inbox_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._inbox_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        inbox.addWidget(self._inbox_lbl, 1)
        self._copy_btn = _button("Copy path", "", self._copy_inbox)
        inbox.addWidget(self._copy_btn)
        v.addLayout(inbox)
        v.addWidget(_label("An agent can drop a set file (.yaml, .json or .zip — the format is "
                           "assistant/features/flashcards/FORMAT.md) into this folder; it is "
                           "imported the next time this tab opens.", "fc_muted"))
        return page

    def _build_study(self) -> QWidget:
        page = _StudyPage(self._on_key)
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 14, 20, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        self._set_lbl = _label("", "fc_muted", wrap=False)
        top.addWidget(self._set_lbl, 1)
        self._left_lbl = _label("", "fc_muted", wrap=False)
        top.addWidget(self._left_lbl)
        self._end_btn = _button("End", "", self._end_round)
        top.addWidget(self._end_btn)
        v.addLayout(top)
        self._round_bar = QProgressBar()
        self._round_bar.setObjectName("fc_thin")
        self._round_bar.setTextVisible(False)
        v.addWidget(self._round_bar)

        self._face_scroll = QScrollArea()
        self._face_scroll.setWidgetResizable(True)
        self._face_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._face_scroll.viewport().installEventFilter(self)
        # A picture card scrolls to its target box once the layout has a
        # range to scroll in — a timer fired before layout finds max == 0.
        self._face_scroll.verticalScrollBar().rangeChanged.connect(
            lambda _lo, _hi: self._scroll_to_target())
        self._face = QFrame()
        self._face.setObjectName("fc_face")
        self._face_layout = QVBoxLayout(self._face)
        self._face_layout.setContentsMargins(28, 24, 28, 24)
        self._face_layout.setSpacing(14)
        self._face_scroll.setWidget(self._face)
        v.addWidget(self._face_scroll, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._undo_btn = _button("Undo", "", self._order_undo)
        bar.addWidget(self._undo_btn)
        self._reveal_all_btn = _button("Reveal all", "", self._occ_reveal_all)
        bar.addWidget(self._reveal_all_btn)
        bar.addStretch(1)
        self._action_btn = _button("Show answer", "primary", self._action)
        self._action_btn.setMinimumSize(200, 40)
        bar.addWidget(self._action_btn)
        self._grade_box = QWidget()
        g = QHBoxLayout(self._grade_box)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(8)
        self._grade_btns: dict = {}
        for grade, text in GRADES:
            b = _button(text, {1: "destructive", 3: "primary"}.get(grade, ""),
                        lambda gr=grade: self._grade(gr))
            b.setMinimumSize(96, 46)
            self._grade_btns[grade] = b
            g.addWidget(b)
        bar.addWidget(self._grade_box)
        bar.addStretch(1)
        v.addLayout(bar)
        return page

    def _build_summary(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(10)
        self._sum_pct = _label("", "fc_big", wrap=False)
        v.addWidget(self._sum_pct)
        self._sum_sub = _label("", "fc_muted")
        v.addWidget(self._sum_sub)
        self._sum_table = QTableWidget(0, 3)
        self._sum_table.setHorizontalHeaderLabels(["Set", "Right", "Total"])
        self._sum_table.verticalHeader().setVisible(False)
        self._sum_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._sum_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self._sum_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self._sum_table)
        v.addWidget(_label("Missed", "fc_subject", wrap=False))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self._miss_layout = QVBoxLayout(body)
        self._miss_layout.setContentsMargins(0, 0, 6, 0)
        self._miss_layout.setSpacing(8)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._practise_btn = _button("Practise the mistakes", "primary", self._practise)
        self._back_btn = _button("Back to sets", "", self._back_to_library)
        row.addWidget(self._back_btn)
        row.addWidget(self._practise_btn)
        v.addLayout(row)
        return page

    # ------------------------------------------------------------ contract

    def reload(self) -> None:
        if not self._fixed_store:
            try:
                self._store = FlashcardStore()      # the signed-in user's decks
            except Exception as e:                  # noqa: BLE001
                self._status.setText(f"Could not open the flashcards store: {e}")
                return
        status = []
        try:
            for r in self._store.import_inbox():
                if r.get("error"):
                    status.append(f"Inbox: {r['file']} failed — {r['error']}")
                else:
                    status.append(f"Inbox: {r['set']} +{r['added']} cards")
        except Exception as e:                      # noqa: BLE001
            status.append(f"Inbox could not be read: {e}")
        if status:
            self._status.setText("  ·  ".join(status))
            self._status.setToolTip("\n".join(status))
        self._inbox_lbl.setText(self._store.inbox_dir)
        self._inbox_lbl.setToolTip(self._store.inbox_dir)
        self._rebuild_library()

    def apply_theme(self, dark: bool) -> None:
        self._dark = dark
        self._pal = _palette(dark)
        self.setStyleSheet(_qss(self._pal))
        if self._canvas is not None:
            self._canvas.colors = self._pal
            self._canvas.update()

    def apply_ui_config(self, ui) -> None:
        """Nothing size-related is configurable here yet; the card face sizes
        itself from the card."""

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        if self._pages.currentWidget() is self._lib_page:
            QTimer.singleShot(0, self.reload)

    # ------------------------------------------------------------ library

    def _rebuild_library(self) -> None:
        scroll = self._lib_scroll.verticalScrollBar().value()
        try:
            self._library = self._store.library()
        except Exception as e:                      # noqa: BLE001
            self._status.setText(f"Could not read the library: {e}")
            self._library = []
        _clear(self._lib_layout)
        self._set_boxes = {}
        self._set_dir = {}
        self._archived_box = None
        # The main list: live subjects with their live sets. An archived
        # subject takes ALL its sets with it; an archived set leaves its
        # (live) subject's list and counts. Neither can be ticked into a round.
        active, arch_subjects, arch_sets = [], [], []
        for sub in self._library:
            if sub.get("archived"):
                arch_subjects.append(sub)
                continue
            live = [s for s in sub["sets"] if not s.get("archived")]
            arch_sets += [dict(s, subject=sub["name"]) for s in sub["sets"] if s.get("archived")]
            active.append(dict(sub, sets=live))
        alive = {s["id"] for sub in active for s in sub["sets"]}
        self._selected &= alive
        if not active:
            self._lib_layout.addWidget(_label(
                "No flashcards yet. Import a set file, make a set by hand, or have an agent "
                "drop one into the inbox below." if not self._library else
                "Everything is archived — unarchive a set or subject below to study it.",
                "fc_muted"))
        for sub in active:
            self._lib_layout.addWidget(self._subject_block(sub))
        if arch_subjects or arch_sets:
            self._archived_box = self._archived_section(arch_subjects, arch_sets)
            self._lib_layout.addWidget(self._archived_box)
        self._lib_layout.addStretch(1)
        QTimer.singleShot(0, lambda: self._lib_scroll.verticalScrollBar().setValue(scroll))
        self._options_changed()

    def _subject_block(self, sub: dict) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 8, 0, 4)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(6)
        collapsed = sub["id"] in self._collapsed
        tog = QToolButton()
        tog.setObjectName("fc_toggle")
        tog.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow)
        tog.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tog.setToolTip("Collapse / expand")
        head.addWidget(tog)
        name = _SubjectName(sub["name"])
        name.setObjectName("fc_subject")
        name.setToolTip("Double-click to rename · right-click for more")
        name.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        name.customContextMenuRequested.connect(
            lambda pos, s=sub, w=name: self._subject_menu(s, w.mapToGlobal(pos)))
        name.double_clicked.connect(lambda s=sub: self._rename_subject(s))
        head.addWidget(name)
        n_cards = sum(s["cards"] for s in sub["sets"])
        n_due = sum(s["due"] for s in sub["sets"])
        n_sets = len(sub["sets"])
        info = (f"{n_sets} set{'' if n_sets == 1 else 's'} · {n_cards} cards"
                + (f" · {n_due} due" if n_due else ""))
        head.addWidget(_label(info, "fc_muted", wrap=False))
        head.addStretch(1)
        ids = [s["id"] for s in sub["sets"]]
        head.addWidget(_button("all", "fc_link", lambda i=ids: self._select_ids(i, True)))
        head.addWidget(_button("none", "fc_link", lambda i=ids: self._select_ids(i, False)))
        more = _button("⋯", "fc_link")
        more.setToolTip("Subject options")
        more.clicked.connect(lambda _=False, s=sub, b=more: self._subject_menu(
            s, b.mapToGlobal(b.rect().bottomLeft())))
        head.addWidget(more)
        head_w = QWidget()
        head_w.setLayout(head)
        head.setContentsMargins(0, 0, 0, 0)
        head_w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        head_w.customContextMenuRequested.connect(
            lambda pos, s=sub, w=head_w: self._subject_menu(s, w.mapToGlobal(pos)))
        v.addWidget(head_w)
        rows = QWidget()
        rv = QVBoxLayout(rows)
        rv.setContentsMargins(22, 2, 0, 0)
        rv.setSpacing(0)
        if not sub["sets"]:
            rv.addWidget(_label("No sets yet — New set adds one.", "fc_muted"))
        for s in sub["sets"]:
            rv.addWidget(self._set_row(s))
        rows.setVisible(not collapsed)
        v.addWidget(rows)
        box.toggle_btn = tog
        box.rows = rows
        box.name_label = name
        box.more_btn = more

        def toggle():
            hide = sub["id"] not in self._collapsed
            rows.setVisible(not hide)
            tog.setArrowType(Qt.ArrowType.RightArrow if hide else Qt.ArrowType.DownArrow)
            (self._collapsed.add if hide else self._collapsed.discard)(sub["id"])
            _save_collapsed(self._collapsed)
        tog.clicked.connect(lambda _=False: toggle())
        return box

    def _archived_section(self, subjects: list, sets: list) -> QWidget:
        """'Archived (N)' at the bottom, collapsed by default: what was put
        away, whole, with Unarchive and Delete on each row."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 16, 0, 4)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(6)
        tog = QToolButton()
        tog.setObjectName("fc_toggle")
        tog.setArrowType(Qt.ArrowType.DownArrow if self._archived_open else Qt.ArrowType.RightArrow)
        tog.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head.addWidget(tog)
        n = len(subjects) + len(sets)
        title = _label(f"Archived ({n})", "fc_muted", wrap=False)
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)
        rows = QWidget()
        rv = QVBoxLayout(rows)
        rv.setContentsMargins(22, 2, 0, 0)
        rv.setSpacing(0)
        box.rows = {}
        for sub in subjects:
            n_sets = len(sub["sets"])
            n_cards = sum(s["cards"] for s in sub["sets"])
            r = self._archived_row(
                sub["name"], f"subject · {n_sets} set{'' if n_sets == 1 else 's'} · {n_cards} cards",
                lambda where, s=sub: self._subject_menu(s, where))
            box.rows[("subject", sub["id"])] = r
            rv.addWidget(r)
        for s in sets:
            r = self._archived_row(s["name"], f"in {s['subject']} · {s['cards']} cards",
                                   lambda where, st=s: self._set_menu(st, where))
            box.rows[("set", s["id"])] = r
            rv.addWidget(r)
        rows.setVisible(self._archived_open)
        v.addWidget(rows)
        box.toggle_btn = tog
        box.body = rows
        box.title = title

        def toggle():
            self._archived_open = not self._archived_open
            rows.setVisible(self._archived_open)
            tog.setArrowType(Qt.ArrowType.DownArrow if self._archived_open
                             else Qt.ArrowType.RightArrow)
        tog.clicked.connect(lambda _=False: toggle())
        return box

    def _archived_row(self, name: str, info: str, menu: Callable) -> QWidget:
        row = QWidget()
        row.setObjectName("fc_setrow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(12)
        h.addWidget(_label(name, "", wrap=False))
        h.addWidget(_label(info, "fc_muted", wrap=False))
        h.addStretch(1)
        more = _button("⋯", "fc_link")
        more.setToolTip("Unarchive or delete")
        more.clicked.connect(lambda _=False, b=more: menu(b.mapToGlobal(b.rect().bottomLeft())))
        h.addWidget(more)
        row.more_btn = more
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(lambda pos, w=row: menu(w.mapToGlobal(pos)))
        return row

    def _set_row(self, s: dict) -> QWidget:
        row = _SetRow()
        row.setObjectName("fc_setrow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(12)
        cb = QCheckBox(s["name"])
        cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cb.setChecked(s["id"] in self._selected)
        cb.toggled.connect(lambda on, sid=s["id"]: self._toggle_set(sid, on))
        self._set_boxes[s["id"]] = cb
        self._set_dir[s["id"]] = s.get("dir", "ltr")
        row.check = cb
        h.addWidget(cb)
        h.addStretch(1)
        due = _label(f"{s['due']} due" if s["due"] else "", "fc_due", wrap=False)
        due.setMinimumWidth(56)
        due.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(due)
        cnt = _label(f"{s['cards']} cards", "fc_muted", wrap=False)
        cnt.setMinimumWidth(70)
        cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(cnt)
        bar = QProgressBar()
        bar.setObjectName("fc_thin")
        bar.setTextVisible(False)
        bar.setFixedWidth(110)
        bar.setRange(0, max(1, s["items"]))
        bar.setValue(s["seen"])
        bar.setToolTip(f"{s['seen']} of {s['items']} items seen")
        h.addWidget(bar)
        more = _button("⋯", "fc_link")
        more.clicked.connect(lambda _=False, st=s, b=more: self._set_menu(
            st, b.mapToGlobal(b.rect().bottomLeft())))
        h.addWidget(more)
        more.setToolTip("Set options")
        row.more_btn = more
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, st=s, w=row: self._set_menu(st, w.mapToGlobal(pos)))
        return row

    def _toggle_set(self, sid: int, on: bool) -> None:
        (self._selected.add if on else self._selected.discard)(sid)
        self._options_changed()

    def _select_ids(self, ids, on: bool) -> None:
        for sid in ids:
            cb = self._set_boxes.get(sid)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(on)
                cb.blockSignals(False)
            (self._selected.add if on else self._selected.discard)(sid)
        self._options_changed()

    def _select_all(self, on: bool) -> None:
        self._select_ids(list(self._set_boxes), on)

    # options -> the Study button

    def _mode(self) -> str:
        return next((k for k, b in self._mode_btns.items() if b.isChecked()), "smart")

    def _types(self) -> "list[str]":
        return [k for k, b in self._type_btns.items() if b.isChecked()]

    def _limit(self) -> int:
        return next((k for k, b in self._size_btns.items() if b.isChecked()), 20)

    def _options_changed(self) -> None:
        mode = self._mode()
        self._type_row.setVisible(mode != "exam")
        n, why = self._round_size()
        if n:
            self._study_btn.setText(f"Study {n} card{'s' if n != 1 else ''}")
        else:
            self._study_btn.setText(why)
        self._study_btn.setEnabled(bool(n))

    def _round_size(self) -> "tuple[int, str]":
        ids = sorted(self._selected)
        if not ids:
            return 0, "Select sets to study"
        mode, types = self._mode(), self._types()
        if mode != "exam" and not types:
            return 0, "Pick a card type"
        try:
            n = len(self._store.study(ids, mode=mode, types=types if mode != "exam" else None, limit=0))
        except Exception:                           # noqa: BLE001
            return 0, "Nothing to study"
        if not n:
            return 0, {"smart": "Nothing due", "exam": "No multiple-choice cards"}.get(mode, "No cards")
        lim = self._limit()
        return (min(n, lim) if lim else n), ""

    # menus

    def _set_menu(self, s: dict, where) -> None:
        m = QMenu(self)
        if s.get("archived"):
            m.addAction("Unarchive", lambda: self._archive("set", s, False))
            m.addSeparator()
            m.addAction("Delete…", lambda: self._delete_set(s))
            m.exec(where)
            return
        m.addAction("Edit cards…", lambda: self._edit_set(s["id"]))
        m.addAction("Rename…", lambda: self._rename_set(s))
        m.addAction("Export…", lambda: self._export_set(s))
        m.addSeparator()
        m.addAction("Reset progress…", lambda: self._reset_set(s))
        m.addAction("Archive", lambda: self._archive("set", s, True))
        m.addAction("Delete…", lambda: self._delete_set(s))
        m.exec(where)

    def _subject_menu(self, sub: dict, where) -> None:
        m = QMenu(self)
        if sub.get("archived"):
            m.addAction("Unarchive subject", lambda: self._archive("subject", sub, False))
            m.addSeparator()
            m.addAction("Delete subject…", lambda: self._delete_subject(sub))
            m.exec(where)
            return
        m.addAction("New set here…", lambda: self._new_set(sub["name"]))
        m.addAction("Rename subject…", lambda: self._rename_subject(sub))
        m.addSeparator()
        m.addAction("Archive subject", lambda: self._archive("subject", sub, True))
        m.addAction("Delete subject…", lambda: self._delete_subject(sub))
        m.exec(where)

    def _archive(self, kind: str, obj: dict, archived: bool) -> None:
        try:
            self._store.set_archived(kind, obj["id"], archived)
        except Exception as e:                      # noqa: BLE001
            self._inform("Archive", str(e), error=True)
        else:
            verb = "Archived" if archived else "Unarchived"
            self._status.setText(f"{verb} {obj['name']}")
        self._rebuild_library()

    # dialogs (methods so tests can answer them)

    def _ask_text(self, title: str, label: str, text: str = "") -> "str | None":
        val, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, text)
        return val.strip() if ok and val.strip() else None

    def _confirm(self, title: str, text: str, yes: str = "Delete") -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        ok = box.addButton(yes, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is ok

    def _inform(self, title: str, text: str, *, error: bool = False) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if error else QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.exec()

    def _pick_import_files(self) -> "list[str]":
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import flashcards", os.path.expanduser("~"),
            "Flashcard sets (*.yaml *.yml *.json *.zip)")
        return paths

    def _ask_import_mode(self, filename: str, existing: "list[str]") -> "str | None":
        box = QMessageBox(self)
        box.setWindowTitle("Set already exists")
        names = ", ".join(existing[:4]) + ("…" if len(existing) > 4 else "")
        box.setText(f"{filename} updates a set you already have ({names}).\n\n"
                    "Replace makes the set exactly the file (cards no longer in it are removed). "
                    "Add only adds the cards it doesn't have. Progress on unchanged cards is "
                    "kept either way.")
        rep = box.addButton("Replace", QMessageBox.ButtonRole.AcceptRole)
        app = box.addButton("Add new cards only", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return {id(rep): "replace", id(app): "append"}.get(id(box.clickedButton()))

    # actions

    def _existing_in(self, path: str) -> "list[str]":
        """Names of sets in this file the library already holds (subject + set_id)."""
        from assistant.features.flashcards.store import _load, _slug
        docs = []
        try:
            with open(path, "rb") as f:
                data = f.read()
            if path.lower().endswith(".zip"):
                zf = zipfile.ZipFile(io.BytesIO(data))
                for n in zf.namelist():
                    if n.lower().endswith((".yaml", ".yml", ".json")) and "__MACOSX" not in n:
                        docs.append(_load(n, zf.read(n)))
            else:
                docs.append(_load(path, data))
        except Exception:                           # noqa: BLE001 — the import will say why
            return []
        have = {(sub["name"], s["slug"]) for sub in self._library for s in sub["sets"]}
        out = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            subject = str(d.get("subject") or "").strip()
            for s in (d.get("sets") if isinstance(d.get("sets"), list) else [d]):
                if not isinstance(s, dict):
                    continue
                name = str(s.get("set") or "").strip()
                if (subject, _slug(str(s.get("set_id") or name))) in have:
                    out.append(name)
        return out

    def _import(self) -> None:
        paths = self._pick_import_files()
        if not paths:
            return
        lines, errors = [], []
        for path in paths:
            fname = os.path.basename(path)
            mode = "replace"
            existing = self._existing_in(path)
            if existing:
                mode = self._ask_import_mode(fname, existing)
                if mode is None:
                    continue
            try:
                for r in self._store.import_path(path, mode=mode):
                    lines.append(f"{r['set']}: {r['added']} added, {r['kept']} kept, "
                                 f"{r['removed']} removed")
            except Exception as e:                  # noqa: BLE001
                errors.append(f"{fname}: {e}")
        self._rebuild_library()
        if lines:
            self._status.setText(f"Imported {len(lines)} set{'s' if len(lines) != 1 else ''}")
        if errors:
            self._inform("Import failed",
                         "\n\n".join(errors) + ("\n\nImported:\n" + "\n".join(lines) if lines else ""),
                         error=True)
        elif lines:
            self._inform("Imported", "\n".join(lines))

    def _new_subject(self) -> None:
        name = self._ask_text("New subject", "Subject name:")
        if not name:
            return
        try:
            self._store.subject_id(name)
        except Exception as e:                      # noqa: BLE001
            self._inform("New subject", str(e), error=True)
        self._rebuild_library()

    def _new_set(self, subject: str = "") -> None:
        dlg = NewSetDialog([s["name"] for s in self._library if not s.get("archived")], subject, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        subj, name, direction = dlg.values()
        try:
            sid = self._store.create_set(subj, name, dir=direction)
        except Exception as e:                      # noqa: BLE001
            self._inform("New set", str(e), error=True)
            return
        self._rebuild_library()
        self._edit_set(sid)

    def _edit_set(self, set_id: int) -> None:
        dlg = SetEditorDialog(self._store, set_id, self, dark=self._dark)
        dlg.exec()
        self._rebuild_library()

    def _rename_set(self, s: dict) -> None:
        name = self._ask_text("Rename set", "Set name:", s["name"])
        if not name:
            return
        try:
            self._store.update_set(s["id"], name=name)
        except Exception as e:                      # noqa: BLE001
            self._inform("Rename", str(e), error=True)
        self._rebuild_library()

    def _rename_subject(self, sub: dict) -> None:
        name = self._ask_text("Rename subject", "Subject name:", sub["name"])
        if not name or name == sub["name"]:
            return
        try:
            self._store.rename_subject(sub["id"], name)
        except Exception as e:                      # noqa: BLE001
            self._inform("Rename subject", f"Couldn't rename “{sub['name']}”: {e}", error=True)
        self._rebuild_library()

    def _export_set(self, s: dict) -> None:
        import yaml
        try:
            doc = self._store.export_doc(s["id"])
        except Exception as e:                      # noqa: BLE001
            self._inform("Export", str(e), error=True)
            return
        pics = sorted({p for c in doc["cards"] for p in cardformat.images(c)})
        default = os.path.join(os.path.expanduser("~"), s["slug"] + (".zip" if pics else ".yaml"))
        path, _ = QFileDialog.getSaveFileName(self, "Export set", default,
                                              "Set file (*.yaml);;Set with pictures (*.zip)")
        if not path:
            return
        text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
        try:
            if path.lower().endswith(".zip"):
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(s["slug"] + ".yaml", text)
                    for rel in pics:
                        src = self._store.media_path(s["id"], rel)
                        if os.path.exists(src):
                            zf.write(src, rel)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
        except OSError as e:
            self._inform("Export", str(e), error=True)
            return
        self._status.setText(f"Exported {s['name']} to {path}")

    def _reset_set(self, s: dict) -> None:
        if self._confirm("Reset progress", f"Forget everything you've answered in “{s['name']}”? "
                         "Every card becomes new again.", "Reset"):
            self._store.reset_progress(s["id"])
            self._rebuild_library()

    def _delete_set(self, s: dict) -> None:
        if self._confirm("Delete set", f"Delete “{s['name']}”, its {s['cards']} cards, their "
                         "pictures and your progress on them? This cannot be undone."):
            self._store.delete_set(s["id"])
            self._selected.discard(s["id"])
            self._rebuild_library()

    def _delete_subject(self, sub: dict) -> None:
        # every set, archived ones included — the block's own list hides those
        full = next((x for x in self._library if x["id"] == sub["id"]), sub)
        n = len(full["sets"])
        if self._confirm("Delete subject", f"Delete “{sub['name']}” and all {n} of "
                         "its sets? This cannot be undone."):
            self._store.delete_subject(sub["id"])
            self._rebuild_library()

    def _copy_inbox(self) -> None:
        os.makedirs(self._store.inbox_dir, exist_ok=True)
        QApplication.clipboard().setText(self._store.inbox_dir)
        self._status.setText("Inbox path copied")

    # ------------------------------------------------------------ the round

    def _start_study(self) -> None:
        ids = sorted(self._selected)
        if not ids:
            return
        mode = self._mode()
        try:
            queue = self._store.study(ids, mode=mode, types=self._types() if mode != "exam" else None,
                                      limit=self._limit())
        except Exception as e:                      # noqa: BLE001
            self._status.setText(str(e))
            return
        if not queue:
            self._status.setText("Nothing to study with these options.")
            return
        self._begin(queue, mode)

    def _begin(self, queue: list, mode: str) -> None:
        self._queue = [dict(e) for e in queue]
        self._idx = 0
        self._round_mode = mode
        self._first = {}
        self._pages.setCurrentWidget(self._study_page)
        self._show_entry()

    def _rtl(self) -> bool:
        return self._cur.get("entry", {}).get("dir") == "rtl"

    def _show_entry(self) -> None:
        if self._idx >= len(self._queue):
            self._show_summary()
            return
        e = self._queue[self._idx]
        self._cur = {"entry": e, "answered": False}
        self._canvas = None
        _clear(self._face_layout)
        rtl = e.get("dir") == "rtl"
        self._face.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
        self._set_lbl.setText(e.get("set", "") + (" · exam" if self._round_mode == "exam" else ""))
        left = len(self._queue) - self._idx
        self._left_lbl.setText(f"{left} left")
        self._round_bar.setRange(0, max(1, len(self._queue)))
        self._round_bar.setValue(self._idx)
        self._grade_box.hide()
        self._undo_btn.hide()
        self._reveal_all_btn.hide()
        self._action_btn.show()
        self._action_btn.setEnabled(True)
        getattr(self, f"_render_{e['card']['type']}")(e)
        self._face_layout.addStretch(1)
        self._face_scroll.verticalScrollBar().setValue(0)
        if e["card"]["type"] != "typed":
            self._study_page.setFocus()

    # bits of a face

    def _text(self, text: str, px: int = 22, *, bold: bool = False, name: str = "",
              rich: bool = False) -> QLabel:
        lab = _label("", name)
        lab.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
        lab.setText(text)
        if name == "fc_muted":                      # captions stay in the UI font
            lab.setStyleSheet(f"font-size: {px}px;")
        else:
            _card_font(lab, px, bold)
        lab.setAlignment(_align(self._rtl()))
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._face_layout.addWidget(lab)
        return lab

    def _english(self, text: str, px: int = 16) -> QLabel:
        """A line of English: left to right whatever the card's direction."""
        lab = self._text(text, px, name="fc_muted")
        lab.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        return lab

    def _copy_button(self, text: str, name: str) -> QToolButton:
        """Copies a card's own words (Gil, 2026-10-12: "a copy option … at the
        bottom right"), and says so for a moment."""
        b = QToolButton()
        b.setObjectName(name)
        b.setText("Copy")
        b.setToolTip("Copy the text")
        b.setAutoRaise(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setEnabled(bool(text))

        def copy():
            QApplication.clipboard().setText(text)
            b.setText("Copied")
            QTimer.singleShot(1200, lambda: _alive(b) and b.setText("Copy"))
        b.clicked.connect(lambda _=False: copy())
        return b

    def _english_prompt(self) -> None:
        """Under the question: an "English" toggle on the left when the card
        has English (its text folded under it), and Copy on the right."""
        e = self._cur["entry"]
        text = english_prompt(e["card"], e["item"])
        row = QHBoxLayout()
        row.setDirection(QHBoxLayout.Direction.LeftToRight)
        if text:
            self._english_toggle(row, text)
        row.addStretch(1)
        row.addWidget(self._copy_button(prompt_line(e["card"], e["item"]), "fc_copy_prompt"))
        self._face_layout.insertLayout(self._face_layout.count() - (1 if text else 0), row)

    def _english_toggle(self, row: QHBoxLayout, text: str) -> None:
        btn = QToolButton()
        btn.setObjectName("fc_english_toggle")
        btn.setCheckable(True)
        btn.setChecked(_english_open())
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        btn.setAutoRaise(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(btn)
        lab = self._english(text, 17)

        def show(on: bool) -> None:
            btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
            btn.setText("English")
            lab.setVisible(on)
        btn.toggled.connect(lambda on: (show(on), _save_english_open(on)))
        show(btn.isChecked())
        self._cur["english_prompt"] = lab

    def _english_answer(self) -> None:
        """Under the answer: its English, and Copy at the bottom right."""
        e = self._cur["entry"]
        text = english_answer(e["card"], e["item"])
        if text:
            self._cur["english_answer"] = self._english(text, 18)
        row = QHBoxLayout()
        row.setDirection(QHBoxLayout.Direction.LeftToRight)
        row.addStretch(1)
        row.addWidget(self._copy_button(answer_line(e["card"], e["item"]), "fc_copy_answer"))
        self._face_layout.addLayout(row)

    def _set_action(self, text: str, cb: Callable, enabled: bool = True) -> None:
        self._cur["action"] = cb
        self._action_btn.setText(text)
        self._action_btn.setEnabled(enabled)
        self._action_btn.show()
        self._grade_box.hide()

    def _action(self) -> None:
        cb = self._cur.get("action")
        if cb is not None and self._action_btn.isEnabled():
            cb()

    def _show_grades(self) -> None:
        self._cur["answered"] = True
        self._action_btn.hide()
        prog = self._cur["entry"].get("progress")
        for g, text in GRADES:
            self._grade_btns[g].setText(f"{text}\n{interval_hint(prog, g)}")
        self._grade_box.show()
        self._study_page.setFocus()

    def _show_extra(self) -> None:
        card = self._cur["entry"]["card"]
        bits = []
        if card.get("explain"):
            bits.append(card["explain"])
        if card.get("note"):
            bits.append(card["note"])
        if bits:
            self._face_layout.addWidget(_rule())
            self._text("\n".join(bits), 15, name="fc_muted")
        en = card.get("en") or {}
        english = [en[k] for k in ("explain", "note") if en.get(k)]
        if english:
            self._english("\n".join(english), 15)
        if card.get("page") not in (None, ""):
            self._text(f"p. {card['page']}", 13, name="fc_muted")

    def _add_canvas(self, path: str, labels=(), mode: str = "plain", max_h: "int | None" = None) -> PictureCanvas:
        c = PictureCanvas(path, labels, mode)
        c.colors = self._pal
        self._canvas, self._canvas_max_h = c, max_h
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(c)
        holder.addStretch(1)
        self._face_layout.addLayout(holder)
        self._refit()
        return c

    def _refit(self) -> None:
        if self._canvas is None:
            return
        try:
            w = self._face_scroll.viewport().width() - 2 * 28 - 4
            self._canvas.fit(w, self._canvas_max_h)
        except RuntimeError:                        # the canvas was deleted
            self._canvas = None

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.Resize and obj is self._face_scroll.viewport():
            self._refit()
        return super().eventFilter(obj, ev)

    # ---- per type

    def _render_basic(self, e: dict) -> None:
        card = e["card"]
        q, a = (card["back"], card["front"]) if e["item"] == "rev" else (card["front"], card["back"])
        self._text(q, 24)
        self._english_prompt()
        self._set_action("Show answer", lambda: self._reveal_basic(a))

    def _reveal_basic(self, answer: str) -> None:
        self._face_layout.addWidget(_rule())
        self._cur["answer_lbl"] = self._text(answer, 22, bold=True, name="fc_reveal")
        self._english_answer()
        self._show_extra()
        self._show_grades()

    def _render_image(self, e: dict) -> None:
        card = e["card"]
        path = self._store.media_path(e["set_id"], card["image"])
        if e["item"] == "rev":
            self._text(card["back"], 24)
            self._english_prompt()

            def reveal():
                self._face_layout.addWidget(_rule())
                self._add_canvas(path, max_h=360)
                if card.get("front"):
                    self._text(card["front"], 18, name="fc_muted")
                self._show_extra()
                self._show_grades()
            self._set_action("Show answer", reveal)
            return
        if card.get("front"):
            self._text(card["front"], 20)
            self._english_prompt()
        self._add_canvas(path, max_h=360)
        self._set_action("Show answer", lambda: self._reveal_basic(card["back"]))

    def _render_cloze(self, e: dict) -> None:
        card = e["card"]
        n = int(e["item"][1:]) if e["item"].startswith("c") else 0
        lab = self._text(cloze_text(card["text"], n, revealed=False, accent=self._pal["accent"]), 24, rich=True)
        self._english_prompt()

        def reveal():
            lab.setText(cloze_text(card["text"], n, revealed=True, accent=self._pal["accent"]))
            self._english_answer()
            self._show_extra()
            self._show_grades()
        self._set_action("Show answer", reveal)

    def _render_mc(self, e: dict) -> None:
        card = e["card"]
        self._text(card["question"], 22)
        self._english_prompt()
        choices = list(card["choices"])
        self._rng.shuffle(choices)
        tiles = []
        for i, ch in enumerate(choices):
            t = Tile(ch, str(i + 1) if i < 9 else "", rtl=self._rtl())
            t.clicked.connect(lambda i=i: self._mc_pick(i))
            self._face_layout.addWidget(t)
            tiles.append(t)
        self._cur["tiles"] = tiles
        self._action_btn.hide()
        self._cur["action"] = None

    def _mc_pick(self, i: int) -> None:
        if self._cur.get("answered"):
            return
        tiles = self._cur["tiles"]
        if not 0 <= i < len(tiles):
            return
        self._cur["answered"] = True
        answer = self._cur["entry"]["card"]["answer"]
        right = tiles[i].text == answer
        for t in tiles:
            t.set_clickable(False)
            if t.text == answer:
                t.set_state("right")
            elif t is tiles[i]:
                t.set_state("wrong")
            else:
                t.set_state("off")
        self._english_answer()
        self._show_extra()
        self._set_action("Continue", lambda: self._grade(3 if right else 1))
        self._study_page.setFocus()

    def _render_order(self, e: dict) -> None:
        card = e["card"]
        self._text(card["prompt"], 22)
        self._english_prompt()
        steps = list(card["steps"])
        while len(steps) > 1 and steps == card["steps"]:
            self._rng.shuffle(steps)
        self._text("Your order", 13, name="fc_muted")
        picked_box = QVBoxLayout()
        picked_box.setSpacing(4)
        self._face_layout.addLayout(picked_box)
        self._text("Tap the steps in order", 13, name="fc_muted")
        pool = []
        for s in steps:
            t = Tile(s, rtl=self._rtl(), px=16)
            t.clicked.connect(lambda t=t: self._order_place(t))
            self._face_layout.addWidget(t)
            pool.append(t)
        self._cur.update(pool=pool, placed=[], picked_box=picked_box, placed_tiles=[])
        self._undo_btn.show()
        self._undo_btn.setEnabled(False)
        self._set_action("Check", self._order_check, enabled=False)

    def _order_place(self, tile: Tile) -> None:
        if self._cur.get("answered") or tile in self._cur["placed"]:
            return
        self._cur["placed"].append(tile)
        tile.hide()
        n = len(self._cur["placed"])
        shown = Tile(tile.text, str(n), rtl=self._rtl(), px=16)
        shown.set_clickable(False)
        shown.set_state("placed")
        self._cur["picked_box"].addWidget(shown)
        self._cur["placed_tiles"].append(shown)
        self._undo_btn.setEnabled(True)
        self._action_btn.setEnabled(n == len(self._cur["pool"]))

    def _order_undo(self) -> None:
        if self._cur.get("answered") or not self._cur.get("placed"):
            return
        tile = self._cur["placed"].pop()
        tile.show()
        shown = self._cur["placed_tiles"].pop()
        shown.setParent(None)
        shown.deleteLater()
        self._undo_btn.setEnabled(bool(self._cur["placed"]))
        self._action_btn.setEnabled(False)

    def _order_check(self) -> None:
        steps = self._cur["entry"]["card"]["steps"]
        placed = [t.text for t in self._cur["placed"]]
        self._cur["answered"] = True
        right = placed == steps
        for i, t in enumerate(self._cur["placed_tiles"]):
            t.set_state("right" if i < len(steps) and placed[i] == steps[i] else "wrong")
        self._undo_btn.hide()
        if not right:
            self._face_layout.addWidget(_rule())
            self._text("Correct order", 13, name="fc_muted")
            for i, s in enumerate(steps):
                t = Tile(s, str(i + 1), rtl=self._rtl(), px=16)
                t.set_clickable(False)
                self._face_layout.addWidget(t)
        self._english_answer()
        self._show_extra()
        self._cur["order_right"] = right
        self._set_action("Continue", lambda: self._grade(3 if right else 1))
        self._study_page.setFocus()

    def _render_typed(self, e: dict) -> None:
        card = e["card"]
        self._text(card["front"], 22)
        self._english_prompt()
        ed = QPlainTextEdit()
        _card_font(ed, 18)
        ed.setMinimumHeight(160)
        ed.setPlaceholderText("Write it from memory…")
        if self._rtl():
            ed.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            opt = ed.document().defaultTextOption()
            opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
            opt.setAlignment(Qt.AlignmentFlag.AlignRight)
            ed.document().setDefaultTextOption(opt)
        self._face_layout.addWidget(ed)
        self._cur["editor"] = ed
        self._set_action("Check", self._typed_check)
        ed.setFocus()

    def _typed_check(self) -> None:
        card = self._cur["entry"]["card"]
        ed = self._cur["editor"]
        ed.setReadOnly(True)
        marked = missing_words(card["answer"], ed.toPlainText())
        miss = sum(1 for _, m in marked if m)
        words = sum(1 for t, _ in marked if t.strip() and normalise_word(t))
        out = []
        for tok, m in marked:
            esc = html.escape(tok).replace("\n", "<br>")
            out.append(f'<span style="color:{self._pal["bad"]}; text-decoration: underline">{esc}</span>'
                       if m else esc)
        self._face_layout.addWidget(_rule())
        self._text(f"{words - miss} of {words} words" + (" — the missing ones are marked" if miss else ""),
                   13, name="fc_muted")
        self._cur["answer_lbl"] = self._text("".join(out), 19, rich=True)
        self._english_answer()
        self._show_extra()
        self._show_grades()

    def _render_occlusion(self, e: dict) -> None:
        card = e["card"]
        path = self._store.media_path(e["set_id"], card["image"])
        one = e["item"].startswith("l")
        self._text(card.get("prompt") or ("Name the hidden label" if one else "Name every hidden label"), 20)
        self._english_prompt()
        canvas = self._add_canvas(path, card["labels"], "one" if one else "all")
        if one:
            canvas.target = int(e["item"][1:])
            canvas.update()

            def reveal():
                canvas.revealed.add(canvas.target)
                canvas.update()
                self._cur["answer_lbl"] = self._text(card["labels"][canvas.target]["text"], 24,
                                                     bold=True, name="fc_reveal")
                self._english_answer()
                self._show_extra()
                self._show_grades()
            self._set_action("Show answer", reveal)
        else:
            self._reveal_all_btn.show()
            self._cur["occ_list"] = self._text("", 17, name="fc_reveal")
            canvas.box_clicked.connect(lambda _i: self._occ_update())
            self._set_action("Done", self._occ_done)

    def _scroll_to_target(self) -> None:
        c = self._canvas
        if c is None or c.target < 0 or c.mode != "one":
            return
        try:
            r = c.box_rect(c.target)
            pt = c.mapTo(self._face, r.center().toPoint())
            self._face_scroll.ensureVisible(pt.x(), pt.y(), 60, 160)
        except RuntimeError:
            pass

    def _occ_update(self) -> None:
        c = self._canvas
        labels = c.labels
        names = [labels[i]["text"] for i in sorted(c.revealed)]
        self._cur["occ_list"].setText("  ·  ".join(names))
        if len(c.revealed) == len(labels):
            self._occ_done()

    def _occ_reveal_all(self) -> None:
        c = self._canvas
        if c is None or self._cur.get("answered"):
            return
        c.revealed = set(range(len(c.labels)))
        c.update()
        self._occ_update()

    def _occ_done(self) -> None:
        if self._cur.get("answered"):
            return
        c = self._canvas
        c.revealed = set(range(len(c.labels)))
        c.update()
        self._cur["occ_list"].setText("  ·  ".join(l["text"] for l in c.labels))
        self._reveal_all_btn.hide()
        self._show_extra()
        self._show_grades()

    # ---- grading

    def _grade(self, grade: int) -> None:
        e = self._cur.get("entry")
        if e is None:
            return
        key = (e["card_id"], e["item"])
        if key not in self._first:
            self._first[key] = {"entry": e, "right": grade > 1}
        if self._round_mode != "exam":
            try:
                prog = self._store.review(e["card_id"], e["item"], grade, source="mac")
            except Exception as ex:                 # noqa: BLE001 — a vanished card must not end the round
                prog = e.get("progress")
                self._set_lbl.setText(f"Not saved: {ex}")
            if grade == 1:
                again = dict(e, progress=prog)
                at = min(len(self._queue), self._idx + self._rng.randint(4, 7))
                self._queue.insert(at, again)
        self._idx += 1
        self._show_entry()

    def _on_key(self, ev) -> bool:
        if self._pages.currentWidget() is not self._study_page or not self._cur:
            return False
        key = ev.key()
        t = self._cur["entry"]["card"]["type"]
        if key == Qt.Key.Key_Space or key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._grade_box.isVisible():
                self._grade(3)
            elif self._action_btn.isVisible():
                self._action()
            return True
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            n = key - Qt.Key.Key_0
            if self._grade_box.isVisible() and n <= 4:
                self._grade(n)
            elif t == "mc" and not self._cur.get("answered"):
                self._mc_pick(n - 1)
            elif t == "order" and not self._cur.get("answered"):
                vis = [x for x in self._cur["pool"] if x not in self._cur["placed"]]
                if n <= len(vis):
                    self._order_place(vis[n - 1])
            return True
        if key == Qt.Key.Key_Escape:
            self._end_round()
            return True
        return False

    def _end_round(self) -> None:
        if self._first:
            self._show_summary()
        else:
            self._back_to_library()

    # ------------------------------------------------------------ summary

    def _show_summary(self) -> None:
        self._cur = {}
        self._canvas = None
        firsts = list(self._first.values())
        n = len(firsts)
        right = sum(1 for f in firsts if f["right"])
        pct = round(100 * right / n) if n else 0
        self._sum_pct.setText(f"{pct}%")
        what = "exam score" if self._round_mode == "exam" else "right on the first attempt"
        self._sum_sub.setText(f"{right} of {n} {what}")
        per: dict = {}
        for f in firsts:
            row = per.setdefault(f["entry"].get("set", ""), [0, 0])
            row[0] += f["right"]
            row[1] += 1
        self._sum_table.setRowCount(len(per))
        for r, (name, (ok, tot)) in enumerate(sorted(per.items())):
            for c, val in enumerate((name, str(ok), str(tot))):
                it = QTableWidgetItem(val)
                if c:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._sum_table.setItem(r, c, it)
        rows_h = sum(self._sum_table.rowHeight(i) for i in range(len(per)))
        self._sum_table.setFixedHeight(min(200, self._sum_table.horizontalHeader().height() + rows_h + 4))
        _clear(self._miss_layout)
        misses = [f["entry"] for f in firsts if not f["right"]]
        self._misses = misses
        for e in misses:
            q, a = question_answer(e)
            page = e["card"].get("page")
            rtl = e.get("dir") == "rtl"
            arrow = "←" if rtl else "→"
            lab = _label(f"{q}\n{arrow} {a}" + (f"   (p. {page})" if page not in (None, "") else ""))
            _card_font(lab, 15)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
            lab.setAlignment(_align(rtl))
            self._miss_layout.addWidget(lab)
        if not misses:
            self._miss_layout.addWidget(_label("None — every card right first time.", "fc_muted"))
        self._miss_layout.addStretch(1)
        self._practise_btn.setEnabled(bool(misses))
        self._pages.setCurrentWidget(self._sum_page)

    def _practise(self) -> None:
        if self._misses:
            q = [dict(e) for e in self._misses]
            self._rng.shuffle(q)
            self._begin(q, self._round_mode)

    def _back_to_library(self) -> None:
        self._cur = {}
        self._canvas = None
        self._pages.setCurrentWidget(self._lib_page)
        self.reload()


# ---------------------------------------------------------------- dialogs

class NewSetDialog(QDialog):
    def __init__(self, subjects: "list[str]", subject: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("New set")
        f = QFormLayout(self)
        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.addItems(subjects)
        if subject:
            self.subject.setCurrentText(subject)
        self.name = QLineEdit()
        self.direction = QComboBox()
        self.direction.addItem("Left to right", "ltr")
        self.direction.addItem("Right to left (Hebrew, Arabic)", "rtl")
        f.addRow("Subject", self.subject)
        f.addRow("Set name", self.name)
        f.addRow("Direction", self.direction)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self) -> "tuple[str, str, str]":
        return (self.subject.currentText().strip(), self.name.text().strip(),
                self.direction.currentData())


def _plain(h: int = 70) -> QPlainTextEdit:
    e = QPlainTextEdit()
    e.setFixedHeight(h)
    e.setTabChangesFocus(True)
    return e


class _Form(QWidget):
    """One card type's fields. dump() returns the card minus common fields."""

    kind = ""

    def __init__(self, editor: "SetEditorDialog"):
        super().__init__()
        self.editor = editor
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)

    def load(self, card: dict) -> None: ...
    def dump(self) -> dict: ...
    def clear(self) -> None:
        self.load({})


class _BasicForm(_Form):
    kind = "basic"

    def __init__(self, editor):
        super().__init__(editor)
        self.front, self.back = _plain(), _plain()
        self.both = QCheckBox("Ask both ways (back → front too)")
        self.form.addRow("Front", self.front)
        self.form.addRow("Back", self.back)
        self.form.addRow("", self.both)

    def load(self, card):
        self.front.setPlainText(card.get("front", ""))
        self.back.setPlainText(card.get("back", ""))
        self.both.setChecked(bool(card.get("both_ways")))

    def dump(self):
        out = {"type": "basic", "front": self.front.toPlainText(), "back": self.back.toPlainText()}
        if self.both.isChecked():
            out["both_ways"] = True
        return out


class _TypedForm(_Form):
    kind = "typed"

    def __init__(self, editor):
        super().__init__(editor)
        self.front, self.answer = _plain(), _plain(150)
        self.form.addRow("Question", self.front)
        self.form.addRow("Answer", self.answer)

    def load(self, card):
        self.front.setPlainText(card.get("front", ""))
        self.answer.setPlainText(card.get("answer", ""))

    def dump(self):
        return {"type": "typed", "front": self.front.toPlainText(), "answer": self.answer.toPlainText()}


class _ClozeForm(_Form):
    kind = "cloze"

    def __init__(self, editor):
        super().__init__(editor)
        self.text = _plain(120)
        self.gap_btn = _button("Make gap", "", self._make_gap)
        self.form.addRow("Text", self.text)
        hint = _label("Select words and press Make gap — each {{gap}} is asked on its own.", "fc_muted")
        row = QHBoxLayout()
        row.addWidget(self.gap_btn)
        row.addWidget(hint, 1)
        self.form.addRow("", row)

    def _make_gap(self):
        cur = self.text.textCursor()
        sel = cur.selectedText()
        if not sel.strip():
            return
        cur.insertText("{{" + sel + "}}")
        self.text.setTextCursor(cur)

    def load(self, card):
        self.text.setPlainText(card.get("text", ""))

    def dump(self):
        return {"type": "cloze", "text": self.text.toPlainText()}


class _McForm(_Form):
    kind = "mc"

    def __init__(self, editor):
        super().__init__(editor)
        self.question = _plain()
        self.form.addRow("Question", self.question)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(4)
        self.group = QButtonGroup(self)
        self.rows: list = []
        self.form.addRow("Choices", self.rows_box)
        self.add_btn = _button("Add choice", "", lambda: self._add_row())
        self.form.addRow("", self.add_btn)
        self.form.addRow("", _label("The round button marks the correct answer.", "fc_muted"))
        self.load({})

    def _add_row(self, text: str = "", correct: bool = False):
        if len(self.rows) >= 8:
            return
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        radio = QRadioButton()
        self.group.addButton(radio)
        radio.setChecked(correct)
        edit = QLineEdit(text)
        rm = _button("✕", "fc_link")
        h.addWidget(radio)
        h.addWidget(edit, 1)
        h.addWidget(rm)
        row = (w, radio, edit)
        rm.clicked.connect(lambda _=False, r=row: self._remove_row(r))
        self.rows.append(row)
        self.rows_box.addWidget(w)
        self.add_btn.setEnabled(len(self.rows) < 8)

    def _remove_row(self, row):
        if len(self.rows) <= 2:
            return
        self.rows.remove(row)
        self.group.removeButton(row[1])
        row[0].setParent(None)
        row[0].deleteLater()
        self.add_btn.setEnabled(True)

    def load(self, card):
        self.question.setPlainText(card.get("question", ""))
        for w, radio, _ in self.rows:
            self.group.removeButton(radio)
            w.setParent(None)
            w.deleteLater()
        self.rows = []
        choices = card.get("choices") or ["", "", "", ""]
        for c in choices:
            self._add_row(c, c == card.get("answer"))

    def dump(self):
        choices = [e.text() for _, _, e in self.rows]
        picked = [e.text() for _, r, e in self.rows if r.isChecked()]
        if not picked:
            raise CardError("Mark the correct answer with its round button.")
        return {"type": "mc", "question": self.question.toPlainText(),
                "choices": [c for c in choices if c.strip()], "answer": picked[0]}


class _OrderForm(_Form):
    kind = "order"

    def __init__(self, editor):
        super().__init__(editor)
        self.prompt = _plain(60)
        self.steps = QListWidget()
        self.steps.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.steps.setMinimumHeight(150)
        self.form.addRow("Prompt", self.prompt)
        self.form.addRow("Steps (in the right order)", self.steps)
        row = QHBoxLayout()
        for text, cb in (("Add step", self._add), ("Remove", self._remove),
                         ("Up", lambda: self._move(-1)), ("Down", lambda: self._move(1))):
            row.addWidget(_button(text, "", cb))
        row.addStretch(1)
        self.form.addRow("", row)

    def _item(self, text):
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        return it

    def _add(self):
        it = self._item("")
        self.steps.addItem(it)
        self.steps.setCurrentItem(it)
        self.steps.editItem(it)

    def _remove(self):
        r = self.steps.currentRow()
        if r >= 0:
            self.steps.takeItem(r)

    def _move(self, d):
        r = self.steps.currentRow()
        if r < 0 or not 0 <= r + d < self.steps.count():
            return
        it = self.steps.takeItem(r)
        self.steps.insertItem(r + d, it)
        self.steps.setCurrentRow(r + d)

    def load(self, card):
        self.prompt.setPlainText(card.get("prompt", ""))
        self.steps.clear()
        for s in card.get("steps", []):
            self.steps.addItem(self._item(s))

    def dump(self):
        steps = [self.steps.item(i).text() for i in range(self.steps.count())]
        return {"type": "order", "prompt": self.prompt.toPlainText(),
                "steps": [s for s in steps if s.strip()]}


class _PictureMixin:
    def _choose_picture(self) -> "str | None":
        path = self.editor.pick_picture()
        if not path:
            return None
        try:
            return self.editor.copy_picture(path)
        except Exception as e:                      # noqa: BLE001
            self.editor.show_error(str(e))
            return None


class _ImageForm(_PictureMixin, _Form):
    kind = "image"

    def __init__(self, editor):
        super().__init__(editor)
        self.image = ""
        self.pic_btn = _button("Choose picture…", "", self._pick)
        self.pic_lbl = _label("", "fc_muted", wrap=False)
        row = QHBoxLayout()
        row.addWidget(self.pic_btn)
        row.addWidget(self.pic_lbl, 1)
        self.form.addRow("Picture", row)
        self.preview = PictureCanvas()
        self.form.addRow("", self.preview)
        self.front, self.back = _plain(50), _plain(50)
        self.both = QCheckBox("Ask both ways (name → picture too)")
        self.form.addRow("Prompt (optional)", self.front)
        self.form.addRow("Answer", self.back)
        self.form.addRow("", self.both)

    def _set_image(self, rel):
        self.image = rel or ""
        self.pic_lbl.setText(self.image)
        self.preview.set_picture(self.editor.store.media_path(self.editor.set_id, self.image)
                                 if self.image else "")
        self.preview.fit(320, 180)

    def _pick(self):
        rel = self._choose_picture()
        if rel:
            self._set_image(rel)

    def load(self, card):
        self._set_image(card.get("image", ""))
        self.front.setPlainText(card.get("front", ""))
        self.back.setPlainText(card.get("back", ""))
        self.both.setChecked(bool(card.get("both_ways")))

    def dump(self):
        out = {"type": "image", "image": self.image, "back": self.back.toPlainText()}
        if self.front.toPlainText().strip():
            out["front"] = self.front.toPlainText()
        if self.both.isChecked():
            out["both_ways"] = True
        return out


class _OcclusionForm(_PictureMixin, _Form):
    kind = "occlusion"

    def __init__(self, editor):
        super().__init__(editor)
        self.image = ""
        self.pic_btn = _button("Choose picture…", "", self._pick)
        self.pic_lbl = _label("", "fc_muted", wrap=False)
        row = QHBoxLayout()
        row.addWidget(self.pic_btn)
        row.addWidget(self.pic_lbl, 1)
        self.form.addRow("Picture", row)
        self.canvas = PictureCanvas(mode="edit")
        self.canvas.box_drawn.connect(self._box_drawn)
        self.canvas.box_selected.connect(lambda i: self.labels_list.setCurrentRow(i))
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setMinimumHeight(320)
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.form.addRow(_label("Drag on the picture to cover a label", "fc_muted"))
        self.form.addRow(scroll)
        self.labels_list = QListWidget()
        self.labels_list.setMinimumHeight(110)
        self.labels_list.currentRowChanged.connect(self._select)
        self.form.addRow("Labels", self.labels_list)
        lrow = QHBoxLayout()
        self.label_text = QLineEdit()
        self.label_text.setPlaceholderText("What the covered label says")
        self.label_text.textEdited.connect(self._edit_text)
        self.del_btn = _button("Delete label", "", self._delete)
        lrow.addWidget(self.label_text, 1)
        lrow.addWidget(self.del_btn)
        self.form.addRow("Text", lrow)
        self.ask = QComboBox()
        self.ask.addItem("One label at a time (each is its own question)", "one_at_a_time")
        self.ask.addItem("All at once (reveal one by one, graded together)", "all_at_once")
        self.form.addRow("Ask", self.ask)
        self.prompt = QLineEdit()
        self.form.addRow("Prompt (optional)", self.prompt)

    def _set_image(self, rel):
        self.image = rel or ""
        self.pic_lbl.setText(self.image)
        self.canvas.set_picture(self.editor.store.media_path(self.editor.set_id, self.image)
                                if self.image else "")
        self.canvas.fit(440, max_scale=1.2)

    def _pick(self):
        rel = self._choose_picture()
        if rel:
            self._set_image(rel)

    def _refresh_list(self, select: int = -1):
        self.labels_list.blockSignals(True)
        self.labels_list.clear()
        for i, lab in enumerate(self.canvas.labels):
            self.labels_list.addItem(f"{i + 1}. {lab['text'] or '(type its text)'}")
        self.labels_list.blockSignals(False)
        if select >= 0:
            self.labels_list.setCurrentRow(select)
        self.canvas.update()

    def _box_drawn(self, box):
        self.canvas.labels.append({"text": "", "box": box})
        self._refresh_list(len(self.canvas.labels) - 1)
        self.label_text.setFocus()

    def _select(self, i):
        self.canvas.selected = i
        self.canvas.update()
        ok = 0 <= i < len(self.canvas.labels)
        self.label_text.setText(self.canvas.labels[i]["text"] if ok else "")

    def _edit_text(self, text):
        i = self.labels_list.currentRow()
        if 0 <= i < len(self.canvas.labels):
            self.canvas.labels[i]["text"] = text
            it = self.labels_list.item(i)
            it.setText(f"{i + 1}. {text or '(type its text)'}")

    def _delete(self):
        i = self.labels_list.currentRow()
        if 0 <= i < len(self.canvas.labels):
            self.canvas.labels.pop(i)
            self.canvas.selected = -1
            self._refresh_list(min(i, len(self.canvas.labels) - 1))

    def load(self, card):
        self._set_image(card.get("image", ""))
        self.canvas.labels = [dict(l) for l in card.get("labels", [])]
        self.canvas.selected = -1
        self._refresh_list()
        self.label_text.clear()
        self.ask.setCurrentIndex(1 if card.get("ask") == "all_at_once" else 0)
        self.prompt.setText(card.get("prompt", ""))

    def dump(self):
        out = {"type": "occlusion", "image": self.image, "ask": self.ask.currentData(),
               "labels": [dict(l) for l in self.canvas.labels]}
        if self.prompt.text().strip():
            out["prompt"] = self.prompt.text()
        return out


FORMS = (_BasicForm, _ClozeForm, _McForm, _OrderForm, _TypedForm, _ImageForm, _OcclusionForm)


class SetEditorDialog(QDialog):
    """Every card of one set; add, edit, delete, move. Saves through the store,
    so the rules are `cardformat.normalise`'s and its sentences show inline."""

    def __init__(self, store: FlashcardStore, set_id: int, parent=None, *, dark: bool = True):
        super().__init__(parent)
        self.store, self.set_id = store, set_id
        self.setStyleSheet(_qss(_palette(dark)))
        self.resize(1040, 800)
        self._cards: list = []
        self.editing_id: "int | None" = None
        info = store.get_set(set_id)
        self.setWindowTitle(f"Edit cards — {info['name']}")
        rtl = info.get("dir") == "rtl"

        split = QSplitter(Qt.Orientation.Horizontal)
        outer = QVBoxLayout(self)
        outer.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        if rtl:
            self.list.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.list.currentRowChanged.connect(self._load_row)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_btn = _button("Add", "", self.new_card)
        self.del_btn = _button("Delete", "", self._delete)
        self.up_btn = _button("↑", "", lambda: self._move(-1))
        self.down_btn = _button("↓", "", lambda: self._move(1))
        for b in (self.add_btn, self.del_btn, self.up_btn, self.down_btn):
            row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(_label("Type", "fc_muted", wrap=False))
        self.type_combo = QComboBox()
        for F in FORMS:
            self.type_combo.addItem(TYPE_LABELS[F.kind], F.kind)
        top.addWidget(self.type_combo, 1)
        rv.addLayout(top)
        self.stack = QStackedWidget()
        self.forms = {F.kind: F(self) for F in FORMS}
        for f in self.forms.values():
            if rtl:
                for ed in f.findChildren(QPlainTextEdit) + f.findChildren(QLineEdit):
                    ed.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.stack.addWidget(f)
        self.type_combo.currentIndexChanged.connect(
            lambda _i: self.stack.setCurrentWidget(self.forms[self.type_combo.currentData()]))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.stack)
        rv.addWidget(scroll, 1)
        common = QFormLayout()
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("comma, separated")
        self.page = QLineEdit()
        self.explain = _plain(50)
        common.addRow("Tags", self.tags)
        common.addRow("Page", self.page)
        common.addRow("Explanation", self.explain)
        rv.addLayout(common)
        self.error = _label("", "fc_error")
        rv.addWidget(self.error)
        brow = QHBoxLayout()
        self.mode_lbl = _label("New card", "fc_muted", wrap=False)
        brow.addWidget(self.mode_lbl, 1)
        self.save_btn = _button("Save card", "primary", self.save)
        self.close_btn = _button("Close", "", self.accept)
        brow.addWidget(self.close_btn)
        brow.addWidget(self.save_btn)
        rv.addLayout(brow)
        split.addWidget(right)
        split.setSizes([300, 680])
        self._refresh()
        self.new_card()

    # hooks the forms call (and tests replace)
    def pick_picture(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "Choose picture", os.path.expanduser("~"),
                                              "Pictures (*.png *.jpg *.jpeg *.gif *.webp)")
        return path

    def copy_picture(self, path: str) -> str:
        with open(path, "rb") as f:
            data = f.read()
        base, ext = os.path.splitext(re.sub(r"[^\w.-]+", "-", os.path.basename(path)))
        rel, n = f"images/{base}{ext}", 2
        while os.path.exists(self.store.media_path(self.set_id, rel)):
            with open(self.store.media_path(self.set_id, rel), "rb") as f:
                if f.read() == data:
                    return rel
            rel, n = f"images/{base}-{n}{ext}", n + 1
        return self.store.save_media(self.set_id, rel, data)

    def show_error(self, text: str) -> None:
        self.error.setText(text)

    # list

    @staticmethod
    def summary(card: dict) -> str:
        first = (card.get("front") or card.get("question") or card.get("prompt") or card.get("text")
                 or card.get("back") or card.get("image") or "")
        first = first.strip().splitlines()[0] if first.strip() else ""
        return f"{TYPE_LABELS.get(card['type'], card['type'])} · {first[:70]}"

    def _refresh(self, select_id: "int | None" = None) -> None:
        self._cards = self.store.get_set(self.set_id)["cards"]
        self.list.blockSignals(True)
        self.list.clear()
        for c in self._cards:
            self.list.addItem(self.summary(c))
        row = next((i for i, c in enumerate(self._cards) if c["id"] == select_id), -1)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)

    def _load_row(self, row: int) -> None:
        if not 0 <= row < len(self._cards):
            return
        c = self._cards[row]
        card = {k: v for k, v in c.items() if k not in ("id", "position", "items", "progress")}
        self.editing_id = c["id"]
        self.type_combo.setCurrentIndex(self.type_combo.findData(card["type"]))
        self.forms[card["type"]].load(card)
        self.tags.setText(", ".join(card.get("tags", [])))
        self.page.setText(str(card.get("page", "")))
        self.explain.setPlainText(card.get("explain", ""))
        # Not edited here, but never dropped by an edit either.
        self._kept = {k: card[k] for k in ("en", "note") if card.get(k)}
        self.error.clear()
        self.mode_lbl.setText(f"Editing card {row + 1} of {len(self._cards)}")

    def new_card(self) -> None:
        self.editing_id = None
        self.list.blockSignals(True)
        self.list.setCurrentRow(-1)
        self.list.blockSignals(False)
        for f in self.forms.values():
            f.clear()
        self.tags.clear()
        self.page.clear()
        self.explain.clear()
        self._kept = {}
        self.error.clear()
        self.mode_lbl.setText("New card")

    def card(self) -> dict:
        card = self.forms[self.type_combo.currentData()].dump()
        tags = [t.strip() for t in self.tags.text().split(",") if t.strip()]
        if tags:
            card["tags"] = tags
        page = self.page.text().strip()
        if page:
            card["page"] = int(page) if page.isdigit() else page
        if self.explain.toPlainText().strip():
            card["explain"] = self.explain.toPlainText()
        if self.editing_id is not None:
            kept = getattr(self, "_kept", {})
            if kept.get("note"):
                card["note"] = kept["note"]
            if kept.get("en"):
                card["en"] = cardformat.english_that_fits(kept["en"], card)
                if not card["en"]:
                    del card["en"]
        return card

    def save(self) -> None:
        try:
            card = self.card()
            if self.editing_id is None:
                cid = self.store.add_card(self.set_id, card)
            else:
                cid = self.editing_id
                self.store.update_card(cid, card)
        except (CardError, FlashcardError) as e:
            self.error.setText(str(e).replace("card: ", "", 1))
            return
        except Exception as e:                      # noqa: BLE001 — a sentence, never a crash
            self.error.setText(f"Could not save: {e}")
            return
        self.error.clear()
        self._refresh(cid)
        self._load_row(self.list.currentRow())

    def _delete(self) -> None:
        if self.editing_id is None:
            return
        box = QMessageBox(self)
        box.setText("Delete this card and your progress on it?")
        ok = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        if not self._confirm_delete(box, ok):
            return
        self.store.delete_card(self.editing_id)
        self._refresh()
        self.new_card()

    def _confirm_delete(self, box, ok) -> bool:
        box.exec()
        return box.clickedButton() is ok

    def _move(self, d: int) -> None:
        if self.editing_id is None:
            return
        self.store.move_card(self.editing_id, d)
        self._refresh(self.editing_id)

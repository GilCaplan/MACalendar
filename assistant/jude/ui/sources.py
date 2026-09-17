"""The cards under an answer: what Jude actually read.

A citation nobody can check is decoration, so every card carries the ref as a
link to Sefaria, the English Jude was given, and the Hebrew or Aramaic behind
it — folded away, because the page it belongs on is the original, not the
translation, and anyone who wants it will ask for it.
"""

from __future__ import annotations

import re
import urllib.parse

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

SEFARIA = "https://www.sefaria.org/"

_REF = re.compile(r"^(.*?)\s+(\S+)$")


def sefaria_url(source) -> str:
    """The page this ref lives on, per the rule in `jude/ARCHITECTURE.md`.

    Talmud is the exception, and not a small one: our coordinates are
    chapter-based while Sefaria addresses a tractate by daf (2a, 3b), so a
    constructed URL would be a confidently wrong page rather than a missing
    one. The tractate overview is the honest answer. Anything we cannot split
    into book + section falls back to a Sefaria search, which at worst costs
    the reader one click.
    """
    raw = source if isinstance(source, str) else (source.get("ref") or "")
    category = "" if isinstance(source, str) else (source.get("category") or "")
    ref = str(raw).strip().strip("[]").strip()
    match = _REF.match(ref)
    if not match or not match.group(1).strip():
        return SEFARIA + "search#q=" + urllib.parse.quote(ref)
    book = match.group(1).strip().replace(" ", "_")
    if category == "Talmud":
        return SEFARIA + book
    return SEFARIA + book + "." + match.group(2).replace(":", ".")


def match_percent(source: dict) -> str:
    """Jude reports a distance, not a similarity — 0 is a perfect match — so
    the number on the card is inverted before it is shown as a percentage."""
    score = source.get("score")
    if score is None:
        return ""
    try:
        return f"{round((1 - min(float(score), 1.0)) * 100)}% match"
    except (TypeError, ValueError):
        return ""


class SourceCard(QFrame):
    def __init__(self, source: dict, theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._source = source
        self.setObjectName("jude_source_card")
        self.setStyleSheet(
            f"QFrame#jude_source_card {{ background:{theme.surface};"
            f" border:1px solid {theme.border}; border-radius:{theme.radius_md}px; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(8)
        ref = QLabel(
            f"<a href='{sefaria_url(source)}' style='color:{theme.accent};"
            f" text-decoration:none;'>{_escape(source.get('ref'))}</a>")
        ref.setOpenExternalLinks(True)     # Sefaria belongs in a browser, not in here
        ref.setToolTip("Open on Sefaria")
        ref.setStyleSheet("font-weight:600; font-size:12.5px;")
        head.addWidget(ref)

        if source.get("is_primary") is True:
            head.addWidget(_chip("⚖ Primary", theme.accent, theme))

        category = source.get("category") or ""
        if category:
            head.addWidget(_chip(category, theme.text2, theme))

        percent = match_percent(source)
        if percent:
            score = QLabel(percent)
            score.setStyleSheet(f"color:{theme.text2}; font-size:10.5px;")
            head.addWidget(score)

        head.addStretch(1)

        self._hebrew = (source.get("he_text") or "").strip()
        if self._hebrew:
            self._toggle = QPushButton("🔤 Hebrew ▾")
            self._toggle.setObjectName("flat")
            self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self._toggle.setStyleSheet(f"color:{theme.text2}; font-size:11px;")
            self._toggle.clicked.connect(self._on_toggle)
            head.addWidget(self._toggle)
        lay.addLayout(head)

        english = QLabel(f'"{_escape(source.get("en_text"))}"')
        english.setWordWrap(True)
        english.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        english.setStyleSheet(f"color:{theme.text}; font-size:12px;")
        lay.addWidget(english)

        self._he_label = None
        if self._hebrew:
            self._he_label = QLabel(_escape(self._hebrew))
            self._he_label.setWordWrap(True)
            self._he_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            # Right-to-left as a layout direction, not merely right alignment:
            # a Hebrew line that ends in a bracket or a number is punctuated on
            # the wrong side without it.
            self._he_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self._he_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._he_label.setStyleSheet(
                f"color:{theme.text}; font-size:14px; padding-top:4px;"
                f" border-top:1px solid {theme.border};")
            self._he_label.hide()
            lay.addWidget(self._he_label)

    def _on_toggle(self) -> None:
        if self._he_label is None:
            return
        shown = not self._he_label.isVisible()
        self._he_label.setVisible(shown)
        self._toggle.setText("🔤 Hebrew ▴" if shown else "🔤 Hebrew ▾")


def _escape(text) -> str:
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _chip(text: str, colour: str, theme) -> QLabel:
    chip = QLabel(text)
    chip.setStyleSheet(
        f"color:{colour}; border:1px solid {colour}; border-radius:{theme.radius_sm}px;"
        f" padding:0px 5px; font-size:10px; font-weight:600;")
    return chip


def _by_category(sources: list) -> "list[tuple[str, list]]":
    """Grouped in the order the categories first appear — Jude returns its
    sources ranked, and re-sorting them alphabetically would hide that."""
    groups: "dict[str, list]" = {}
    for source in sources:
        key = source.get("planned_category") or source.get("category") or "Other"
        groups.setdefault(key, []).append(source)
    return list(groups.items())


class _Section(QWidget):
    def __init__(self, title: str, sources: list, theme, accent: bool, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        label = QLabel(f"{title} ({len(sources)})")
        colour = theme.accent if accent else theme.text2
        label.setStyleSheet(
            f"color:{colour}; font-size:10.5px; font-weight:700;"
            " text-transform:uppercase; letter-spacing:0.04em;")
        lay.addWidget(label)

        for category, items in _by_category(sources):
            heading = QLabel(f"{category} · {len(items)}")
            heading.setStyleSheet(f"color:{theme.text2}; font-size:10px;")
            lay.addWidget(heading)
            for source in items:
                card = SourceCard(source, theme, self)
                if accent:
                    # The primary hierarchy (Torah → Mishnah → Talmud → Rambam →
                    # Shulchan Arukh) is what a ruling is actually built on; the
                    # accent border is the one visual difference that says so.
                    card.setStyleSheet(
                        f"QFrame#jude_source_card {{ background:{theme.surface};"
                        f" border:1px solid {theme.accent};"
                        f" border-radius:{theme.radius_md}px; }}")
                lay.addWidget(card)


class SourcesView(QFrame):
    """Every source behind one answer.

    `is_primary` only appears when Jude detected a halachic topic and ran the
    dual retrieval, so the two-section layout is not the common case — when the
    field is absent the cards are simply grouped by category.
    """

    def __init__(self, sources: list, theme, parent=None) -> None:
        super().__init__(parent)
        sources = [s for s in (sources or []) if isinstance(s, dict)]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)

        header = QLabel(f"📚 Sources ({len(sources)})")
        header.setStyleSheet(
            f"color:{theme.text2}; font-size:11px; font-weight:700;")
        lay.addWidget(header)

        primary = [s for s in sources if s.get("is_primary") is True]
        secondary = [s for s in sources if s.get("is_primary") is False]
        rest = [s for s in sources if s.get("is_primary") is None]

        if primary or secondary:
            if primary:
                lay.addWidget(_Section("⚖ Primary Sources", primary, theme, True, self))
            if secondary:
                lay.addWidget(_Section("🔍 Secondary Sources", secondary, theme, False, self))
            if rest:
                lay.addWidget(_Section("Other Sources", rest, theme, False, self))
        else:
            for category, items in _by_category(sources):
                heading = QLabel(f"{category} · {len(items)}")
                heading.setStyleSheet(f"color:{theme.text2}; font-size:10px;")
                lay.addWidget(heading)
                for source in items:
                    lay.addWidget(SourceCard(source, theme, self))

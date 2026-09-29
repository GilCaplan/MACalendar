"""The ⓘ beside a setting whose effect is not obvious from its name.

Gil, 2026-09-29: *"perhaps add info tooltip for non trivial features"*. Many
settings already carried an explanation — as a hover tooltip, which nobody
finds. `attach(root)` gives every control under `root` that has one a small
ⓘ button beside it: hovering shows the text at once, clicking shows it too
(a tooltip alone needs a steady mouse and a delay). The explanation stays in
ONE place, the control's own `setToolTip`, so the ⓘ can never say something
different from the tooltip.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QHBoxLayout,
                             QLineEdit, QToolButton, QToolTip, QWidget)

_KINDS = (QCheckBox, QComboBox, QLineEdit, QAbstractSpinBox)


def info_button(text: str, parent: QWidget | None = None) -> QToolButton:
    b = QToolButton(parent)
    b.setObjectName("info_tip")
    b.setText("ⓘ")
    b.setToolTip(text)
    b.setAutoRaise(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setAccessibleName("More about this setting")
    from assistant.calendar_ui import styles as _styles
    dark = getattr(_styles, "_dark", True)
    # Explicit colours: palette(placeholder-text) rendered near-black on the
    # dark theme, and an ⓘ nobody can see is no ⓘ.
    b.setStyleSheet("QToolButton#info_tip { border: none; background: transparent;"
                    f" color: {'#9a9aa2' if dark else '#6e6e73'}; font-size: 15px; padding: 0 3px; }}"
                    f"QToolButton#info_tip:hover {{ color: {_styles.get_accent()}; }}")
    b.clicked.connect(lambda: QToolTip.showText(
        b.mapToGlobal(QPoint(b.width() // 2, b.height())), text, b))
    return b


def attach(root: QWidget) -> int:
    """Put an ⓘ beside every control under `root` that explains itself.
    Returns how many were added. Safe to call twice (a control is done once)
    and one ⓘ per explanation per row — two boxes sharing a text (a
    "from … to" pair) get one."""
    added = 0
    seen: set = set()
    for w in root.findChildren(QWidget):
        if not isinstance(w, _KINDS) or w.property("info_tip_done"):
            continue
        text = (w.toolTip() or "").strip()
        parent = w.parentWidget()
        if not text or parent is None or parent.layout() is None:
            continue
        key = (id(parent), text)
        if key in seen:
            w.setProperty("info_tip_done", True)
            continue
        holder = QWidget(parent)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        item = parent.layout().replaceWidget(w, holder, Qt.FindChildOption.FindChildrenRecursively)
        if item is None:                    # not in a layout we can reach: leave it
            holder.deleteLater()
            continue
        row.addWidget(w)
        row.addWidget(info_button(text, holder))
        if not isinstance(w, (QComboBox, QLineEdit, QAbstractSpinBox)):
            row.addStretch(1)
        w.setProperty("info_tip_done", True)
        seen.add(key)
        added += 1
    return added

""""How to talk to me" — a short, static tips screen (Mac).

Two sections, in reading order: "How it works" (`STEPS`, what the engine does
with a sentence, one line each with a spoken example) and "Tips" (`TIPS`).
Content lives in `assistant/tips.py`, tied to the engine version it was
verified against (see that module's docstring); this file is presentation
only. Same shape as `categories_dialog.CategoriesDialog`: plain QVBoxLayout,
a muted intro label, a "Done" button.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QFrame, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from assistant.tips import STEPS, TIPS


def _section(text: str) -> QLabel:
    label = QLabel(text.upper())
    font = QFont(label.font())
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    label.setFont(font)
    label.setObjectName("tipSection")
    return label


class TipsDialog(QDialog):
    """How the assistant reads a sentence, then a few short phrasing tips."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How to Talk to Me")
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 18)
        # The words scroll rather than squeeze: Qt caps a new window's height
        # to part of the screen, and word-wrapped labels in a layout taller
        # than that were CLIPPED mid-line (seen 2026-09-24 when the steps
        # joined the tips). Inside a scroll area each label gets its full
        # height for the width and the window opens as tall as fits.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        root = QVBoxLayout(body)
        root.setContentsMargins(18, 18, 18, 0)
        root.setSpacing(14)

        intro = QLabel("A few things that make voice commands land right the first time.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        root.addWidget(_section("How it works"))
        for n, (text, example) in enumerate(STEPS, start=1):
            # The step and its example read as one unit, so they sit closer
            # together than the dialog's own spacing.
            pair = QVBoxLayout()
            pair.setSpacing(2)
            step = QLabel(f"{n}. {text}")
            step.setObjectName("tipStep")
            step.setWordWrap(True)
            pair.addWidget(step)
            ex = QLabel(example)
            ex.setWordWrap(True)
            ex.setObjectName("muted")
            ex.setContentsMargins(14, 0, 0, 0)
            pair.addWidget(ex)
            root.addLayout(pair)

        root.addWidget(_section("Tips"))
        for headline, body in TIPS:
            pair = QVBoxLayout()
            pair.setSpacing(4)
            head = QLabel(headline)
            head.setObjectName("tipHeadline")
            head.setWordWrap(True)
            bold = QFont(head.font())
            bold.setBold(True)
            head.setFont(bold)
            pair.addWidget(head)
            text = QLabel(body)
            text.setWordWrap(True)
            text.setObjectName("muted")
            pair.addWidget(text)
            root.addLayout(pair)

        root.addStretch(1)
        done_btn = QPushButton("Done")
        done_btn.setObjectName("primary")
        done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        done_btn.clicked.connect(self.accept)
        buttons = QVBoxLayout()
        buttons.setContentsMargins(18, 0, 18, 0)
        buttons.addWidget(done_btn, alignment=Qt.AlignmentFlag.AlignRight)
        outer.addLayout(buttons)

        width = 480
        want = root.totalHeightForWidth(width) + done_btn.sizeHint().height() + 36
        screen = self.screen().availableGeometry().height() if self.screen() else want
        self.resize(width, min(want, int(screen * 0.85)))

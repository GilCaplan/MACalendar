""""How to talk to me" — a short, static tips screen (Mac).

Content lives in `assistant/tips.py`, tied to the engine version it was
verified against (see that module's docstring); this file is presentation
only. Same shape as `categories_dialog.CategoriesDialog`: plain QVBoxLayout,
a muted intro label, a "Done" button.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from assistant.tips import TIPS


class TipsDialog(QDialog):
    """Five short tips on getting the most out of voice commands."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How to Talk to Me")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        intro = QLabel("A few things that make voice commands land right the first time.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        for headline, body in TIPS:
            head = QLabel(headline)
            head.setObjectName("tipHeadline")
            head.setWordWrap(True)
            root.addWidget(head)
            text = QLabel(body)
            text.setWordWrap(True)
            text.setObjectName("muted")
            root.addWidget(text)

        root.addStretch(1)
        done_btn = QPushButton("Done")
        done_btn.setObjectName("primary")
        done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        done_btn.clicked.connect(self.accept)
        root.addWidget(done_btn, alignment=Qt.AlignmentFlag.AlignRight)

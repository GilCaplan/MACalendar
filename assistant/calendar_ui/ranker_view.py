"""Ranker — the Mac panel. Contract: `calendar_ui/feature_panel.py`."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from assistant.calendar_ui.feature_panel import FeaturePanel


class RankerView(FeaturePanel):
    feature_name = "ranker"

    def __init__(self, db=None, config=None, dark: bool = True) -> None:
        super().__init__()
        self._db = db
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self._empty = QLabel("Ranker has nothing to show yet.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

    def reload(self) -> None:
        """THE contract verb: re-read and redraw."""

    def apply_theme(self, dark: bool) -> None:
        pass

    def apply_ui_config(self, ui) -> None:
        pass

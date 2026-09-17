"""What the pipeline did, under the answer that came out of it.

Jude is five stages deep — router, retrieval, filter, synthesis, tools — and
one question takes 30-90 seconds, most of it invisible. The `steps` in `meta`
and the `timing` in `done` are the only account of where that time went, and a
cited answer whose retrieval you cannot inspect is a claim rather than a study
aid. So this is not a debug panel: it is the second half of the answer.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# Long enough to be recognisable, short enough that a router's four search
# queries do not push the duration off the right edge of the card.
_MAX_VALUE = 120


def fmt_ms(ms) -> str:
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return ""
    return f"{int(ms)}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


def _format_value(value) -> str:
    if isinstance(value, list):
        text = " › ".join(str(v) for v in value)
    elif isinstance(value, dict):
        text = ", ".join(f"{k}={v}" for k, v in value.items())
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = str(value)
    return text if len(text) <= _MAX_VALUE else text[:_MAX_VALUE - 1] + "…"


def format_result(result) -> str:
    """Every field the step reported, in the step's own words.

    Deliberately generic rather than a branch per module: Jude is its own
    repository and still being worked on, so a renderer that knows only about
    Router, Retrieval and Filter silently drops whatever stage it grows next.
    """
    if not isinstance(result, dict):
        return _format_value(result) if result else ""
    parts = [f"{key} {_format_value(value)}"
             for key, value in result.items() if value not in (None, "", [], {})]
    return "  ·  ".join(parts)


class TracePanel(QFrame):
    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("jude_trace")
        self.setStyleSheet(
            f"QFrame#jude_trace {{ background:{theme.bg2};"
            f" border:1px solid {theme.border}; border-radius:{theme.radius_md}px; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        self._head = QPushButton("🔍 Pipeline trace  ▴")
        self._head.setObjectName("flat")
        self._head.setCursor(Qt.CursorShape.PointingHandCursor)
        self._head.setStyleSheet(
            f"text-align:left; color:{theme.text2}; font-size:11px; padding:2px 0;")
        self._head.clicked.connect(self._toggle)
        outer.addWidget(self._head)

        self._body = QWidget(self)
        self._rows = QVBoxLayout(self._body)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        outer.addWidget(self._body)

    def _toggle(self) -> None:
        shown = not self._body.isVisible()
        self._body.setVisible(shown)
        self._head.setText("🔍 Pipeline trace  " + ("▴" if shown else "▾"))

    # ------------------------------------------------------------- content

    def _row(self, module: str, duration, detail: str, colour: "str | None" = None) -> None:
        theme = self._theme
        row = QWidget(self._body)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        name = QLabel(module)
        name.setMinimumWidth(78)
        name.setStyleSheet(
            f"color:{colour or theme.text}; font-size:10.5px; font-weight:700;")
        lay.addWidget(name)

        ms = fmt_ms(duration)
        if ms:
            badge = QLabel(ms)
            badge.setStyleSheet(
                f"color:{theme.text2}; font-size:10px; border:1px solid {theme.border};"
                f" border-radius:{theme.radius_sm}px; padding:0px 4px;")
            lay.addWidget(badge)

        text = QLabel(detail)
        text.setWordWrap(True)
        text.setStyleSheet(f"color:{theme.text2}; font-size:10.5px;")
        lay.addWidget(text, 1)
        self._rows.addWidget(row)

    def set_steps(self, steps: list) -> None:
        for step in steps or []:
            if not isinstance(step, dict):
                continue
            self._row(str(step.get("module") or "step"),
                      step.get("duration_ms"),
                      format_result(step.get("result")))

    def add_tool_call(self, event: dict) -> None:
        """A tool that fired during synthesis — Jude reaching for a source it
        did not retrieve up front. It arrives mid-stream, after the steps."""
        args = event.get("args") or {}
        lead = args.get("query") or args.get("ref") or args.get("text") or ""
        if args.get("category"):
            lead = f"{lead} [{args['category']}]".strip()
        summary = event.get("result_summary") or ""
        detail = f"{lead} → {summary}".strip(" →")
        self._row(f"🔧 {event.get('tool') or 'tool'}", None, detail,
                  colour=self._theme.accent)

    def set_timing(self, timing: dict) -> None:
        timing = timing or {}
        for key, label in (("route_ms", "Route"), ("retrieve_ms", "Retrieve"),
                           ("filter_ms", "Filter")):
            if timing.get(key) is not None:
                self._row(label, timing[key], "")
        if timing.get("synth_total_ms") is not None:
            first = timing.get("synth_first_token_ms")
            detail = f"first token {fmt_ms(first)}" if first is not None else ""
            self._row("Synthesis", timing["synth_total_ms"], detail)
        if timing.get("total_ms") is not None:
            self._row("Total", timing["total_ms"], "", colour=self._theme.accent)

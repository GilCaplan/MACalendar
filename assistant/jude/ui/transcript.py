"""The conversation itself — questions, streamed answers, and the cards
an answer drags along with it.

**The tokens are batched here, and that is the point of this module.** The
previous Mac app inserted every token into a `QTextBrowser` through a cursor,
so a 2,000-token answer asked Qt for 2,000 full document relayouts and the
window crawled while the model was still mid-sentence. Tokens now land in a
plain string; a single `QTimer` on this widget repaints the answer that is
growing, at most once every `REPAINT_MS`, and the markdown is rendered once per
repaint rather than once per token. Nothing else in here may write to the
answer label.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from assistant.jude.ui import markdown as _md
from assistant.jude.ui.sources import SourcesView
from assistant.jude.ui.trace import TracePanel

# Fast enough that the answer reads as live, slow enough that a whole
# paragraph's worth of tokens costs one relayout instead of forty.
REPAINT_MS = 70

# The scrollbar is "at the bottom" within this many pixels. Anything stricter
# and one pixel of drift stops the answer following itself down the page;
# anything looser and a reader scrolled up to re-read a source gets yanked back.
STICK_PX = 80

EXAMPLES = [
    ("Halacha", "Is it permitted to carry an umbrella on Shabbat?"),
    ("Narrative", "What happened at Mount Sinai when the Torah was given?"),
    ("Talmudic Debate", "What is the debate between Beit Hillel and Beit Shammai?"),
    ("Kabbalah", "What does Kabbalah teach about the nature of the soul?"),
]


def _escape(text) -> str:
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


class _Card(QFrame):
    """A bordered surface — every block in the transcript is one of these."""

    def __init__(self, theme, parent=None, accent: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("jude_card")
        border = theme.accent if accent else theme.border
        self.setStyleSheet(
            f"QFrame#jude_card {{ background:{theme.surface}; border:1px solid {border};"
            f" border-radius:{theme.radius_lg}px; }}")


class UserMessage(_Card):
    def __init__(self, text: str, theme, parent=None) -> None:
        super().__init__(theme, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        label = QLabel("👤  " + _escape(text))
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(f"color:{theme.text}; font-size:13px;")
        lay.addWidget(label)


class PendingRow(_Card):
    """The only thing on screen for up to ninety seconds.

    `stage` is Jude's sole progress signal, so this row exists to show it. A
    surface that quietly waits for the first token is indistinguishable from
    one that has hung, which is how the wait gets reported as a crash.
    """

    def __init__(self, theme, parent=None) -> None:
        super().__init__(theme, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        self._label = QLabel("✡  Thinking…")
        self._label.setStyleSheet(f"color:{theme.text2}; font-size:12px;")
        lay.addWidget(self._label)
        lay.addStretch(1)

    def set_stage(self, name: str) -> None:
        self._label.setText("✡  " + (name or "Thinking…"))


class AnswerMessage(_Card):
    def __init__(self, theme, parent=None) -> None:
        super().__init__(theme, parent)
        self._theme = theme
        self._raw = ""
        self._painted = ""
        self._streaming = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(6)
        self._lay = lay

        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setOpenExternalLinks(True)
        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._body.setStyleSheet(f"color:{theme.text}; font-size:13px;")
        lay.addWidget(self._body)

        self._sources: "SourcesView | None" = None
        self._trace: "TracePanel | None" = None
        self._copy_row: "QWidget | None" = None

    # The only two methods that touch the label, and neither is called per token.
    def append(self, text: str) -> None:
        self._raw += text

    def repaint_if_dirty(self) -> bool:
        if self._raw == self._painted:
            return False
        self._painted = self._raw
        cursor = "<span style='color:%s;'>▊</span>" % self._theme.text2
        self._body.setText(_md.render(self._raw, self._theme)
                           + (cursor if self._streaming else ""))
        return True

    @property
    def text(self) -> str:
        return self._raw

    def set_text(self, text: str) -> None:
        self._raw = text
        self._painted = ""
        self.repaint_if_dirty()

    def trace_panel(self) -> TracePanel:
        if self._trace is None:
            self._trace = TracePanel(self._theme, self)
            self._lay.addWidget(self._trace)
        return self._trace

    def set_sources(self, sources: list) -> None:
        if not sources or self._sources is not None:
            return
        self._sources = SourcesView(sources, self._theme, self)
        # Above the trace: the sources are part of the answer, the trace is the
        # account of how it was built.
        index = self._lay.indexOf(self._trace) if self._trace is not None else -1
        if index < 0:
            self._lay.addWidget(self._sources)
        else:
            self._lay.insertWidget(index, self._sources)

    def finish(self) -> None:
        self._streaming = False
        self._painted = ""            # force one last paint, without the cursor
        self.repaint_if_dirty()
        if self._copy_row is not None:
            return
        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        button = QPushButton("📋 Copy answer")
        button.setObjectName("flat")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(f"color:{self._theme.text2}; font-size:11px;")
        # The markdown, not the rendered HTML: an answer is pasted into notes
        # far more often than into something that renders rich text.
        button.clicked.connect(lambda: self._copy(button))
        lay.addWidget(button)
        self._copy_row = row
        self._lay.addWidget(row)

    def _copy(self, button: QPushButton) -> None:
        QApplication.clipboard().setText(self._raw)
        button.setText("✓ Copied")
        # PARENTED to the button rather than a bare singleShot: opening
        # another conversation within those two seconds deletes this message,
        # and a free-standing timer then fires into a freed C++ object and
        # aborts the interpreter. A child timer dies with its parent.
        reset = QTimer(button)
        reset.setSingleShot(True)
        reset.timeout.connect(lambda: button.setText("📋 Copy answer"))
        reset.start(2000)


class ClarificationCard(_Card):
    """Jude asking which question it should answer.

    The options are buttons because the alternative — printing them and hoping
    the reader retypes one — loses the prompt Jude wrote for each option, which
    is the part that makes the retry better than the first attempt.
    """

    chose = pyqtSignal(str)
    skipped = pyqtSignal()

    def __init__(self, event: dict, theme, parent=None) -> None:
        super().__init__(theme, parent, accent=True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)

        question = QLabel("🤔  " + _escape(event.get("question")
                                           or "Did you mean one of these?"))
        question.setWordWrap(True)
        question.setStyleSheet(f"color:{theme.text}; font-size:13px; font-weight:600;")
        lay.addWidget(question)

        for option in event.get("options") or []:
            # Jude sends {label, prompt}; older builds send a bare string, and
            # a client that crashes on the simpler shape is the client's bug.
            if isinstance(option, dict):
                label = option.get("label") or option.get("prompt") or ""
                prompt = option.get("prompt") or label
            else:
                label = prompt = str(option)
            if not label:
                continue
            button = QPushButton(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet("text-align:left;")
            button.clicked.connect(lambda _checked=False, p=prompt: self.chose.emit(p))
            lay.addWidget(button)

        skip = QPushButton("Continue with my original question →")
        skip.setObjectName("flat")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.setStyleSheet(f"color:{theme.text2}; font-size:11.5px; text-align:left;")
        skip.clicked.connect(lambda: self.skipped.emit())
        lay.addWidget(skip)


class PivotCard(_Card):
    """"Switching from X to Y?" — asked while the answer keeps arriving.

    Non-blocking on purpose: Jude has already decided to answer, and the pivot
    only settles what this conversation is *called*. A modal here would stop a
    stream that does not need stopping.
    """

    confirmed = pyqtSignal(str)
    dismissed = pyqtSignal()

    def __init__(self, event: dict, theme, parent=None) -> None:
        super().__init__(theme, parent, accent=True)
        previous = event.get("previous_topic") or "this topic"
        candidate = event.get("candidate_topic") or "a new topic"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)

        label = QLabel(f"↻  Switching from <b>{_escape(previous)}</b> to "
                       f"<b>{_escape(candidate)}</b>?")
        label.setWordWrap(True)
        label.setStyleSheet(f"color:{theme.text}; font-size:12.5px;")
        lay.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(6)
        yes = QPushButton("Update the topic")
        yes.setObjectName("primary")
        yes.setCursor(Qt.CursorShape.PointingHandCursor)
        no = QPushButton(f"Stay on {previous}")
        no.setObjectName("flat")
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet(f"color:{theme.text2};")

        def confirm() -> None:
            yes.setEnabled(False)
            no.hide()
            yes.setText("Topic updated")
            self.confirmed.emit(candidate)

        def dismiss() -> None:
            no.setEnabled(False)
            yes.hide()
            no.setText("Kept")
            self.dismissed.emit()

        yes.clicked.connect(confirm)
        no.clicked.connect(dismiss)
        row.addWidget(yes)
        row.addWidget(no)
        row.addStretch(1)
        lay.addLayout(row)


class ErrorCard(_Card):
    def __init__(self, message: str, theme, parent=None) -> None:
        super().__init__(theme, parent)
        self.setStyleSheet(
            f"QFrame#jude_card {{ background:{theme.surface};"
            f" border:1px solid {theme.destructive};"
            f" border-radius:{theme.radius_lg}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        label = QLabel("⚠  " + _escape(message))
        label.setWordWrap(True)
        label.setStyleSheet(f"color:{theme.destructive}; font-size:12.5px;")
        lay.addWidget(label)


class EmptyState(QWidget):
    example_chosen = pyqtSignal(str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 40, 24, 24)
        lay.setSpacing(8)

        seal = QLabel("📜")
        seal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seal.setStyleSheet("font-size:34px;")
        lay.addWidget(seal)

        headline = QLabel("What would you like to learn?")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setStyleSheet(f"color:{theme.text}; font-size:17px; font-weight:700;")
        lay.addWidget(headline)

        sub = QLabel("Torah, Talmud, Midrash, Halacha and Kabbalah — every answer "
                     "cited, every source linked back to Sefaria.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{theme.text2}; font-size:12px;")
        lay.addWidget(sub)
        lay.addSpacing(10)

        for category, text in EXAMPLES:
            card = QPushButton(f"{category}\n{text}")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(
                f"text-align:left; padding:8px 12px; color:{theme.text2};")
            card.clicked.connect(
                lambda _checked=False, t=text: self.example_chosen.emit(t))
            lay.addWidget(card)


class Transcript(QScrollArea):
    """The message column, and the one timer that repaints a live answer."""

    example_chosen = pyqtSignal(str)
    clarification_chosen = pyqtSignal(str)       # a rewritten prompt to ask
    clarification_skipped = pyqtSignal(str)      # the original prompt, unchanged
    topic_confirmed = pyqtSignal(str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._holder = QWidget()
        self._lay = QVBoxLayout(self._holder)
        self._lay.setContentsMargins(16, 14, 16, 14)
        self._lay.setSpacing(10)
        self._lay.addStretch(1)
        self.setWidget(self._holder)

        self._pending: "PendingRow | None" = None
        self._answer: "AnswerMessage | None" = None

        # ONE timer for the whole transcript, not one per answer: only the
        # newest answer can be growing, and a timer per message would keep
        # firing for every finished one still on screen.
        self._repaint = QTimer(self)
        self._repaint.setInterval(REPAINT_MS)
        self._repaint.timeout.connect(self._flush)

        # Scrolling is deferred through a timer owned by this widget, for the
        # same reason the copy button's reset is: a queued lambda that outlives
        # the widget it touches takes the process down with it.
        self._scroller = QTimer(self)
        self._scroller.setSingleShot(True)
        self._scroller.timeout.connect(self._jump_to_bottom)

    # ------------------------------------------------------------ plumbing

    def _add(self, widget: QWidget) -> None:
        stick = self._at_bottom()
        self._lay.insertWidget(self._lay.count() - 1, widget)
        if stick:
            self._scroll_to_bottom()

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - STICK_PX

    def _scroll_to_bottom(self) -> None:
        # Queued: the layout has not been recomputed yet when a widget is
        # inserted, so maximum() is still the old one at this instant.
        self._scroller.start(0)

    def _jump_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _flush(self) -> None:
        if self._answer is None:
            self._repaint.stop()
            return
        stick = self._at_bottom()
        if self._answer.repaint_if_dirty() and stick:
            self._scroll_to_bottom()

    # ------------------------------------------------------------- content

    def clear(self) -> None:
        self._repaint.stop()
        self._pending = None
        self._answer = None
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def show_empty_state(self) -> None:
        self.clear()
        empty = EmptyState(self._theme, self._holder)
        empty.example_chosen.connect(self.example_chosen)
        self._add(empty)

    def add_user(self, text: str) -> None:
        self._drop_empty_state()
        self._add(UserMessage(text, self._theme, self._holder))

    def _drop_empty_state(self) -> None:
        """The examples are an invitation, not history — once a question has
        been asked they are four buttons wasting the top of the scroll."""
        for index in range(self._lay.count()):
            widget = self._lay.itemAt(index).widget()
            if isinstance(widget, EmptyState):
                self._lay.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()
                return

    def start_pending(self) -> None:
        self.clear_pending()
        self._pending = PendingRow(self._theme, self._holder)
        self._add(self._pending)

    def set_stage(self, name: str) -> None:
        if self._pending is not None:
            self._pending.set_stage(name)

    def clear_pending(self) -> None:
        if self._pending is None:
            return
        self._pending.setParent(None)
        self._pending.deleteLater()
        self._pending = None

    def append_token(self, text: str) -> None:
        if self._answer is None:
            self.clear_pending()
            self._answer = AnswerMessage(self._theme, self._holder)
            self._add(self._answer)
            self._repaint.start()
        self._answer.append(text)

    def answer(self) -> "AnswerMessage | None":
        return self._answer

    def ensure_answer(self) -> AnswerMessage:
        """An answer row even if no token ever arrived — `done` with nothing
        streamed still has sources and a trace worth showing."""
        if self._answer is None:
            self.append_token("")
        return self._answer

    def add_tool_call(self, event: dict) -> None:
        if self._answer is not None:
            self._answer.trace_panel().add_tool_call(event)
        elif self._pending is not None:
            self._pending.set_stage(f"🔧 {event.get('tool') or 'tool'}")

    def finish_answer(self, sources: list, steps: list, tool_calls: list,
                      timing: dict, fallback: str = "") -> None:
        self._repaint.stop()
        self.clear_pending()
        answer = self.ensure_answer()
        if not answer.text and fallback:
            answer.set_text(fallback)
        if steps:
            panel = answer.trace_panel()
            panel.set_steps(steps)
            for call in tool_calls or []:
                panel.add_tool_call(call)
        if timing:
            answer.trace_panel().set_timing(timing)
        answer.set_sources(sources or [])
        answer.finish()
        self._answer = None
        self._repaint.stop()          # after ensure_answer() may have restarted it
        self._scroll_to_bottom()

    def add_sources_only(self, query: str, sources: list, steps: list) -> None:
        """Sources mode answers with a shelf rather than a paragraph — no
        synthesis runs, so there is nothing to stream and nothing to copy."""
        self.clear_pending()
        card = _Card(self._theme, self._holder)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(6)
        header = QLabel(f"📚  {len(sources or [])} sources — {_escape(query[:70])}")
        header.setWordWrap(True)
        header.setStyleSheet(f"color:{self._theme.text}; font-size:12.5px; font-weight:600;")
        lay.addWidget(header)
        lay.addWidget(SourcesView(sources or [], self._theme, card))
        if steps:
            panel = TracePanel(self._theme, card)
            panel.set_steps(steps)
            lay.addWidget(panel)
        self._add(card)

    def add_history(self, role: str, content: str, sources: list) -> None:
        if role == "user":
            self.add_user(content)
            return
        message = AnswerMessage(self._theme, self._holder)
        message.set_text(content or "")
        message.set_sources(sources or [])
        message.finish()
        self._add(message)

    def add_error(self, message: str) -> None:
        self._repaint.stop()
        self.clear_pending()
        if self._answer is not None:
            # Tokens already arrived: keep them and say what went wrong after
            # them, rather than replacing a half-answer with an error.
            self._answer.append("\n\n⚠ " + message)
            self._answer.finish()
            self._answer = None
            return
        self._add(ErrorCard(message, self._theme, self._holder))

    def add_clarification(self, event: dict, original_prompt: str) -> None:
        self.clear_pending()
        card = ClarificationCard(event, self._theme, self._holder)
        card.chose.connect(self.clarification_chosen)
        card.skipped.connect(
            lambda p=original_prompt: self.clarification_skipped.emit(p))
        self._add(card)

    def add_pivot(self, event: dict) -> None:
        card = PivotCard(event, self._theme, self._holder)
        card.confirmed.connect(self.topic_confirmed)
        self._add(card)

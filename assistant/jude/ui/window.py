"""The Jude window: sidebar, topbar, transcript, composer.

Its own window rather than a tab in the calendar, for the reason the thinking
HUD is its own app: studying a sugya is not something you do inside a calendar,
and this window should outlive the calendar's.

Everything it knows about Jude arrives as an event on one NDJSON stream, and
every HTTP call it makes goes to the MACalendar API — see `client.py` for why
that matters even though Jude is on this same machine.
"""

from __future__ import annotations

import logging
from html import escape as _escape

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget,
)

from assistant.calendar_ui import styles as _styles
from assistant.jude.ui import client
from assistant.jude.ui.composer import Composer
from assistant.jude.ui.sidebar import Sidebar
from assistant.jude.ui.stream import ChatStream
from assistant.jude.ui.theme import Theme
from assistant.jude.ui.transcript import Transcript

logger = logging.getLogger(__name__)

# `ready` is not `running`: an integration that autostarts is ready before it
# is up, and it can stop being ready when config.yaml changes under it. Cheap
# enough on loopback to simply keep asking.
STATUS_POLL_MS = 15000

NO_ANSWER = ("⚠ No response was generated. Try rephrasing the question, or "
             "raise the number of sources.")


class JudeWindow(QMainWindow):
    def __init__(self, config=None) -> None:
        super().__init__()
        self._config = config
        self._dark = (getattr(config, "theme", "dark") == "dark")
        self._theme = Theme(self._dark)
        self._chat_id: "str | None" = None
        self._prompt = ""                  # the question currently being answered
        self._meta: dict = {}
        self._tool_calls: list = []
        self._busy = False
        self._ready = True
        self._answered_as_sources = False
        self._clarified = False

        self.setWindowTitle("Jude — Judaic study")
        self.resize(1080, 800)
        self.setMinimumSize(760, 520)
        self.setStyleSheet(_styles.get_app_style(self._dark))

        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self._sidebar = Sidebar(self._theme, central)
        self._sidebar.new_chat.connect(self.new_chat)
        self._sidebar.mode_changed.connect(self._on_mode_changed)
        self._sidebar.chat_opened.connect(self._open_chat)
        self._sidebar.chat_deleted.connect(self._delete_chat)
        root.addWidget(self._sidebar)

        main = QWidget(central)
        main_lay = QVBoxLayout(main)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)
        root.addWidget(main, 1)

        main_lay.addWidget(self._build_topbar(main))

        self._transcript = Transcript(self._theme, main)
        self._transcript.example_chosen.connect(self._on_example)
        self._transcript.clarification_chosen.connect(self._on_clarification_chosen)
        self._transcript.clarification_skipped.connect(self._on_clarification_skipped)
        self._transcript.topic_confirmed.connect(self._confirm_topic)
        main_lay.addWidget(self._transcript, 1)

        # The stage line. It is the ONLY thing the user has for up to ninety
        # seconds, so it sits between the answer and the entry where the eye
        # already is, not in a status bar at the bottom of the screen.
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._status.setOpenExternalLinks(True)
        self._status.setStyleSheet(
            f"color:{self._theme.text2}; font-size:11px; padding:4px 16px 0;")
        main_lay.addWidget(self._status)

        self._composer = Composer(self._theme, main)
        self._composer.submitted.connect(self.ask)
        main_lay.addWidget(self._composer)

        self._stream = ChatStream(self)
        self._stream.stage.connect(self._on_stage)
        self._stream.meta.connect(self._on_meta)
        self._stream.token.connect(self._transcript.append_token)
        self._stream.tool_call.connect(self._on_tool_call)
        self._stream.clarification.connect(self._on_clarification)
        self._stream.topic_pivot.connect(self._transcript.add_pivot)
        self._stream.done.connect(self._on_done)
        self._stream.failed.connect(self._on_failed)
        self._stream.finished.connect(self._on_finished)

        QShortcut(QKeySequence(QKeySequence.StandardKey.New), self,
                  activated=self.new_chat)

        self._transcript.show_empty_state()
        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_POLL_MS)
        self._poll.timeout.connect(self._refresh_status)
        self._poll.start()
        self._refresh_status()
        self._reload_chats()

    def _build_topbar(self, parent: QWidget) -> QWidget:
        bar = QWidget(parent)
        bar.setStyleSheet(
            f"background:{self._theme.bg2}; border-bottom:1px solid {self._theme.border};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)

        self._title = QLabel("Ask Jude")
        self._title.setStyleSheet(
            f"color:{self._theme.text}; font-size:14px; font-weight:700;")
        lay.addWidget(self._title)

        self._badge = QLabel("")
        self._badge.setStyleSheet(
            f"color:{self._theme.accent}; font-size:11px; font-weight:600;"
            f" border:1px solid {self._theme.accent};"
            f" border-radius:{self._theme.radius_sm}px; padding:1px 7px;")
        self._badge.hide()
        lay.addWidget(self._badge)
        lay.addStretch(1)
        return bar

    # ------------------------------------------------------------- status

    def _refresh_status(self) -> None:
        if self._busy:
            return              # the stage line is saying something more useful
        client.call_async(self, self._config, "GET", "/jude/status",
                          self._on_status, self._on_status_error, timeout=6)

    def _on_status(self, status) -> None:
        status = status if isinstance(status, dict) else {}
        self._ready = bool(status.get("ready"))
        self._composer.set_enabled(self._ready)
        if not self._ready:
            # The reason, plus the repository as a LINK.
            #
            # `reason` is prose and `repo` is structured — the sentence no
            # longer contains the URL, because when both carried it every
            # client printed it twice. So the sentence says what to do and the
            # link is the thing you can actually click.
            reason = status.get("reason") or "Jude cannot answer right now."
            repo = (status.get("repo") or "").strip()
            if repo:
                reason += f'<br><a href="{_escape(repo)}">{_escape(repo)}</a>'
            self._status.setText(reason)
            self._sidebar.set_footer("")
            return
        self._status.setText("")
        model = status.get("model") or "local model"
        gate = "gated" if status.get("gated") else "direct"
        priority = status.get("priority") or ""
        self._sidebar.set_footer(f"● {model} · {gate} · {priority}".rstrip(" ·"))

    def _on_status_error(self, message: str) -> None:
        # /jude/status never errors when the API is up, so a failure here is
        # the API being down — which the reason sentence cannot describe.
        self._ready = False
        self._composer.set_enabled(False)
        self._status.setText(message)

    # --------------------------------------------------------------- chats

    def _reload_chats(self) -> None:
        client.call_async(
            self, self._config, "GET", "/jude/chats",
            lambda chats: self._sidebar.set_chats(
                chats if isinstance(chats, list) else [], self._chat_id),
            lambda message: logger.info("chat list unavailable: %s", message))

    def new_chat(self) -> None:
        self._stream.abort()
        self._chat_id = None
        self._meta = {}
        self._title.setText("Ask Jude")
        self._badge.hide()
        self._transcript.show_empty_state()
        self._sidebar.set_active(None)
        self._set_busy(False)
        self._composer.focus_entry()

    def _open_chat(self, chat_id: str, title: str) -> None:
        self._stream.abort()          # its tokens must not land in this history
        self._chat_id = chat_id
        self._title.setText(title or "Conversation")
        self._badge.hide()
        self._sidebar.set_active(chat_id)
        self._transcript.clear()
        self._set_busy(False)
        client.call_async(self, self._config, "GET", f"/jude/chats/{chat_id}/history",
                          self._render_history, self._transcript.add_error)

    def _render_history(self, messages) -> None:
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict):
                continue
            self._transcript.add_history(
                message.get("role") or "assistant",
                message.get("content") or "",
                message.get("sources") or [])

    def _delete_chat(self, chat_id: str) -> None:
        def done(_result) -> None:
            if chat_id == self._chat_id:
                self.new_chat()
            self._reload_chats()

        client.call_async(self, self._config, "DELETE", f"/jude/chats/{chat_id}",
                          done, self._transcript.add_error)

    def _confirm_topic(self, topic: str) -> None:
        if not self._chat_id:
            return                    # nothing to relabel yet
        client.call_async(self, self._config, "PUT",
                          f"/jude/chats/{self._chat_id}/topic",
                          lambda _r: None,
                          lambda message: logger.info("topic pivot: %s", message),
                          body={"topic": topic})

    # ----------------------------------------------------------- asking

    def ask(self, prompt: str, skip_clarification: bool = False) -> None:
        prompt = (prompt or "").strip()
        if not prompt or self._busy or not self._ready:
            return
        self._prompt = prompt
        self._meta = {}
        self._tool_calls = []
        self._answered_as_sources = False
        self._clarified = False
        self._transcript.add_user(prompt)
        self._transcript.start_pending()
        self._set_busy(True)
        self._status.setText("Thinking…")
        self._stream.ask(self._config, prompt=prompt, chat_id=self._chat_id,
                         mode=self._sidebar.mode, lang=self._composer.lang,
                         top_k=self._composer.top_k,
                         skip_clarification=skip_clarification)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._composer.set_busy(busy)
        # The stage line is cleared when the question is over — unless it is
        # carrying the not-ready reason, which is not about this question.
        if not busy and self._ready:
            self._status.setText("")

    def _on_example(self, text: str) -> None:
        self._composer.set_text(text)
        self._composer.focus_entry()

    def _on_mode_changed(self, mode: str) -> None:
        self._composer.set_top_k_visible(mode != "sources")

    def _on_stage(self, name: str) -> None:
        self._status.setText(name)
        self._transcript.set_stage(name)

    def _on_meta(self, meta: dict) -> None:
        self._meta = meta
        new_chat = not self._chat_id and meta.get("chat_id")
        if meta.get("chat_id"):
            self._chat_id = meta["chat_id"]
        if new_chat:
            self._title.setText(self._prompt[:55])
            self._reload_chats()
        self._apply_badge(meta)
        if meta.get("mode") == "sources":
            # Sources mode never synthesises, so the answer IS the shelf and
            # there is no stream behind it to wait for.
            self._answered_as_sources = True
            self._transcript.add_sources_only(
                self._prompt, meta.get("sources") or [], meta.get("steps") or [])

    def _apply_badge(self, meta: dict) -> None:
        label = meta.get("halachic_label")
        if meta.get("halachic_topic") and label:
            seder = meta.get("halachic_seder")
            self._badge.setText(f"📚 {label}" + (f" · Seder {seder}" if seder else ""))
        elif meta.get("mode") == "study" and meta.get("study_pool_size"):
            self._badge.setText(f"📖 Study · {meta['study_pool_size']} sources loaded")
        elif meta.get("mode") == "sources":
            self._badge.setText("📋 Sources Only")
        else:
            self._badge.hide()
            return
        self._badge.show()

    def _on_tool_call(self, event: dict) -> None:
        self._tool_calls.append(event)
        self._transcript.add_tool_call(event)
        new_sources = event.get("new_sources") or []
        if new_sources:
            # Merged into meta so the finished answer cites what the tool
            # fetched mid-synthesis, not only what retrieval found up front.
            self._meta["sources"] = (self._meta.get("sources") or []) + new_sources

    def _on_clarification(self, event: dict) -> None:
        self._clarified = True
        if event.get("chat_id") and not self._chat_id:
            self._chat_id = event["chat_id"]
            self._title.setText(self._prompt[:55])
            self._reload_chats()
        self._transcript.add_clarification(event, self._prompt)

    def _on_clarification_chosen(self, prompt: str) -> None:
        self.ask(prompt)

    def _on_clarification_skipped(self, prompt: str) -> None:
        self.ask(prompt, skip_clarification=True)

    def _on_done(self, timing: dict) -> None:
        if self._answered_as_sources:
            return
        if self._clarified and not (self._transcript.answer()
                                    and self._transcript.answer().text):
            return               # the question came back as a question
        self._transcript.finish_answer(
            self._meta.get("sources") or [], self._meta.get("steps") or [],
            self._tool_calls, timing, fallback=NO_ANSWER)

    def _on_failed(self, message: str) -> None:
        self._transcript.add_error(message)

    def _on_finished(self) -> None:
        # A dropped connection ends the stream without `done`; whatever text
        # arrived is still an answer and still deserves its sources.
        answer = self._transcript.answer()
        if answer is not None and not self._answered_as_sources:
            self._transcript.finish_answer(
                self._meta.get("sources") or [], self._meta.get("steps") or [],
                self._tool_calls, {}, fallback=NO_ANSWER)
        self._transcript.clear_pending()
        self._set_busy(False)
        self._refresh_status()

"""One question's worth of NDJSON, marshalled onto the GUI thread.

`POST /jude/chat` answers `application/x-ndjson`: one JSON object per line,
typed by `type` — `stage`, `meta`, `token`, `tool_call`, `clarification`,
`topic_pivot`, `done`, `error`. Each becomes a signal, and a signal is the only
way anything here reaches a widget.

**Every answer carries a generation.** Starting a new question, opening another
chat or hitting New chat while an answer is still streaming used to leave the
old request running — it cannot be cancelled mid-read — and its tokens then
landed in whatever bubble was on screen by then. The worker checks the
generation it was started with before every emit, so an abandoned stream drains
into nothing instead of into somebody else's answer.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal

from assistant.jude.ui import client

logger = logging.getLogger(__name__)


class ChatStream(QObject):
    stage = pyqtSignal(str)
    meta = pyqtSignal(dict)
    token = pyqtSignal(str)
    tool_call = pyqtSignal(dict)
    clarification = pyqtSignal(dict)
    topic_pivot = pyqtSignal(dict)
    done = pyqtSignal(dict)            # the `timing` block
    failed = pyqtSignal(str)           # a sentence for a person
    finished = pyqtSignal()            # always last, success or not

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._generation = 0

    def ask(self, config, *, prompt: str, chat_id: "str | None", mode: str,
            lang: str, top_k: int, skip_clarification: bool = False) -> None:
        self._generation += 1
        generation = self._generation
        body = {
            "prompt": prompt,
            "chat_id": chat_id,
            "mode": mode,
            "lang": lang,
            "top_k": int(top_k),
            "skip_clarification": bool(skip_clarification),
        }
        threading.Thread(target=self._work, args=(config, body, generation),
                         daemon=True, name="jude-ask").start()

    def abort(self) -> None:
        """Stop applying whatever is still arriving. The request itself keeps
        running to completion on its own thread — Jude has already done the
        work and there is nothing to gain by killing the socket."""
        self._generation += 1

    def _work(self, config, body: dict, generation: int) -> None:
        def live() -> bool:
            return generation == self._generation

        try:
            request = client.build_request(config, "POST", "/jude/chat", body)
            with urllib.request.urlopen(request, timeout=client.STREAM_TIMEOUT) as response:
                for raw in response:
                    if not live():
                        return
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:     # a half-written line is not fatal
                        continue
                    self._dispatch(event)
        except Exception as exc:           # noqa: BLE001 - shown, never raised
            logger.info("jude stream failed: %s", exc)
            if live():
                self.failed.emit(client.explain(config, exc))
        finally:
            if live():
                self.finished.emit()

    def _dispatch(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "token":
            self.token.emit(event.get("text") or "")
        elif kind == "stage":
            self.stage.emit(event.get("name") or "")
        elif kind == "meta":
            self.meta.emit(event)
        elif kind == "tool_call":
            self.tool_call.emit(event)
        elif kind == "clarification":
            self.clarification.emit(event)
        elif kind == "topic_pivot":
            # Deliberately just a signal: the pivot is a question about the
            # conversation's label, and the answer keeps streaming behind it.
            self.topic_pivot.emit(event)
        elif kind == "done":
            self.done.emit(event.get("timing") or {})
        elif kind == "error":
            self.failed.emit(event.get("message") or "Something went wrong.")

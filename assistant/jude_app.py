"""Jude — the Judaic study assistant, as its own Mac app.

    python -m assistant.jude_app

A fourth window beside the calendar, the thinking HUD and the API server, and
separate for the same reason the HUD is: studying a sugya is not a thing you do
inside a calendar. It is started by `Launch Calendar.command` when
`jude.enabled` is on, and the calendar's toolbar has a 📖 button that brings it
up (that button starts it if it is not already running, the way the review
panel's tray item reopens the card).

**It goes through the assistant's API, not through Jude.** Every question is a
POST to `127.0.0.1:8080/jude/chat` — the same endpoint, same NDJSON, same
answers the iPhone gets. The alternative, talking to Jude's FastAPI directly
because it happens to be on the same machine, would be a second client of a
second protocol, and the two would drift the week after they were written. The
whole point of the bridge is that there is one way in.

Jude's own repository is NOT vendored here — see `DOCUMENTATION/JUDE.md`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from assistant.calendar_ui import styles as _styles

logger = logging.getLogger(__name__)


def _api_base(config) -> str:
    port = os.environ.get("MACALENDAR_API_PORT") or str(
        getattr(getattr(config, "api", None), "port", 8080))
    return f"http://127.0.0.1:{port}"


def _api_key(config) -> "str | None":
    return getattr(getattr(config, "api", None), "key", None)


class _Stream(QObject):
    """One question's worth of NDJSON, marshalled onto the GUI thread.

    The request runs on a worker thread — a streamed answer takes tens of
    seconds on a local model, and a frozen window for that long reads as a
    crash. Qt signals are the only safe way back.
    """

    stage = pyqtSignal(str)
    token = pyqtSignal(str)
    meta = pyqtSignal(dict)
    finished = pyqtSignal(str)          # "" on success, else the message to show

    def ask(self, config, prompt: str, chat_id: "str | None", mode: str) -> None:
        threading.Thread(target=self._work, args=(config, prompt, chat_id, mode),
                         daemon=True, name="jude-ask").start()

    def _work(self, config, prompt: str, chat_id: "str | None", mode: str) -> None:
        import urllib.error
        import urllib.request

        body = {"prompt": prompt, "mode": mode}
        if chat_id:
            body["chat_id"] = chat_id
        req = urllib.request.Request(
            _api_base(config) + "/jude/chat", method="POST",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        key = _api_key(config)
        if key:
            req.add_header("X-API-Key", key)
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except ValueError:
                        continue
                    kind = evt.get("type")
                    if kind == "token":
                        self.token.emit(evt.get("text") or "")
                    elif kind == "stage":
                        self.stage.emit(evt.get("name") or "")
                    elif kind == "meta":
                        self.meta.emit(evt)
                    elif kind == "clarification":
                        self.token.emit("\n\n**" + (evt.get("question") or "") + "**\n")
                        for opt in evt.get("options") or []:
                            self.token.emit(f"\n• {opt}")
                    elif kind == "error":
                        self.finished.emit(evt.get("message") or "Something went wrong.")
                        return
            self.finished.emit("")
        except urllib.error.HTTPError as e:
            # The 503 the API answers when Jude is off or not installed carries
            # a sentence written for a person; show that, not "HTTP 503".
            detail = ""
            try:
                detail = (json.loads(e.read().decode("utf-8")) or {}).get("error", "")
            except Exception:
                pass
            self.finished.emit(detail or f"The assistant answered {e.code}.")
        except Exception as e:           # noqa: BLE001
            self.finished.emit(
                f"Couldn't reach the assistant on {_api_base(config)} — is it running? ({e})")


class JudeWindow(QMainWindow):
    # `_refresh_status` runs its request on a worker thread (an unreachable API
    # must not freeze the window), and a widget may only be touched from the
    # GUI thread — so the answer comes back through here.
    statusReady = pyqtSignal(str)

    def __init__(self, config) -> None:
        super().__init__()
        self._config = config
        self._chat_id: "str | None" = None
        self._answering = False
        self._sources: list = []

        self.setWindowTitle("Jude — Judaic study")
        self.resize(720, 760)

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setObjectName("jude_status")
        lay.addWidget(self._status)

        self._transcript = QTextBrowser()
        self._transcript.setOpenExternalLinks(True)   # source cards link to Sefaria
        font = QFont()
        font.setPointSize(13)
        self._transcript.setFont(font)
        lay.addWidget(self._transcript, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._mode = QComboBox()
        # Jude's three modes, in its own words: Q&A, Study (a deep pre-loaded
        # source pool), Sources only (skip synthesis, browse the passages).
        for label, value in (("Q&A", "qa"), ("Study", "study"), ("Sources", "sources")):
            self._mode.addItem(label, value)
        self._mode.setFixedWidth(96)
        row.addWidget(self._mode)

        self._entry = QLineEdit()
        self._entry.setPlaceholderText("Ask about Torah, Talmud, halacha…  (⌘N starts a new chat)")
        self._entry.returnPressed.connect(self._ask)
        row.addWidget(self._entry, 1)

        self._send = QPushButton("Ask")
        self._send.setObjectName("primary")
        self._send.clicked.connect(self._ask)
        row.addWidget(self._send)
        lay.addLayout(row)

        self._stream = _Stream()
        self._stream.stage.connect(self._on_stage)
        self._stream.token.connect(self._on_token)
        self._stream.meta.connect(self._on_meta)
        self._stream.finished.connect(self._on_finished)

        self.statusReady.connect(self._status.setText)

        self.setStyleSheet(_styles.get_app_style(dark=config.theme == "dark"))
        self._refresh_status()
        self._entry.setFocus()

    # -- state ----------------------------------------------------------

    def _refresh_status(self) -> None:
        """Ask the API what it can offer, and say so plainly.

        Not fatal, and never a dialog: an unreachable assistant or a missing
        Jude checkout is a sentence in the window, with the thing to do in it.
        """
        def _work() -> None:
            import urllib.request
            text = ""
            try:
                req = urllib.request.Request(_api_base(self._config) + "/jude/status")
                key = _api_key(self._config)
                if key:
                    req.add_header("X-API-Key", key)
                with urllib.request.urlopen(req, timeout=5) as r:
                    st = json.loads(r.read().decode("utf-8"))
                if st.get("ready"):
                    text = (f"Local · {st.get('model', '')} · Ollama"
                            + ("" if st.get("running") else " · starts on your first question"))
                else:
                    text = st.get("reason") or "Jude isn't available."
            except Exception as e:      # noqa: BLE001
                text = (f"Can't reach the assistant on {_api_base(self._config)} "
                        f"— is it running? ({e})")
            self.statusReady.emit(text)

        threading.Thread(target=_work, daemon=True, name="jude-status").start()

    def new_chat(self) -> None:
        if self._answering:
            return
        self._chat_id = None
        self._sources = []
        self._transcript.clear()
        self._entry.setFocus()

    # -- asking ---------------------------------------------------------

    def _ask(self) -> None:
        prompt = self._entry.text().strip()
        if not prompt or self._answering:
            return
        self._entry.clear()
        self._answering = True
        self._send.setEnabled(False)
        self._append_html(f'<p style="margin:14px 0 4px 0"><b>{_escape(prompt)}</b></p>')
        self._stream.ask(self._config, prompt, self._chat_id,
                         self._mode.currentData())

    def _on_stage(self, name: str) -> None:
        self._status.setText(name)

    def _on_token(self, text: str) -> None:
        # Appended as plain text: the answer is markdown-ish and streaming it
        # through a HTML parser a token at a time renders half-open tags.
        cursor = self._transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._transcript.setTextCursor(cursor)

    def _on_meta(self, evt: dict) -> None:
        self._chat_id = evt.get("chat_id") or self._chat_id
        self._sources = evt.get("sources") or []
        topic = evt.get("halachic_label") or ""
        seder = evt.get("halachic_seder") or ""
        if topic:
            self._append_html(
                f'<p style="margin:2px 0;color:{_styles.GRAY_TEXT}">📚 {_escape(topic)}'
                + (f" · Seder {_escape(seder)}" if seder else "") + "</p>")

    def _on_finished(self, error: str) -> None:
        self._answering = False
        self._send.setEnabled(True)
        if error:
            self._append_html(
                f'<p style="margin:8px 0;color:#c0392b">{_escape(error)}</p>')
        elif self._sources:
            # Every source card links back to Sefaria, which is Jude's own
            # convention and the reason its answers are checkable.
            items = "".join(
                f'<li>{_escape(s.get("ref", ""))}</li>' for s in self._sources[:12])
            self._append_html(
                f'<p style="margin:10px 0 2px 0;color:{_styles.GRAY_TEXT}">'
                f"Sources ({len(self._sources)})</p><ul>{items}</ul>")
        self._refresh_status()
        self._entry.setFocus()

    def _append_html(self, html: str) -> None:
        cursor = self._transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html)
        self._transcript.setTextCursor(cursor)

    def keyPressEvent(self, event) -> None:       # noqa: N802 (Qt's name)
        if (event.key() == Qt.Key.Key_N
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.new_chat()
            return
        super().keyPressEvent(event)


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Jude — Judaic study assistant")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from assistant.config import load_config, ConfigError
    try:
        config = load_config(args.config)
    except ConfigError:
        config = load_config("config.example.yaml")

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Jude")
    window = JudeWindow(config)
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

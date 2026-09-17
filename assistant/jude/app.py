"""Jude as its own Mac app.

    python -m assistant.jude.app [--config config.yaml]

A fourth window beside the calendar, the thinking HUD and the API server, and
separate from the calendar for the same reason the HUD is: studying a sugya is
not a thing you do inside a calendar, and this window should still be there
when the calendar is closed.

It reads config.yaml for two things only — the theme, and how to reach the API
(`api.port`, `api.key`) — so a checkout with no config.yaml still runs against
`config.example.yaml`. Nothing it does depends on a setting being right: a
missing config leaves it on the defaults the API itself ships with.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

EXAMPLE_CONFIG = "config.example.yaml"


def _load_config(path: str):
    """The user's config, the example, or nothing — in that order.

    `config.yaml` is gitignored, so a fresh checkout genuinely does not have
    one, and refusing to start over a file whose only job here is a port number
    would be a worse failure than running on the defaults.
    """
    from assistant.config import load_config

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for candidate in (path, os.path.join(root, path), EXAMPLE_CONFIG,
                      os.path.join(root, EXAMPLE_CONFIG)):
        try:
            return load_config(candidate)
        except Exception as exc:          # noqa: BLE001 - every candidate may fail
            logger.debug("could not read %s: %s", candidate, exc)
    logger.warning("Running on built-in defaults — no readable config file.")
    return None


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Jude — Judaic study assistant")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")

    from PyQt6.QtWidgets import QApplication

    from assistant.jude.ui import client
    from assistant.jude.ui.window import JudeWindow

    config = _load_config(args.config)

    app = QApplication(sys.argv if argv is None else [sys.argv[0]])
    app.setApplicationName("Jude")
    # The Dock icon when the window is run straight from the venv. `Jude.app`
    # carries the .icns itself, so this only matters for `python -m`.
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "jude_icon.png")
    if os.path.exists(icon_path):
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))

    window = JudeWindow(config)
    window.show()
    window.raise_()
    window.activateWindow()
    logger.info("📖 Jude window up, talking to %s/jude", client.api_base(config))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

"""The server as an app you click: ``python -m assistant.host``.

DEVQA Q69. One click starts what a phone needs — ollama and the API — and
leaves an icon in the menu bar (the system tray on Windows and Linux) that
says whether it is running, where it can be reached, and offers:

    Pair a phone or tablet…   the QR code (assistant/pairing/)
    Open calendar             the Mac window, if you want it
    Open at login             start the server with the computer
    Quit                      stops only what THIS app started

It checks its own setup on the way: no ollama → a link to get it; the model
not downloaded → one click downloads it. That download is the one time the
server reaches the internet, and only when asked.

Plain Python + Qt, so the same app runs on macOS, Linux and Windows; the
platform-specific parts are small and named (``autostart.py``, the Dock
policy in ``tray.py``). The pieces:

    supervisor.py   start/stop ollama and the API, read their health
    pair_dialog.py  the QR window — also opened from the calendar's More menu
    autostart.py    "Open at login" for each platform
    tray.py         the menu-bar icon and its menu
"""

# rumps menu-bar app (retired 2026-10-01)

`assistant/app.py` — the project's first surface, from the initial commit: a
`rumps` menu-bar item whose title was an emoji per pipeline status (🎙 🔴 ⚙️
✅ ⚠️). The calendar GUI (`python -m assistant.main`) and later the
MACalendar Server tray (`assistant/host/`) replaced it, and nothing imported
it any more.

Found while replacing every emoji with drawn icons (Gil, 2026-10-01): there
was no point redrawing a surface that no longer runs. The tray's status
pictures live in `assistant/host/tray.py`.

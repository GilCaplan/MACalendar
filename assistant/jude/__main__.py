"""`python -m assistant.jude` — the Jude window.

Jude.app (scripts/build_apps.sh) runs this module, but the window lives in
`assistant.jude.app`; without this file the app logged "No module named
assistant.jude.__main__" and quit at once (found 2026-09-28).
"""
import sys

from assistant.jude.app import main

sys.exit(main())

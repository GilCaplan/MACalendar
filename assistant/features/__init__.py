"""This assistant's own surfaces — the tabs and panels.

    base.py      the Feature contract: name, label, icon, order, pinned
    settings.py  the one visibility map, in config.yaml under `features:`
    registry.py  the list, and the one line server.py calls
    <name>/      one folder per feature

`CONVENTION.md` is how to add one. Note what this is NOT: an
`assistant/integrations/` Integration, which is for hosting somebody else's
PROGRAM. Jude is the only thing that is both.
"""

from assistant.features.base import Feature  # noqa: F401

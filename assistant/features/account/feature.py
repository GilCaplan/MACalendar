"""Account — the admin's dashboard, or a person's own account page.

Gil, 2026-09-28: *"make a tab for admin with dashboard and all relevant things
for admin to control properly, and … for users also tab which is a minimal
amount with what they are allowed to do"*. ONE tab whose content follows the
signed-in person's role, rather than two tabs of which one is always wrong for
whoever is looking: the admin gets the dashboard (every user, their devices,
sign-in policy, auto sign-out, what he sees of whom, vocabulary sharing,
resets, sign-outs); anyone else gets their own sharing, their two settings,
their password, and Sign out.

Its routes are `assistant/users/routes.py` (the users surface owns them), so
this declaration ships no blueprint. Pinned: signing out must always be
reachable.
"""

from __future__ import annotations

from assistant.features.base import Feature


class AccountFeature(Feature):
    name = "account"
    label = "Account"
    icon = "person.crop.circle"
    order = 90
    pinned = True
    default_visible = True

    def panel(self):
        from assistant.calendar_ui.account_panel import AccountPanel
        return AccountPanel

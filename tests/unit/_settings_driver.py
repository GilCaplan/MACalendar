"""Drive the real Settings dialog from a test, given the dialog itself.

Every Settings suite used to find the dialog by asking Qt for the active modal
widget and inspecting it from a polling timer. On Linux CI that lookup kept
segfaulting inside the inspection — 2026-09-30, PR #20, PR #36 (TASKS 53):
the wrapper Qt handed back could point at a widget that was being torn down.
`settings_dialog.ON_OPEN` hands the test the dialog `open_settings` just
built, so nothing is looked up and nothing can be stale.

A failure inside `interact` would leave the dialog's exec() spinning forever,
so it is recorded in `failures` (the test re-raises it) and the dialog closed.
"""

from __future__ import annotations


def drive_settings(interact, failures: list, *, always_close: bool = False) -> None:
    """Call `interact(dialog)` once the next `open_settings` has its dialog up."""
    from assistant.calendar_ui import settings_dialog

    def _go(dlg):
        settings_dialog.ON_OPEN = None              # once: never a later test's dialog
        try:
            interact(dlg)
        except Exception as e:                      # noqa: BLE001 — re-raised by the test
            failures.append(e)
            dlg.reject()
        finally:
            if always_close and dlg.isVisible():
                dlg.reject()

    settings_dialog.ON_OPEN = _go

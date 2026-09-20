"""The finding taxonomy and the router — what was wrong, and where it goes.

Gil, 2026-09-10 (`PLAN.md` §6.4): *"objects labeled bad but potentially good,
rewrite the prompt i.e. X1'… and objects which are not meant to be committed,
pass to the review panel."*

**The route is a property of the FINDING, not an opinion about the object.**
"Bad but potentially good" versus "not meant to be committed" is not one
decision and it is not the model's to make; it is a table, keyed the way
FastRule's `REFUSAL / STRUCTURE / INCAPACITY` already is. That is what keeps the
loop budget from being spent on findings a retry provably cannot fix:

    "you never said a time"      -> no rewrite invents one. Commit it, say so.
    "you asked for a third thing" -> a re-segmentation can genuinely find it.

Only the REWRITE rows spend a round. That discipline is the whole fix for the
2026-09-08 storm — *"Let an event to go out for a run now"*, three dead rounds,
30 seconds, the trace saying "unchanged since the last attempt" each time.

## Every finding is about ONE OBJECT

That is the whole shape of this stage after 2026-09-10. A finding says something
about an object that can be checked against the transcript by looking at that
object alone. Nothing here needs to know how many asks the command contained,
which is what let the ask list — and the model call that built it — go away.
"""
from __future__ import annotations

# -- the three finding types ------------------------------------------------
#
# Re-cut 2026-09-10 (Gil). `missing` and `extra` are GONE: both were defined by
# an ask list this stage no longer builds, because building one re-derived
# segmentation's answer with a weaker instrument. Every finding here is now a
# statement about ONE OBJECT, checkable against the words alone.

#: The object's SUBJECT is not established by the words — its title or target.
#: Three things land here and they are one problem wearing three faces:
#: Gatekeeper's objections (a mutation aimed at a bare noun, a rename that would
#: misroute, a create titled with the generic noun "event"), and a title nothing
#: in the transcript names.
#:
#: **Separate from `UNSUPPORTED_FIELD` because the routes must differ.** An
#: unsupported VALUE — a date nobody said — can be committed and reported: the
#: object is still the thing the speaker asked for. An unsupported SUBJECT
#: cannot; committing it puts a fabricated row on the calendar, which is the
#: measured cycle-7 defect `_guard_inventions` exists for.
UNGROUNDED_SUBJECT = "ungrounded_subject"

#: A VALUE field the words never supported — a pydantic default wearing a
#: resolved value's clothes ("date = today" on a command that named no day). A
#: retry cannot invent a date nobody said, so looping on it only spends the
#: budget: the object commits and the assumption is reported to the speaker.
UNSUPPORTED_FIELD = "unsupported_field"

#: NOTHING in this object is supported by the words. Not a wrong object — an
#: object that should not exist.
#:
#: This is what survives of `extra` after the ask list went away, and it is a
#: stronger test than `extra` was: `extra` meant "the model's ask list did not
#: mention it", which was as often the ask list's fault as the object's. This
#: means "not one field of it can be pointed at in the transcript", which needs
#: no second opinion about how many asks there were.
#:
#: Shares its route and its carrier with FastRule's `NotAnObject`, so the review
#: panel draws one outcome rather than two spellings of it.
NOT_AN_ASK = "not_an_ask"
#: ONE OBJECT NAMED WITH SEVERAL THINGS — a calendar create whose words carry
#: a bare noun list of three or more ("create an event for dentist, haircut
#: and gym"). Segmentation keeps such a list as one item by ruling (Q14), so
#: one event is built and titled with all three. Gil, 2026-09-20: the deep
#: engine should REWRITE it one clause per thing and re-enter — which is what
#: the loop-back is for, and the one under-split it can now name, because the
#: object alone says so: its title is a list.
COORDINATED_SUBJECT = "coordinated_subject"

# -- the three routes -------------------------------------------------------
#: Reword this ask into X1' and re-enter at segmentation. Costs a round.
REWRITE = "rewrite"

#: Commit the object, and tell the speaker what was assumed. Costs nothing.
COMMIT_FLAGGED = "commit_flagged"

#: Not calendar work. Show it on the review panel and never retry it.
PANEL = "panel"

#: THE ROUTER. `test_engine_contracts.py` pins these keys — a new finding type
#: with no route is a finding that silently does nothing, which is the failure
#: mode this table exists to make impossible.
ROUTE = {
    UNGROUNDED_SUBJECT: REWRITE,
    COORDINATED_SUBJECT: REWRITE,
    UNSUPPORTED_FIELD: COMMIT_FLAGGED,
    NOT_AN_ASK: PANEL,
}

#: Which stage each type blames, for the trace and the `CheckFinding` field.
#: Kept because `blamed_stage` is a frozen contract field — but it is no longer
#: what DECIDES anything. `ROUTE` decides; this only reports.
BLAMED = {
    UNGROUNDED_SUBJECT: "fastrule",
    COORDINATED_SUBJECT: "segment",
    UNSUPPORTED_FIELD: "decompose_validate",
    NOT_AN_ASK: "segment",
}


def route(finding_type: str) -> str:
    """Where a finding goes. An unknown type routes to the panel rather than
    raising: an unroutable finding must still reach a human."""
    return ROUTE.get(finding_type, PANEL)


def wants_rewrite(findings) -> bool:
    """Does anything here earn a loop round? The orchestrator's gate."""
    return any(route(f.type) == REWRITE for f in findings)


def rewritable(findings) -> list:
    """Just the findings X1' has to address — the ones that go back around."""
    return [f for f in findings if route(f.type) == REWRITE]

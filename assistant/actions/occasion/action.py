"""The ``add_occasion`` action: file a yearly date (or a countdown) as an
OCCASION — an all-day banner — not an event.

Two ways in, one date reading (assistant/occasions/voice.py):
- the rules (``rule_parser.analyze``) recognise a narrow, unambiguous shape
  ("Dana's birthday is March 3rd") and hand this intent over directly;
- the model may pick it too; it passes the day words AS SAID ("12 Adar",
  "March 3rd") and code works out the date — never the model.
"""

from __future__ import annotations

from typing import ClassVar, Optional, Type

from pydantic import field_validator

from assistant.actions import register
from assistant.actions.base import BaseAction, BaseIntent
from assistant.exceptions import ParseError


class AddOccasionIntent(BaseIntent):
    kind: str
    name: str
    date_text: str
    year: Optional[int] = None

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ("birthday", "anniversary", "yahrzeit", "countdown", "custom",
                     "bday", "b-day", "yortzeit", "yahrtzeit", "jahrzeit", "yartzeit"):
            raise ValueError("kind must be birthday, anniversary, yahrzeit or countdown")
        return v


@register
class AddOccasionAction(BaseAction):
    action_name: ClassVar[str] = "add_occasion"
    description: ClassVar[str] = (
        "Save a YEARLY date — someone's birthday, an anniversary, a yahrzeit — or a "
        "countdown to a date, as an OCCASION (an all-day banner), NOT an event. "
        "Triggers on: \"Dana's birthday is March 3rd\", \"remember our anniversary, June 20\", "
        "\"add my grandfather's yahrzeit on 12 Adar\", \"countdown to the wedding on "
        "December 1\". Do NOT use it for something happening at a time or with a plan — "
        "\"birthday dinner Tuesday at 8\", \"book a table for our anniversary\" are events "
        "(create_event)."
    )
    intent_model: ClassVar[Type[BaseIntent]] = AddOccasionIntent
    #: Its banner is drawn by the calendar views, so they redraw.
    refreshes: ClassVar[str] = "events"
    #: Rules only, for now: offering it to the model changes the prompt of
    #: every command the model sees, and that is measured on Board D
    #: --product before it is switched on (CLAUDE.md, "Measuring a change").
    model_visible: ClassVar[bool] = False
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "kind": {"type": "string",
                     "enum": ["birthday", "anniversary", "yahrzeit", "countdown"]},
            "name": {"type": "string",
                     "description": "Whose or what — 'Dana', 'our anniversary', 'Grandpa Moshe', 'the wedding'."},
            "date_text": {"type": "string",
                          "description": "The date words exactly as said, e.g. 'March 3rd', '12 Adar'."},
            "year": {"type": ["integer", "null"],
                     "description": "The starting year if said (birth year, wedding year), else null."},
        },
        "required": ["kind", "name", "date_text"],
    }

    def execute(self, intent: AddOccasionIntent, config) -> str:  # type: ignore[override]
        from assistant.occasions import dates, store, voice
        rec = voice.from_words(intent.kind, intent.name, intent.date_text, intent.year)
        if rec is None:
            raise ParseError(f"I couldn't tell which date “{intent.date_text}” is — "
                             "say the day and month, like “March 3rd” or “12 Adar”.")
        got, why = store.add(rec)
        if got is None:
            raise ParseError(why)
        when = (f"{got['day']} {_HEB_NAMES[got['month'] - 1]} (Hebrew date)"
                if got["calendar"] == "hebrew" else
                f"{got['day']} {_GREG_NAMES[got['month'] - 1]}"
                + (f" {got['year']}" if got.get("year") and got["kind"] == "countdown" else ""))
        what = dates.banner_title(got["kind"], got["title"], None)
        repeat = "" if got["kind"] == "countdown" else ", every year"
        return f"Added {what} — {when}{repeat}. It shows as a banner; tap it to change it."


_GREG_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
_HEB_NAMES = ["Nisan", "Iyar", "Sivan", "Tammuz", "Av", "Elul", "Tishrei", "Cheshvan",
              "Kislev", "Tevet", "Shevat", "Adar", "Adar II"]

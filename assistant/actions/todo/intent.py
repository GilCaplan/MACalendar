"""Intent models for todo voice actions."""

from __future__ import annotations

from pydantic import field_validator, model_validator

from assistant.actions.base import BaseIntent


class CreateTodoIntent(BaseIntent):
    titles: list[str] = []
    # One count per title, same order. Filled by the validator below, never by
    # the model — asking the LLM for a parallel array invited it to return one
    # of a different length.
    quantities: list[int] = []
    list_name: str = "today"   # 'today' | 'general'
    priority: str = "none"     # 'none' | 'low' | 'medium' | 'high'
    due_date: str | None = None
    # Tag names the user said out loud ("put it on the groceries list"). Only
    # names that exist in the palette survive — CreateTodoAction resolves them,
    # and falls back to inferring a tag from the title when none were given.
    tags: list[str] = []

    @field_validator("titles", "tags", mode="before")
    @classmethod
    def coerce_titles(cls, v):
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return v

    @model_validator(mode="after")
    def require_titles(self) -> CreateTodoIntent:
        if not self.titles:
            raise ValueError("titles list cannot be empty")
        return self

    @model_validator(mode="after")
    def fold_quantities(self) -> CreateTodoIntent:
        """Read counts out of the titles, and fold repeats into one task.

        Covers both ways a quantity arrived as duplication: the LLM emitting
        the same title five times for "pasta times 5", and a count left inside
        a single title. Runs after require_titles, so titles is non-empty.
        """
        from assistant.intent.quantity import collapse_repeats
        titles, quantities = collapse_repeats(self.titles)
        if titles:
            object.__setattr__(self, "titles", titles)
            object.__setattr__(self, "quantities", quantities)
        return self

    def quantity_for(self, index: int) -> int:
        """The count for titles[index], defaulting to 1."""
        try:
            return max(1, int(self.quantities[index]))
        except (IndexError, TypeError, ValueError):
            return 1


class CompleteTodoIntent(BaseIntent):
    match_title: str
    complete: bool = True   # False = uncheck


class DeleteTodoIntent(BaseIntent):
    match_title: str


class UpdateTodoIntent(BaseIntent):
    match_title: str
    new_title: str | None = None
    new_list: str | None = None
    new_priority: str | None = None
    new_due_date: str | None = None   # ISO date string, e.g. '2026-04-01'
    new_notes: str | None = None      # Replace/set the task notes


class QueryTodoIntent(BaseIntent):
    list_name: str = "all"         # 'today' | 'general' | 'all'
    include_completed: bool = False


class AddSubtaskIntent(BaseIntent):
    parent_title: str       # which parent task to add the subtask to
    subtask_title: str      # title of the new subtask


class CompleteSubtaskIntent(BaseIntent):
    parent_title: str
    subtask_title: str
    complete: bool = True   # False = uncheck


class DeleteSubtaskIntent(BaseIntent):
    parent_title: str
    subtask_title: str

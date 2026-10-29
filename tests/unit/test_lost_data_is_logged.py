"""A write that is allowed to fail quietly must still say so in the log.

The 2026-10-29 review found 88 broad `except: pass` blocks. Most guard
best-effort extras, but some dropped data with no trace: the user's label
corrections (the one non-circular label source), learned vocabulary aliases,
command-memory feedback, the History record. Those now log a warning with the
traceback and still never break the user's action.
"""
import logging


def test_a_correction_that_cannot_be_saved_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    from assistant.engine.label import feedback
    blocked = tmp_path / "a-file-not-a-folder"
    blocked.write_text("")
    monkeypatch.setattr(feedback, "_feedback_path", lambda: blocked / "feedback.jsonl")
    with caplog.at_level(logging.WARNING, logger=feedback.__name__):
        feedback._append({"kind": "event", "title": "Dentist"})     # must not raise
    assert any("Could not save a label correction" in r.message and r.exc_info
               for r in caplog.records)


def test_a_broken_path_inside_the_handler_cannot_escape(monkeypatch, caplog):
    """The log line must not itself call what failed."""
    from assistant.engine.label import feedback

    def boom():
        raise OSError("no user folder")
    monkeypatch.setattr(feedback, "_feedback_path", boom)
    with caplog.at_level(logging.WARNING, logger=feedback.__name__):
        feedback._append({"kind": "event", "title": "Dentist"})     # must not raise
    assert any("Could not save a label correction" in r.message for r in caplog.records)

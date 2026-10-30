"""The one-shot engine reads today's date from the clock module.

Its time parser was also named `_clock`, defined below `from assistant import
clock as _clock`, so the function replaced the module and `build_objects`
crashed on `_clock.today()`: every command run with MACALENDAR_ONESHOT=1
raised AttributeError (2026-10-09 to 2026-10-30, found by ruff F811).
"""


def test_the_clock_module_is_not_shadowed():
    from assistant import clock
    from assistant.engine import LLM_one_shot
    assert LLM_one_shot._clock is clock
    assert hasattr(LLM_one_shot._clock, "today")


def test_the_time_parser_keeps_only_hh_mm():
    from assistant.engine.LLM_one_shot import _hhmm
    assert _hhmm("14:30") == "14:30"
    assert _hhmm(" 09:05 ") == "09:05"
    for bad in ("", None, "2pm", "14:3", 1430):
        assert _hhmm(bad) is None

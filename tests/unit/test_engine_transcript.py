

def test_spoken_noise_comes_off_in_the_cleanup_stage(sample_config):
    """Gil's architecture call: the person-specific work — vocabulary repair
    and the "mhmm"/"umm" filler — belongs in the INITIAL CLEANUP step, so
    everything downstream is generic. Filler stripping used to live inside
    FastRule's own normalisation, so the DEEP track never got it: real-usage
    review showed the LLM path failing 5 of 5 on rambling dictation opening
    with exactly these words."""
    from assistant.engine.ingest import repair as transcript
    from assistant.engine.state import EngineState

    st = EngineState(raw_text="Alright, we have a movie today from 3pm to 6pm",
                     text="", source="test")
    transcript.run(st, sample_config)
    assert not st.text.lower().startswith("alright")
    assert "movie" in st.text and "3pm" in st.text     # nothing else lost


# ---------------------------------------------------------------------------
# Step 0 — "is this a command at all?"
#
# Three shapes of non-command reach the brain: silence that transcribed to
# nothing, a recording that is only the word which ended it, and a false start.
# All three used to be found INSIDE stage 1, i.e. after the run lock and the
# config load; and two of them were not found at all, because the stop-word
# strip only ever removed ONE trailing keyword and fell back to the original
# when that emptied the string. "that's it" therefore reached the LLM as a
# two-word command.
# ---------------------------------------------------------------------------

import pytest


@pytest.mark.parametrize("said", [
    "",
    "   ",
    "execute",
    "Execute.",
    "xq",                 # what Whisper writes when it mishears "execute"
    "that's it",
    "set events",
    "ok go",
    "done",
    "um",
    "I need a b-",
])
def test_nothing_to_act_on_is_ignorable(said):
    from assistant.engine.ingest.repair import is_ignorable
    assert is_ignorable(said), f"{said!r} is not a command"


@pytest.mark.parametrize("said", [
    "add lunch tomorrow at one",
    "add lunch tomorrow at one execute",
    "go to shul at 7",       # "go" is a stop word only at the very end
    "buy milk",
])
def test_real_commands_are_not_ignorable(said):
    from assistant.engine.ingest.repair import is_ignorable
    assert not is_ignorable(said), f"{said!r} is a real command"


def test_every_trailing_stop_keyword_comes_off_not_just_the_last():
    """One pass removed one keyword, so "add milk, done, execute" arrived as
    "add milk, done" and the parser had to make sense of the "done"."""
    from assistant.engine.ingest.repair import strip_stop_keyword
    assert strip_stop_keyword("add milk, done, execute") == "add milk"


def test_a_stop_word_only_transcript_is_ignored_by_the_stage(sample_config):
    """Not merely "ignorable" at the front door: the stage itself must reach
    the same verdict, since that is the path a custom stop phrase takes."""
    from assistant.engine.ingest import repair as transcript
    from assistant.engine.state import EngineState

    st = EngineState(raw_text="that's it", text="", source="test")
    transcript.run(st, sample_config)
    assert st.ignored and st.parse_path == "ignored"


def test_the_engine_exits_before_the_run_lock(monkeypatch):
    """The point of the front-door check: a non-command must not queue behind
    a command that is already running, nor load the config to be thrown away."""
    from assistant import engine

    def boom():
        raise AssertionError("config was loaded for a transcript with nothing in it")

    monkeypatch.setattr(engine, "load_config", boom)
    engine._run_lock.acquire()          # as if a long command were mid-flight
    try:
        resp = engine.run_transcript("execute", source="test")
    finally:
        engine._run_lock.release()
    assert resp["parse"] == "ignored"
    assert resp["message"] == ""

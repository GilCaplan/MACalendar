"""A long run must show progress and survive dying. Both, or neither counts.

Board D ran for three and a half hours and printed nothing until the end. `ps`
said "alive, 0.0% CPU", which is what a slow ollama call looks like AND what a
hang looks like — there was no way to tell them apart. A crash at 90% would have
cost the whole run: three hours of model calls with nothing on disk.

Gil, 2026-09-10: *"for future make sure we checkpoint when running long
experiments."*
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from assistant.checkpoint import Checkpoint
import assistant.checkpoint as ckmod


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(ckmod, "CHECKPOINT_DIR", tmp_path)
    return tmp_path


def test_a_completed_unit_is_on_disk_before_the_next_one_starts(scratch):
    """The guarantee. Buffering would make the whole thing decorative: a
    crash would lose exactly the work the checkpoint exists to protect."""
    ck = Checkpoint("t", total=3)
    ck.record("a", {"ok": True})
    # read it from ANOTHER handle, without closing — it must already be there
    rows = [json.loads(l) for l in (scratch / "t.jsonl").read_text().splitlines() if l.strip()]
    assert rows == [{"k": "a", "v": {"ok": True}}]


def test_re_running_resumes_instead_of_redoing_hours_of_model_calls(scratch):
    first = Checkpoint("t")
    for i in range(5):
        first.record(f"row-{i}", i)
    first.finish()

    second = Checkpoint("t")
    assert all(second.has(f"row-{i}") for i in range(5))
    assert not second.has("row-5")
    assert second.get("row-3") == 3


def test_resume_false_starts_clean(scratch):
    Checkpoint("t").record("a", 1)
    fresh = Checkpoint("t", resume=False)
    assert not fresh.has("a")


def test_a_torn_last_line_costs_only_the_row_in_flight(scratch):
    """What `kill -9` mid-write actually leaves. Everything before the torn
    line is good — that is the whole reason units are appended one at a time
    rather than dumped at the end."""
    ck = Checkpoint("t")
    for i in range(4):
        ck.record(f"row-{i}", i)
    ck.finish()
    with open(scratch / "t.jsonl", "a") as fh:
        fh.write('{"k": "row-4", "v": {"partial')      # died here

    resumed = Checkpoint("t")
    assert all(resumed.has(f"row-{i}") for i in range(4))
    assert not resumed.has("row-4")


def test_a_real_kill_9_loses_nothing_already_recorded(scratch, tmp_path):
    """Not a simulation: a real child process, really killed."""
    script = textwrap.dedent(f"""
        import os, sys, time
        os.environ["MACALENDAR_CHECKPOINTS"] = {str(tmp_path)!r}
        sys.path.insert(0, {str(__import__("pathlib").Path(__file__).resolve().parents[2])!r})
        from assistant.checkpoint import Checkpoint
        ck = Checkpoint("killed", total=100, every=1000)
        for i in range(20):
            ck.record("row-%d" % i, i)
        print("READY", flush=True)
        time.sleep(60)
    """)
    proc = subprocess.Popen([sys.executable, "-c", script],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "READY"
    proc.kill()
    proc.wait(timeout=10)

    resumed = Checkpoint("killed")
    assert len(resumed.results) == 20
    assert resumed.get("row-19") == 19


def test_progress_is_visible_without_reading_the_code(scratch, capsys):
    """"Is it working?" must be answerable by LOOKING. `ps` reporting 0.0% CPU
    is what a slow model call and a hang look like alike."""
    ck = Checkpoint("t", total=10, every=2)
    for i in range(4):
        ck.record(f"row-{i}", i)
    out = capsys.readouterr().out
    assert "[t] 2/10" in out and "[t] 4/10" in out
    assert "eta" in out and "/min" in out


def test_an_unwritable_checkpoint_never_stops_the_run(tmp_path, monkeypatch, capsys):
    """The measurement is the point; this is bookkeeping. It degrades to the
    old behaviour, LOUDLY — a silent degradation would leave someone believing
    they had a checkpoint they could resume from."""
    monkeypatch.setattr(ckmod, "CHECKPOINT_DIR", tmp_path / "file-not-a-dir")
    (tmp_path / "file-not-a-dir").write_text("I am a file")
    ck = Checkpoint("t", total=2)
    ck.record("a", 1)                       # must not raise
    ck.finish()
    assert "cannot write" in capsys.readouterr().out
    assert ck.has("a")                      # still correct in memory


def test_progress_is_real_time_even_inside_a_frozen_clock(scratch, capsys):
    """EVERY BOARD IN THIS PROJECT RUNS UNDER `freeze_time`.

    Cases are generated at a fixed CLOCK so a plant that depends on "the day
    after tomorrow" resolves the same way every run — and freezegun patches
    `time.time` and `time.monotonic` alike. A progress meter that reads either
    one inside the frozen block sees a fixed instant: Board D's first real
    progress line read "1500000000/min · 0m elapsed", because elapsed came out
    negative against the frozen past date and clamped to a microsecond.

    The operator watching a five-hour run is not part of the experiment's
    reproducibility fiction.
    """
    import datetime as dt
    from freezegun import freeze_time

    ck = Checkpoint("frozen", total=4, every=2)
    with freeze_time(dt.datetime(2026, 9, 9, 10, 0)):
        for i in range(2):
            ck.record(f"row-{i}", i)
    out = capsys.readouterr().out
    assert "[frozen] 2/4" in out

    # ASSERT A SANE RANGE IN BOTH DIRECTIONS. The first version of this test
    # only rejected an absurdly HIGH rate, so it passed against a fix that did
    # not work: binding `time.monotonic` at import does not escape freezegun,
    # and the meter then read 29,814,215 minutes elapsed — a rate of 0/min,
    # which sailed through an upper-bound-only check. A test that can only
    # catch one of the two ways a number goes wrong is half a test.
    elapsed_m = float(out.rsplit("·", 1)[-1].strip().split("m elapsed")[0])
    assert 0 <= elapsed_m < 1, f"elapsed read a frozen clock: {out!r}"
    rate = float(out.split("·")[-2].strip().split("/min")[0])
    assert 0 < rate < 10_000_000, f"rate read a frozen clock: {out!r}"


def test_resumed_units_do_not_inflate_the_rate_or_the_eta(scratch, capsys,
                                                          monkeypatch):
    """An ETA you cannot trust is worse than none, because you plan around it.

    Board D resumed 111 rows and immediately reported "eta 27m" for what was
    really a three-hour run: the reclaimed rows cost no time THIS run, so
    counting them in the rate made the job look enormously fast.

    The clock is driven by hand. A unit test finishes in microseconds, so ANY
    rate computed against real elapsed time is enormous and the assertion could
    not tell the two behaviours apart — which is how the previous version of
    this test failed against correct code.
    """
    first = Checkpoint("t")
    for i in range(100):
        first.record(f"old-{i}", i)
    first.finish()
    capsys.readouterr()

    ticks = iter([0.0] + [60.0] * 10)       # construct at t=0, report at t=60s
    monkeypatch.setattr(ckmod, "_now", lambda: next(ticks))

    second = Checkpoint("t", total=200, every=1)
    second.record("new-0", 0)
    out = capsys.readouterr().out

    assert "100 resumed" in out
    # ONE unit of real work in 60 seconds. Counting the 100 reclaimed rows
    # would report 101/min and an ETA 100x too short.
    assert "· 1/min ·" in out, out
    assert "eta 99m" in out, out

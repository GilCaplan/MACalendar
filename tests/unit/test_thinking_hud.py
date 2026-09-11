"""The thinking HUD — a separate app fed by the trace bus.

The trace used to be drawn inside the calendar window, so you only saw what the
assistant did if you happened to be looking at the calendar — which you rarely
are when you speak to it from the phone. These cover the two halves of moving
it out: the bus carrying a run as it happens (it used to carry only finished
ones, published by the API server), and the HUD rendering both shapes.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def bus(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_TRACE_BUS", str(tmp_path / "bus.jsonl"))
    from assistant import trace_bus
    monkeypatch.setattr(trace_bus, "BUS_PATH", str(tmp_path / "bus.jsonl"))
    return trace_bus


def _enter_event():
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtCore import Qt
    return QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))


def _leave_event():
    from PyQt6.QtCore import QEvent
    return QEvent(QEvent.Type.Leave)


def _step(stage="stt", title="Heard", detail=""):
    return {"stage": stage, "title": title, "detail": detail, "ms": 5, "at_ms": 5, "ok": True}


# ---------------------------------------------------------------------------
# The bus
# ---------------------------------------------------------------------------

def test_a_streaming_run_arrives_line_by_line(bus):
    offset = bus.size()
    run = bus.publish_begin("Mac")
    bus.publish_step(run, _step())
    bus.publish_result(run, {"message": "done"})

    entries, offset = bus.read_since(offset)
    assert [e["kind"] for e in entries] == ["begin", "step", "result"]
    assert all(e["run"] == run for e in entries)
    assert entries[0]["source"] == "Mac"
    assert entries[2]["result"] == {"message": "done"}


def test_a_reader_that_polls_late_still_gets_the_whole_run(bus):
    offset = bus.size()
    run = bus.publish_begin("Mac")
    for _ in range(3):
        bus.publish_step(run, _step())
    bus.publish_result(run)
    entries, _ = bus.read_since(offset)
    assert len(entries) == 5


def test_read_since_returns_nothing_new_when_nothing_happened(bus):
    run = bus.publish_begin("Mac")
    bus.publish_result(run)
    offset = bus.size()
    assert bus.read_since(offset) == ([], offset)


def test_a_whole_finished_run_still_publishes_in_one_line(bus):
    # This is what the API server does for the phone; it must keep working.
    offset = bus.size()
    bus.publish("iPhone", [_step()], {"message": "Two events"})
    entries, _ = bus.read_since(offset)
    assert len(entries) == 1
    assert entries[0]["kind"] == "trace"
    assert entries[0]["source"] == "iPhone"


def test_a_line_written_before_streaming_existed_reads_as_a_finished_run(bus):
    # Entries already on disk from the previous format have no "kind".
    with open(bus.BUS_PATH, "w", encoding="utf-8") as f:
        f.write('{"ts": 1, "source": "iPhone", "steps": [], "result": {}}\n')
    entries, _ = bus.read_since(0)
    assert entries[0]["kind"] == "trace"


def test_a_trim_never_lands_inside_a_run(bus, monkeypatch):
    monkeypatch.setattr(bus, "MAX_ENTRIES", 4)
    for _ in range(20):                     # plenty to trigger trimming
        run = bus.publish_begin("Mac")
        bus.publish_step(run, _step())
        bus.publish_result(run)
    with open(bus.BUS_PATH, encoding="utf-8") as f:
        kinds = [__import__("json").loads(line)["kind"] for line in f]
    # However the file was cut, the last run is whole: it began after the trim.
    assert kinds[-3:] == ["begin", "step", "result"]


# ---------------------------------------------------------------------------
# The HUD
# ---------------------------------------------------------------------------

@pytest.fixture
def hud(bus, tmp_path, monkeypatch):
    # PyQt6 itself imports fine without the system GL libraries; QtWidgets is
    # what raises (libEGL.so.1 on a bare CI runner), so that is what to probe.
    pytest.importorskip("PyQt6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("MACALENDAR_HUD_STATE", str(tmp_path / "pos.json"))
    from PyQt6.QtWidgets import QApplication
    import assistant.thinking_hud as hud_mod
    monkeypatch.setattr(hud_mod, "STATE_PATH", str(tmp_path / "pos.json"))
    app = QApplication.instance() or QApplication([])
    widget = hud_mod.ThinkingHUD(None)
    reader = hud_mod._BusReader(widget, str(tmp_path / "no-such-config.yaml"))
    yield widget, reader, app
    widget.close()
    widget.deleteLater()


def test_it_stays_out_of_the_way_until_something_happens(hud):
    widget, _, _ = hud
    assert not widget.isVisible()


def test_a_streaming_run_shows_it_and_fills_in(hud, bus):
    widget, reader, _ = hud
    run = bus.publish_begin("Mac")
    reader.poll()
    assert widget.isVisible()
    assert widget.panel.running and widget.panel.step_count == 0

    bus.publish_step(run, _step("stt", "Heard", "buy chicken and rice"))
    bus.publish_step(run, _step("execute", "Create Todo"))
    reader.poll()
    assert widget.panel.step_count == 2

    bus.publish_result(run, {"message": "Added 2 tasks"})
    reader.poll()
    assert not widget.panel.running


def test_a_late_self_check_step_reopens_the_timeline(hud, bus):
    widget, reader, _ = hud
    run = bus.publish_begin("Mac")
    bus.publish_step(run, _step())
    bus.publish_result(run, {"message": "ok"})
    reader.poll()
    assert not widget.panel.running

    bus.publish_step(run, _step("verify", "Self-check"))
    reader.poll()
    assert widget.panel.running and widget.panel.step_count == 2


def test_a_phone_run_is_labelled_as_the_phone(hud, bus):
    widget, reader, _ = hud
    bus.publish("iPhone", [_step(), _step("execute", "Create Todo")], {"message": "Added"})
    reader.poll()
    assert widget.isVisible()
    assert widget.panel.step_count == 2
    assert "iPhone" in widget.panel._title.text()


def test_closing_it_keeps_it_closed(hud, bus):
    """Reversed deliberately: this used to assert the next command brought the
    card back, and that was the complaint. Closing it is an instruction, not a
    dismissal of the run that happens to be on screen — it popping straight
    back up made closing it pointless. The menu bar item added alongside this
    is what makes staying closed safe; without one the card reverts to
    reappearing (see test_hud_history.py).

    Commands that run while it is hidden are still recorded, so opening it
    later shows what was missed.
    """
    widget, reader, _ = hud
    bus.publish("iPhone", [_step()], {})
    reader.poll()
    widget.panel._on_close()
    assert not widget.isVisible()

    bus.publish("iPhone", [_step()], {})
    reader.poll()
    assert not widget.isVisible()

    widget.reopen()
    assert widget.isVisible()


def test_a_step_whose_begin_was_trimmed_away_still_opens_a_run(hud, bus):
    widget, reader, _ = hud
    bus.publish_step("a-run-we-never-saw", _step("stt", "Heard", "orphan"))
    reader.poll()
    assert widget.isVisible()
    assert widget.panel.step_count == 1


def test_show_thinking_off_keeps_it_hidden(hud, bus):
    widget, reader, _ = hud
    from assistant.config import UIConfig

    class _Cfg:
        ui = UIConfig(show_thinking=False)
    widget._config = _Cfg()

    bus.publish("iPhone", [_step()], {})
    reader.poll()
    assert not widget.isVisible()


@pytest.mark.parametrize("corner", ["bottom-right", "bottom-left", "top-right", "top-left"])
def test_it_parks_on_screen_in_every_corner(hud, corner):
    widget, _, app = hud
    from assistant.config import UIConfig

    class _Cfg:
        ui = UIConfig(thinking_corner=corner)
    widget._config = _Cfg()
    widget._park()

    area = app.primaryScreen().availableGeometry()
    assert area.contains(widget.geometry()), f"{corner} put it off screen"


def test_a_dragged_position_is_remembered_and_overrides_the_corner(hud):
    widget, _, _ = hud
    import assistant.thinking_hud as hud_mod

    hud_mod._save_position(120, 240)
    widget.mark_moved()
    widget._park()
    assert (widget.pos().x(), widget.pos().y()) == (120, 240)
    assert os.path.exists(hud_mod.STATE_PATH)


def test_it_sits_translucent_until_you_look_at_it(hud, bus):
    """"There, but not what you're on": it settles below full opacity.

    The animation's target is what's asserted, not the window's actual
    opacity — the offscreen platform used in tests cannot set one.
    """
    widget, reader, _ = hud
    import assistant.thinking_hud as hud_mod

    assert hud_mod.IDLE_OPACITY < hud_mod.HOVER_OPACITY

    bus.publish("iPhone", [_step()], {})
    reader.poll()
    assert widget._fade.endValue() == pytest.approx(hud_mod.IDLE_OPACITY)

    widget.enterEvent(_enter_event())        # pointer moves over it
    assert widget._fade.endValue() == pytest.approx(hud_mod.HOVER_OPACITY)

    widget.leaveEvent(_leave_event())        # …and away again
    assert widget._fade.endValue() == pytest.approx(hud_mod.IDLE_OPACITY)


def test_it_never_takes_the_keyboard(hud):
    # WA_ShowWithoutActivating is the whole reason this is usable: the card
    # appearing must not pull focus out of whatever you were typing in.
    from PyQt6.QtCore import Qt
    widget, _, _ = hud
    assert widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    # …and not Qt.Tool, which macOS hides whenever the owning app is inactive —
    # which, for a Dock-less accessory app, is always.
    assert not (widget.windowFlags() & Qt.WindowType.Tool == Qt.WindowType.Tool)


# ---------------------------------------------------------------------------
# Which device it says the command came from
# ---------------------------------------------------------------------------

def test_a_command_spoken_at_the_mac_is_not_labelled_as_the_phone(hud, bus):
    widget, reader, _ = hud
    # A phone run first, so a stale label would be visible if it didn't reset.
    bus.publish("ios", [_step()], {})
    reader.poll()
    assert "iPhone" in widget.panel._title.text()

    run = bus.publish_begin("Mac")
    bus.publish_step(run, _step())
    reader.poll()
    assert widget.panel._title.text() == "Thinking"


@pytest.mark.parametrize("published,shown", [
    ("ios", "Thinking · from your iPhone"),     # what the API server publishes
    ("iPhone", "Thinking · from your iPhone"),
    ("mac", "Thinking"),                        # what Pipeline._trace_begin publishes
    ("Mac", "Thinking"),
    ("ipad", "Thinking · from your iPad"),
])
def test_the_source_is_named_the_way_a_person_would(hud, bus, published, shown):
    widget, reader, _ = hud
    bus.publish(published, [_step()], {})
    reader.poll()
    assert widget.panel._title.text() == shown


# ---------------------------------------------------------------------------
# Where it puts itself
# ---------------------------------------------------------------------------

def test_a_saved_position_off_the_current_screen_is_pulled_back_on(hud):
    """A position saved against a screen you no longer have must not hide it.

    This is how the HUD went missing: a stale `hud_position.json` put it a few
    pixels below the usable area, so it was drawn — on screen, right size, full
    opacity — with only its top edge showing, and nothing said why.
    """
    widget, _, app = hud
    import assistant.thinking_hud as hud_mod

    area = app.primaryScreen().availableGeometry()
    hud_mod._save_position(area.left() + 40, area.bottom() + 500)   # way off the bottom
    widget.mark_moved()
    widget._park()

    assert area.contains(widget.geometry())


def test_a_click_on_the_header_is_not_a_drag(hud):
    """Pressing and releasing without moving must not pin the card.

    It used to save a position and mark it moved, which silently opted out of
    corner parking for good — on the next launch it reappeared wherever that
    stray click happened to leave it.
    """
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    widget, _, _ = hud
    import assistant.thinking_hud as hud_mod

    def _mouse(kind, x, y):
        return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), QPointF(x, y),
                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)

    drag = widget._drag
    drag.eventFilter(None, _mouse(QEvent.Type.MouseButtonPress, 100, 100))
    drag.eventFilter(None, _mouse(QEvent.Type.MouseButtonRelease, 101, 100))   # 1px

    assert not widget._moved
    assert not os.path.exists(hud_mod.STATE_PATH)


def test_minimising_collapses_the_card_and_the_window_with_it(hud, bus):
    """The – button did nothing at all.

    `clicked` carries the checked state, so connecting it straight to
    `toggle_minimised` passed a bool into that method's `minimised` parameter —
    always False, always "restore", never a toggle.
    """
    widget, reader, app = hud
    bus.publish("mac", [_step()], {"message": "ok"})
    reader.poll()
    panel = widget.panel
    open_height = widget.height()

    panel._min_btn.click()
    app.processEvents()
    assert panel.minimised
    assert not panel._scroll.isVisible()          # body hidden, header still there
    assert panel._min_btn.text() == "+"
    assert widget.height() < open_height          # the window shrank with it

    panel._min_btn.click()
    app.processEvents()
    assert not panel.minimised
    assert panel._scroll.isVisible()
    assert panel._min_btn.text() == "–"
    assert widget.height() == open_height


def test_a_minimised_card_stays_minimised_for_the_next_command(hud, bus):
    # Minimising it means "keep it out of my way"; the header goes on counting.
    widget, reader, app = hud
    bus.publish("mac", [_step()], {})
    reader.poll()
    widget.panel._min_btn.click()
    app.processEvents()

    bus.publish("mac", [_step(), _step("execute", "Create Todo")], {})
    reader.poll()
    assert widget.panel.minimised
    assert widget.panel.step_count == 2


# ---------------------------------------------------------------------------
# The chain rail — the canonical CHAINS scaffold, rendered by brain version
# ---------------------------------------------------------------------------

def _rail_state(rail):
    """(labels done, active label) — what the scaffold is showing."""
    done = {rail._slots[i][1] for i in rail._done}
    active = None if rail._active is None else rail._slots[rail._active][1]
    return done, active


def test_the_rail_names_the_current_brain_version(hud):
    from assistant import trace
    widget, _, _ = hud
    widget.panel.begin("Mac")
    assert widget.panel._rail is not None
    assert widget.panel._rail._ver.text() == trace.BRAIN_VERSION


def test_the_rail_lights_the_chain_in_order_as_steps_arrive(hud):
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.add_step(_step("rule", "Rules"))
    done, active = _rail_state(p._rail)
    assert "fix words" in done          # the earlier slot is behind us
    assert active == "rules first"      # and the rule slot is live


def test_the_rail_maps_the_two_rule_slots_in_chain_order(hud):
    # segmentation and the object-making box also trace as `rule`; the second
    # `rule` step must land on the SECOND `rule` slot, not re-light the first.
    # v3 has three `rule` slots (rules first · split into asks · make each
    # object), which is what makes the ordering matter.
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("rule", "Rules first"))
    p.add_step(_step("rule", "Split"))
    done, active = _rail_state(p._rail)
    assert "rules first" in done
    assert active == "split into asks"


def test_a_finished_run_leaves_no_slot_active(hud):
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.finish({"message": "ok", "brain": "engine-v2"})
    assert p._rail._finished and p._rail._active is None
    assert "fix words" in {p._rail._slots[i][1] for i in p._rail._done}


def test_the_info_dot_shows_the_in_depth_copy_on_a_real_click(hud):
    # The ⓘ is a control — click it, don't call the handler. It must carry the
    # explorer-depth copy and not raise when tapped (offscreen shows nothing).
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from assistant.calendar_ui.thinking_panel import _InfoDot, _Theme
    dot = _InfoDot("Fix words", "corrected against your personal vocabulary", _Theme(True))
    assert "Fix words" in dot.toolTip()
    assert "vocabulary" in dot.toolTip()
    QTest.mouseClick(dot, Qt.MouseButton.LeftButton)   # must not raise


# ---------------------------------------------------------------------------
# The rail's live spinner + elapsed counter on the row in progress
# ---------------------------------------------------------------------------
#
# Passive rendering, so the real analog of "drive the widget, don't call the
# handler" is: feed the real _ChainRail a real step stream, let a real QTimer
# tick a few times (QTest.qWait, not a mocked clock), and read the actual
# widgets it moved — not the private counters that decided them.

def _row_for(rail, label):
    """The live row tuple for a chain slot, by its label text."""
    for row in rail._rows:
        i = row[0]
        if rail._slots[i][1] == label:
            return row
    raise AssertionError(f"no row for {label!r} — slots are {[s[1] for s in rail._slots]}")


def _secs(text: str) -> float:
    assert text.endswith(" s"), f"not a seconds label: {text!r}"
    return float(text[:-2])


def test_the_active_row_gets_a_live_increasing_timer_and_a_spinner(hud):
    from PyQt6.QtTest import QTest
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.add_step(_step("rule", "Rules"))          # "rules first" is now active
    rail = p._rail
    assert not rail._finished

    _, _stage, _icon, _text, time_lbl, mark_stack, _state, spinner = _row_for(rail, "rules first")

    # It's the slot in progress: the spinner occupies the mark slot and is
    # actually ticking, not merely constructed.
    assert mark_stack.currentWidget() is spinner
    assert spinner._timer.isActive(), "the active row's spinner is not animating"

    QTest.qWait(150)
    app.processEvents()
    first = _secs(time_lbl.text())
    QTest.qWait(150)
    app.processEvents()
    second = _secs(time_lbl.text())

    assert second > first, f"live counter did not advance: {first} -> {second}"

    # A slot the run hasn't reached yet shows neither a mark nor a time.
    untouched = _row_for(rail, "judge")
    assert untouched[6].text() == ""            # state label
    assert untouched[4].text() == ""            # time label


def test_finishing_freezes_the_time_and_stops_the_spinner(hud):
    from PyQt6.QtTest import QTest
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.add_step(_step("rule", "Rules"))
    rail = p._rail

    _, _, _, _, active_time, active_stack, active_state, active_spinner = _row_for(rail, "rules first")
    QTest.qWait(150)
    app.processEvents()
    assert active_stack.currentWidget() is active_spinner
    assert active_spinner._timer.isActive()

    p.finish({"message": "ok", "brain": "engine-v2"})
    app.processEvents()

    # The row that was live when the run ended: done, spinner gone, its own
    # elapsed span frozen as a normal seconds label.
    assert active_stack.currentWidget() is active_state
    assert active_state.text() == "✓"
    assert not active_spinner._timer.isActive(), "the spinner kept animating after finish()"
    assert _secs(active_time.text()) >= 0

    # A row the run passed through earlier already had a real step to source
    # its duration from — also frozen, in the same "N.NN s" shape as the raw
    # per-step timeline below it.
    _, _, _, _, done_time, done_stack, done_state, done_spinner = _row_for(rail, "fix words")
    assert done_state.text() == "✓"
    assert done_stack.currentWidget() is done_state
    assert not done_spinner._timer.isActive()
    assert _secs(done_time.text()) > 0

    # Never reached at all: the not-needed mark, no time, and not accidentally
    # given a duration. "judge" is folded away on a run this short, so this
    # reads the row that stands behind the fold — the mark is what an unfolded
    # chain shows.
    _, _, _, _, skip_time, _sstack, skip_state, skip_spinner = _row_for(rail, "judge")
    assert skip_state.text() == rail.SKIP_MARK
    assert skip_time.text() == ""
    assert not skip_spinner._timer.isActive()


def test_the_not_needed_mark_fits_the_box_it_is_drawn_in(hud):
    """The mark shares a 14×14 box with the ✓ and the spinner.

    This used to be the word "skipped", which clipped to its two middle
    characters and shipped as "pp" — green, because the test read the label's
    text back and never looked at the pixels. One glyph is the contract; the
    row says the rest in a tooltip.
    """
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.finish({"message": "ok", "brain": "engine-v2"})
    app.processEvents()

    rail = p._rail
    _, _, _, _, _, mark_stack, state, _ = _row_for(rail, "judge")
    assert len(rail.SKIP_MARK) == 1, f"{rail.SKIP_MARK!r} cannot fit a 14px box"
    assert state.text() == rail.SKIP_MARK
    assert rail.SKIP_TIP in state.toolTip()
    # Measured, not assumed: what the label wants is what the box gives it.
    box = mark_stack.parentWidget()
    assert state.sizeHint().width() <= box.width(), (
        f"the mark {state.text()!r} needs {state.sizeHint().width()}px in a "
        f"{box.width()}px box — it will render clipped")


# ---------------------------------------------------------------------------
# Folding the road not taken
# ---------------------------------------------------------------------------
#
# The rail drew all eight slots however few the run walked: on a fast-lane
# answer that is four icons, four labels and four marks for a chain nothing
# went down — 42% of a fixed 440px card. It still shows every slot WHILE the
# run is in flight, where the unlit ones are what is coming next.

def _visible_slots(rail) -> set:
    return {rail._slots[i][1] for i in range(len(rail._slots))
            if not rail._hosts[i].isHidden()}


def test_every_slot_is_on_screen_while_the_run_is_still_going(hud):
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    app.processEvents()

    rail = p._rail
    assert rail.folded_slots() == set()
    assert _visible_slots(rail) == {label for _stage, label in rail._slots}


def test_a_finished_run_folds_the_slots_it_never_reached(hud):
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.add_step(_step("rule", "Rule parser"))
    p.finish({"message": "ok", "brain": "engine-v2"})
    app.processEvents()

    rail = p._rail
    folded = {rail._slots[i][1] for i in rail.folded_slots()}
    # Everything it walked stays; the tail it never reached goes behind one line.
    assert {"fix words", "rules first"} <= _visible_slots(rail)
    assert "judge" in folded and "write · label" in folded
    assert not folded & _visible_slots(rail)

    # isHidden(), not isVisible(): the HUD itself is never shown in the suite,
    # so every descendant reports invisible however it was configured.
    fold = rail._folds[min(rail.folded_slots())]
    assert not fold.isHidden()
    assert str(len(rail.folded_slots())) in fold.text()


def test_clicking_the_fold_puts_the_whole_chain_back(hud):
    """A real mouse click on the real control — the fold is how the rest of
    the chain is reachable at all, so a test that called the handler would
    prove nothing about whether anyone can get to it."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.finish({"message": "ok", "brain": "engine-v2"})
    app.processEvents()

    rail = p._rail
    hidden_before = rail.folded_slots()
    assert hidden_before, "nothing was folded, so there is nothing to click"
    fold = rail._folds[min(hidden_before)]

    QTest.mouseClick(fold, Qt.MouseButton.LeftButton)
    app.processEvents()

    assert rail.folded_slots() == set()
    assert _visible_slots(rail) == {label for _stage, label in rail._slots}
    assert fold.isHidden()


def test_a_late_step_unfolds_the_chain_it_is_walking_again(hud):
    """The background self-check reopens a finished timeline. Its slot may be
    one of the folded ones — lighting a hidden row would light nothing."""
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    p.finish({"message": "ok", "brain": "engine-v2"})
    app.processEvents()
    assert p._rail.folded_slots(), "precondition: the tail was folded away"

    rail = p._rail
    p.add_step(_step("verify", "Reviewed the answer"))
    app.processEvents()

    assert rail.folded_slots() == set()
    assert "judge" in _visible_slots(rail)
    assert rail._slots[rail._active][1] == "judge"


def test_a_freshly_lit_slot_resets_its_own_timer(hud):
    """Each slot's live counter starts from zero when IT becomes active, not
    from whenever the rail itself was created."""
    from PyQt6.QtTest import QTest
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("vocab", "Vocabulary"))
    rail = p._rail
    QTest.qWait(200)                            # "fix words" ticks for a while
    app.processEvents()

    p.add_step(_step("rule", "Rules"))          # "rules first" only just lit
    app.processEvents()
    _, _, _, _, new_time, _stack, _state, _spinner = _row_for(rail, "rules first")
    assert _secs(new_time.text()) < 0.1, \
        f"new active row started at {new_time.text()!r}, not close to zero"


# ---------------------------------------------------------------------------
# One-tap revert of a destructive background patch
# ---------------------------------------------------------------------------

def test_a_destructive_patch_step_shows_a_revert_button(hud):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    got = []
    p.revert_requested.connect(lambda specs: got.append(specs))
    spec = {"kind": "todo", "body": {"title": "buy groceries", "list_name": "today"}}
    p.add_step({"stage": "verify", "title": "Reviewed the answer",
                "detail": "I removed a task I created by mistake.", "ms": 0,
                "at_ms": 0, "ok": False, "data": {"revert": [spec]}})
    assert len(p._notices) == 1
    bar = p._notices[-1]
    QTest.mouseClick(bar._btn, Qt.MouseButton.LeftButton)   # a real click, not the handler
    assert got == [[spec]]
    assert not bar._btn.isEnabled() and bar._btn.text() == "Reverted"


def test_a_plain_step_shows_no_revert_button(hud):
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    p.add_step(_step("execute", "Create Todo"))
    assert p._notices == []


# ---------------------------------------------------------------------------
# The two non-object outcomes
# ---------------------------------------------------------------------------
#
# An item that leaves the object stage without an object is one of two very
# different things, and the panel is where they are told apart: "this wasn't
# calendar work" is the engine reading correctly, "this reached me damaged" is
# an upstream defect. Drawn the same way, the card tells the reader they are
# the same event.

def _outcome_step(outcome, ok=True, title="Read part 1"):
    return {"stage": "rule", "title": title,
            "detail": "“play some music” — nothing writable here.",
            "ms": 30, "at_ms": 30, "ok": ok, "data": {"outcome": outcome}}


def _row_with(p, step):
    p.add_step(step)
    return p._rows[-1]


def test_a_non_calendar_ask_is_labelled_as_one(hud):
    from assistant.engine.fastrule import objects
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    row = _row_with(p, _outcome_step(objects.NOT_AN_ASK))
    assert row._outcome is not None
    assert row._outcome.text() == "not calendar work"


def test_a_damaged_item_is_labelled_as_damage(hud):
    from assistant.engine.fastrule import objects
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    row = _row_with(p, _outcome_step(objects.BAD_ITEM, ok=False))
    assert row._outcome is not None
    assert row._outcome.text() == "reached me damaged"


def test_the_two_outcomes_do_not_look_the_same(hud):
    """The whole point of the feature. A correct reading is muted; a defect is
    amber — this file's standing rule, where red stays reserved for fatal."""
    from assistant.engine.fastrule import objects
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    ask = _row_with(p, _outcome_step(objects.NOT_AN_ASK))
    bad = _row_with(p, _outcome_step(objects.BAD_ITEM, ok=False, title="Read part 2"))

    assert ask._outcome.text() != bad._outcome.text()
    assert ask._outcome.styleSheet() != bad._outcome.styleSheet()
    assert p._theme.orange in bad._outcome.styleSheet()
    assert p._theme.orange not in ask._outcome.styleSheet()
    assert p._theme.destructive not in bad._outcome.styleSheet(), \
        "red is reserved for the error stage; a flagged item is not fatal"


def test_an_ordinary_step_gets_no_label(hud):
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    row = _row_with(p, _step("rule", "Rule parser", "confident"))
    assert row._outcome is None


def test_an_outcome_the_panel_does_not_know_is_ignored_not_drawn(hud):
    """A newer engine's outcome must not render as a blank chip or crash the
    card — the panel draws what it knows and stays quiet about the rest."""
    widget, _, _ = hud
    p = widget.panel
    p.begin("Mac")
    row = _row_with(p, _outcome_step("some_future_outcome"))
    assert row._outcome is None


def test_an_outcome_row_still_fits_inside_the_card(hud):
    """Measured, not eyeballed. A step row whose minimum width exceeds the
    card does not wrap — it clips on the right, and what goes missing is the
    end of every line. Adding the chip beside the title did exactly that on
    the first cut, and no assertion about its TEXT would have caught it."""
    from assistant.calendar_ui.thinking_panel import PANEL_WIDTH
    from assistant.engine.fastrule import objects
    widget, _, app = hud
    p = widget.panel
    p.begin("Mac")
    for outcome in (objects.NOT_AN_ASK, objects.BAD_ITEM):
        row = _row_with(p, _outcome_step(outcome))
        app.processEvents()
        need = row.minimumSizeHint().width()
        assert need <= PANEL_WIDTH, (
            f"the {outcome!r} row needs {need}px in a {PANEL_WIDTH}px card — "
            "it will render clipped")

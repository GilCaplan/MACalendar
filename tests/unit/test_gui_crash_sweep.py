"""Click everything in the Mac app; nothing may crash it (Gil, 2026-09-29:
"Test all features on MACalendar in the laptop to see where the app might
crash and fix").

PyQt ABORTS the whole app on an exception raised inside a click handler —
the calendar density checkbox took the calendar down that way the same day.
So this builds the real CalendarWindow on scratch data (conftest redirects
every store and refuses the live API, so nothing here can reach the real
calendar), installs an excepthook that RECORDS instead of aborting, and
walks every surface:

    the four calendar views and every sidebar panel,
    every button, checkbox, combo box, spin box and line edit on each,
    the More menu's actions, the toolbar search, and
    every modal a click opens — explored one level down, then closed.

What reaches outside the process is stubbed so a click cannot open a
browser, launch an app, record from the microphone, speak or wait on a
file picker. Each exception is reported with the path of clicks that
raised it.
"""

from __future__ import annotations

import datetime
import sys
import traceback

import pytest

pytestmark = pytest.mark.filterwarnings("ignore")

#: Words on a control that mean "leave the process" or "start the mic".
_SKIP_WORDS = ("microphone", "mic_", "record", "quit", "sign out", "log out",
               "open jude", "terminal", "install", "restart")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def scratch_restored(tmp_path_factory):
    """Put the session's scratch stores back exactly as they were. The sweep
    presses Save in Settings and deletes rows; the tests after it share that
    scratch directory (conftest), and a run of them failed on the sweep's
    leftovers until this existed."""
    import os
    import shutil
    scratch = os.path.dirname(os.environ["MACALENDAR_CONFIG"])
    keep = tmp_path_factory.mktemp("scratch-before") / "copy"
    shutil.copytree(scratch, keep)
    yield
    for name in os.listdir(scratch):
        target = os.path.join(scratch, name)
        (shutil.rmtree if os.path.isdir(target) and not os.path.islink(target)
         else os.remove)(target)
    shutil.copytree(keep, scratch, dirs_exist_ok=True)


@pytest.fixture
def quarantine(monkeypatch):
    """Nothing a click does may leave this process."""
    # The mic's audio library finds PortAudio with a real subprocess
    # (ctypes.util.find_library -> ldconfig) on its FIRST import. In the
    # shared suite an earlier file already did that; run alone (CI runs each
    # Qt file in its own process, 2026-10-06) it happened under the stub below
    # and failed. Do it here, for real, before Popen is replaced.
    try:
        import sounddevice  # noqa: F401
    except OSError:
        pass
    import subprocess
    import webbrowser
    from PyQt6.QtGui import QColor, QDesktopServices
    from PyQt6.QtWidgets import QColorDialog, QFileDialog, QFontDialog, QInputDialog

    class _Done:
        """A process that ran and printed nothing. A context manager with
        readable (empty) pipes too: ctypes.util.find_library runs
        `with Popen(["/sbin/ldconfig", "-p"]) as p: p.stdout.read()` the first
        time a library is looked up, which in a process of its own (CI runs
        each Qt file alone, 2026-10-06) happens inside this test."""
        returncode, pid = 0, 0

        def __init__(self, *a, **k):
            import io
            self.stdout, self.stderr = io.BytesIO(b""), io.BytesIO(b"")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, *a, **k):
            return "", ""

        def wait(self, *a, **k):
            return 0

        def poll(self):
            return 0

        def kill(self):
            pass

        terminate = kill

    monkeypatch.setattr(subprocess, "Popen", _Done)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done())
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: 0)
    monkeypatch.setattr(subprocess, "check_call", lambda *a, **k: 0)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: b"")
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda *a: True))
    for name in ("getOpenFileName", "getSaveFileName", "getOpenFileNames"):
        monkeypatch.setattr(QFileDialog, name, staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor()))
    monkeypatch.setattr(QFontDialog, "getFont", staticmethod(lambda *a, **k: (None, False)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (0, False)))


def _seed() -> None:
    """A calendar with something in every view: events today, this week, a
    series, a late one, an all-day one; to-dos due and undated; an occasion."""
    from assistant.actions.calendar.intent import CalendarIntent
    from assistant.db import CalendarDB
    from assistant.occasions import store as occasions
    from assistant.users import paths
    import os
    db = CalendarDB(paths.resolve(os.environ["MACALENDAR_DB"]))
    t = datetime.date.today()
    for d, s, e, title, rec in [
            (t, "09:00", "10:00", "standup", None), (t, "09:30", "10:30", "overlap", None),
            (t, "22:30", "23:30", "late call", None),
            (t + datetime.timedelta(days=1), "13:00", "14:00", "lunch", None),
            (t + datetime.timedelta(days=2), "07:00", "08:00", "gym", "weekly")]:
        kw = {"recurrence": rec} if rec else {}
        db.create_event(CalendarIntent(title=title, date=d.isoformat(), start_time=s,
                                       end_time=e, **kw))
    tid = db.create_todo("buy milk", due_date=t.isoformat(), tags=["Groceries"], notes="2 cartons")
    db.create_todo("renew passport", list_name="general", priority="high")
    db.create_subtask(tid, "check the fridge")
    db.create_linked_todo(1)
    course = db.create_course("236501", "Intro to AI", "#8b5cf6", [])
    db.create_assignment(course, "HW 1", (t + datetime.timedelta(days=3)).isoformat())
    timer = db.create_timer("Client work", hourly_rate=100)
    db.create_timer_session(timer, "first session")
    db.create_counter("Push-ups", price_per_unit=1)
    occasions.add({"kind": "birthday", "title": "Dana", "calendar": "gregorian",
                   "month": t.month, "day": t.day})


class _Sweep:
    def __init__(self, app):
        self.app = app
        self.raised: list = []
        self.path: list[str] = []
        self.clicks = 0
        self.seen_modals: set = set()
        self._open: list = []                 # the dialogs being explored, outermost first
        from assistant.calendar_ui import styles
        self._dark_before = styles._dark

    # -- the harness ---------------------------------------------------------------

    def hook(self, etype, value, tb):
        self.raised.append((" › ".join(self.path), "".join(
            traceback.format_exception(etype, value, tb))[-2500:]))

    def settle(self):
        from PyQt6.QtCore import QCoreApplication, QEvent
        for _ in range(3):
            self.app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

    def label(self, w) -> str:
        for get in ("text", "placeholderText", "toolTip", "objectName"):
            try:
                v = getattr(w, get)()
            except Exception:
                continue
            if v:
                return f"{type(w).__name__}[{str(v).splitlines()[0][:40]}]"
        return type(w).__name__

    def skip(self, w) -> bool:
        text = " ".join(str(getattr(w, g)()) for g in ("text", "toolTip", "objectName")
                        if hasattr(w, g)).lower()
        return any(s in text for s in _SKIP_WORDS)

    # -- one surface ---------------------------------------------------------------

    _CLOSERS = ("save", "ok", "cancel", "close", "done", "delete", "remove", "unlink",
                "apply", "discard", "revert", "sign", "archive", "clear", "reset")

    def controls(self, root):
        """Everything clickable under ``root`` — the ones that usually CLOSE
        a dialog or destroy a row last, so the rest are reached first."""
        from PyQt6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox,
                                     QLineEdit)
        from PyQt6 import sip
        if sip.isdeleted(root):
            return []            # a click closed it (WA_DeleteOnClose): nothing left to walk
        out = []
        for cls in (QAbstractButton, QComboBox, QAbstractSpinBox, QLineEdit):
            out += [w for w in root.findChildren(cls)]
        # a spin box's or combo box's own text field is driven through its owner
        out = [w for w in out if not (isinstance(w, QLineEdit)
                                      and isinstance(w.parent(), (QAbstractSpinBox, QComboBox)))]

        def closing(w):
            try:
                t = (w.text() or "").lower()
            except Exception:
                return False
            return any(c in t for c in self._CLOSERS)
        return [w for w in out if not closing(w)] + [w for w in out if closing(w)]

    def log(self, msg: str):
        import os
        path = os.environ.get("SWEEP_LOG")
        if path:
            with open(path, "a") as f:
                f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")

    def start_watchdog(self):
        """Close what nobody is exploring: a popup menu (a context menu's
        exec() blocks like a modal) or a modal that outlived its explorer."""
        from PyQt6.QtCore import QTimer
        self._exploring = 0
        self._dog = QTimer()
        self._dog.setInterval(200)
        self._dog.timeout.connect(self._bark)
        self._dog.start()

    def _bark(self):
        from PyQt6.QtWidgets import QApplication, QDialog
        pop = QApplication.activePopupWidget()
        if pop is not None:
            self.log(f"watchdog closed popup {type(pop).__name__}")
            pop.close()
        m = QApplication.activeModalWidget()
        if m is not None and not self._exploring:
            self._stale = getattr(self, "_stale", 0) + 1
            if self._stale >= 5:            # a second with nobody on it
                self.log(f"watchdog closed modal {type(m).__name__} {m.windowTitle()!r}")
                self._stale = 0
                (m.reject if isinstance(m, QDialog) else m.close)()
        else:
            self._stale = 0

    def finish(self):
        """Leave nothing running for the tests after this one: the watchdog
        would go on closing their dialogs, and a window left open answers
        their clicks."""
        from PyQt6.QtWidgets import QApplication
        dog = getattr(self, "_dog", None)
        if dog is not None:
            dog.stop()
            dog.deleteLater()
        for win in QApplication.topLevelWidgets():
            if win.isVisible():
                win.close()
        self.settle()
        # process-wide state a click can change: who this process acts as
        # (requiring sign-in pins it), the theme, the view preferences
        from assistant import users
        from assistant.calendar_ui import styles, view_prefs
        users.set_process_default(None)
        styles._dark = self._dark_before
        view_prefs.apply(None)

    def poke(self, w, depth: int):
        from PyQt6 import sip
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox,
                                     QLineEdit, QToolButton)
        if sip.isdeleted(w) or not w.isVisible() or not w.isEnabled() or self.skip(w):
            return
        self.path.append(self.label(w))
        self.clicks += 1
        self.log(" › ".join(self.path))
        try:
            if isinstance(w, QToolButton) and w.menu() is not None:
                for act in list(w.menu().actions()):
                    if act.isEnabled() and not act.isSeparator() and \
                            not any(s in act.text().lower() for s in _SKIP_WORDS):
                        self.path.append(f"menu[{act.text()}]")
                        self.arm(depth)
                        act.trigger()
                        self.settle()
                        self.path.pop()
            elif isinstance(w, QAbstractButton):
                self.arm(depth)
                QTest.mouseClick(w, Qt.MouseButton.LeftButton)
                self.settle()
            elif isinstance(w, QComboBox):
                start = w.currentIndex()
                for i in range(min(w.count(), 12)):
                    if sip.isdeleted(w):
                        break
                    self.arm(depth)
                    w.setCurrentIndex(i)
                    self.settle()
                if not sip.isdeleted(w):
                    w.setCurrentIndex(start)
            elif isinstance(w, QAbstractSpinBox):
                for step in (1, -1):
                    if sip.isdeleted(w):
                        break
                    w.stepBy(step)
                    self.settle()
            elif isinstance(w, QLineEdit) and not w.isReadOnly():
                old = w.text()
                self.arm(depth)
                QTest.keyClicks(w, "test 3pm")
                if depth == 0:
                    # in a dialog, Return presses its default button (Save)
                    # and ends the exploration of every page after this one
                    QTest.keyClick(w, Qt.Key.Key_Return)
                else:
                    w.editingFinished.emit()
                self.settle()
                if not sip.isdeleted(w):
                    w.setText(old)
        except Exception:
            self.hook(*sys.exc_info())
        finally:
            self.path.pop()

    _STACKS = None

    def _stack_types(self):
        from PyQt6.QtWidgets import QStackedWidget, QTabWidget
        return (QStackedWidget, QTabWidget)

    def _nearest_stack(self, w, root):
        stacks = self._stack_types()
        p = w.parent()
        while p is not None and p is not root:
            if isinstance(p, stacks):
                return p
            p = p.parent()
        return None

    def sweep(self, root, depth: int = 0, limit: int = 400, restore=None):
        """Every page of every stack under ``root`` (each shown in turn), then
        the loose controls, then the widgets with their own mouse handlers."""
        from PyQt6 import sip
        from PyQt6.QtWidgets import QTabWidget
        stacks = [sw for sw in root.findChildren(self._stack_types())
                  if self._nearest_stack(sw, root) is None]
        for sw in stacks:
            for i in range(sw.count() if not sip.isdeleted(sw) else 0):
                if sip.isdeleted(sw):
                    break
                self.path.append(f"page[{i}]")
                try:
                    sw.setCurrentIndex(i)
                    self.settle()
                    page = sw.widget(i)
                    if page is not None and not sip.isdeleted(page):
                        self.sweep(page, depth, limit, restore)
                except Exception:
                    self.hook(*sys.exc_info())
                self.path.pop()
        done = set()
        for _ in range(3):                   # a click can add controls; look again
            if sip.isdeleted(root):
                break
            fresh = [w for w in self.controls(root)
                     if id(w) not in done and self._nearest_stack(w, root) is None
                     and not sip.isdeleted(w) and w.isVisible()]
            if not fresh:
                break
            for w in fresh[:limit]:
                done.add(id(w))
                if sip.isdeleted(root) or not root.isVisible():
                    return
                self.poke(w, depth)
                if restore:
                    restore()
        self.mouse(root, depth, restore)

    def mouse(self, root, depth: int, restore=None, per_class: int = 3):
        """Click, double-click and right-click the custom widgets that take
        the mouse themselves — event blocks, day cells, task rows."""
        from PyQt6 import sip
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtGui import QContextMenuEvent
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication, QWidget
        counts: dict = {}
        for w in root.findChildren(QWidget):
            cls = type(w)
            if not cls.__module__.startswith("assistant") or sip.isdeleted(w) \
                    or not w.isVisible() or self._nearest_stack(w, root) is not None:
                continue
            handlers = [h for h in ("mousePressEvent", "mouseDoubleClickEvent",
                                    "contextMenuEvent") if h in vars(cls)]
            if not handlers or counts.get(cls, 0) >= per_class:
                continue
            counts[cls] = counts.get(cls, 0) + 1
            self.path.append(f"{cls.__name__}")
            try:
                pt = QPoint(max(1, min(8, w.width() // 2)), max(1, min(8, w.height() // 2)))
                for how in ("click", "double", "right"):
                    if sip.isdeleted(w) or not w.isVisible():
                        break
                    self.path.append(how)
                    self.clicks += 1
                    self.log(" › ".join(self.path))
                    self.arm(depth)
                    if how == "click":
                        QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=pt)
                    elif how == "double":
                        QTest.mouseDClick(w, Qt.MouseButton.LeftButton, pos=pt)
                    else:
                        QApplication.sendEvent(w, QContextMenuEvent(
                            QContextMenuEvent.Reason.Mouse, pt, w.mapToGlobal(pt)))
                    self.settle()
                    self.path.pop()
                    if restore:
                        restore()
            except Exception:
                self.hook(*sys.exc_info())
                self.path = self.path[:self.path.index(cls.__name__)]
                continue
            self.path.pop()

    # -- modals a click opens --------------------------------------------------------

    def arm(self, depth: int):
        """If this click opens a modal, explore it (one level down) and close it."""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, lambda: self._on_modal(depth, 0))

    def _on_modal(self, depth: int, tries: int):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
        m = QApplication.activeModalWidget()
        if m is not None and any(m is x for x in self._open):
            m = None                          # the dialog we are already inside
        if m is None:
            if tries < 3:
                QTimer.singleShot(30, lambda: self._on_modal(depth, tries + 1))
            return
        from PyQt6.QtTest import QTest
        QTest.qWait(120)                      # let it finish showing its contents
        from PyQt6 import sip
        if sip.isdeleted(m) or not m.isVisible():
            return
        key = type(m).__name__ + (m.windowTitle() or "")
        self.log(f"modal seen {key} depth={depth} explored_before={key in self.seen_modals}")
        self.path.append(f"modal[{key}]")
        self._exploring += 1
        self._open.append(m)
        try:
            if depth < 2 and not isinstance(m, QMessageBox) and key not in self.seen_modals:
                self.seen_modals.add(key)
                self.sweep(m, depth + 1, limit=150)
        except Exception:
            self.hook(*sys.exc_info())
        finally:
            self._exploring -= 1
            self._open.pop()
            self.path.pop()
            from PyQt6 import sip
            if not sip.isdeleted(m) and m.isVisible():
                if isinstance(m, QDialog):
                    m.reject()
                else:
                    m.close()


def _real_data_copy() -> bool:
    """``SWEEP_REAL_DATA=1``: sweep a COPY of this Mac's own calendar, to-dos,
    categories, vocabulary and command memory instead of the seed — the data
    shapes a seed never thinks of. The originals are only read; the copies
    land on the scratch paths conftest already points every store at. Off by
    default and never in CI."""
    import os
    import shutil
    from pathlib import Path
    if os.environ.get("SWEEP_REAL_DATA") != "1":
        return False
    home = Path.home() / ".assistant_tools" / "users"
    src = next((d for d in sorted(home.glob("u_*")) if (d / "calendar.db").exists()), None)
    if src is None:
        pytest.skip("no personal calendar on this machine")
    for var, name in (("MACALENDAR_DB", "calendar.db"), ("MACALENDAR_MEMORY_DB", "nlu_memory.db"),
                      ("MACALENDAR_VOCAB", "vocab.json"), ("MACALENDAR_CATEGORIES", "categories.json"),
                      ("MACALENDAR_OCCASIONS", "occasions.json")):
        if (src / name).exists():
            shutil.copyfile(src / name, os.environ[var])
    return True


def test_click_everything_nothing_crashes(app, quarantine, monkeypatch, tmp_path):
    from assistant import users
    from assistant.calendar_ui.window import CalendarWindow
    from assistant.config import load_config
    from assistant.users import local_session, registry, sessions
    # two people, the admin signed in — so the Account panel and sharing have
    # something to show (users are per-test scratch files)
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("MACALENDAR_SESSION_FILE", str(tmp_path / "session.json"))
    real = _real_data_copy()
    if not real:
        admin = registry.create_user("gil", "admin-pass", role="admin")
        registry.create_user("dana", "dana-pass")
        uid = admin["id"] if isinstance(admin, dict) else admin
        local_session.write(uid, registry.get(uid)["username"],
                            registry.get(uid)["display_name"], sessions.issue(uid))
        _seed()
    users.set_process_default(None)
    s = _Sweep(app)
    monkeypatch.setattr(sys, "excepthook", s.hook)
    s.start_watchdog()

    class _Tts:
        mute, voice, rate = False, "Samantha", 200

        def speak(self, *a, **k):
            pass

    class _Pipeline:
        _tts = _Tts()
        current_view = "month"

        def __getattr__(self, name):          # anything else the window asks of it
            return lambda *a, **k: None

    w = CalendarWindow(config=load_config().model_copy(deep=True))
    w._pipeline = _Pipeline()
    w.resize(1400, 900)
    w.show()
    s.settle()

    modes = list(w._CALENDAR_MODES) + list(getattr(w, "_panels", {}).keys())
    for mode in modes:
        s.path = [f"view[{mode}]"]
        try:
            w._set_view(mode)
            s.settle()
        except Exception:
            s.hook(*sys.exc_info())
            continue

        def back(mode=mode):
            if not w.isVisible():
                w.show()
            if w._view_mode != mode:
                w._set_view(mode)
                s.settle()
        s.sweep(w._stack.currentWidget(), restore=back)
    # the chrome around the views, once — minus the buttons that switch view,
    # which the loop above already drove
    s.path = ["chrome"]
    w._set_view("month")
    s.settle()
    back_to_month = lambda: (w._view_mode != "month") and (w._set_view("month"), s.settle())
    for root in (w._toolbar_bar, w._sidebar):
        s.sweep(root, restore=back_to_month)
    # the calendar views again: travelled through, in light mode, and squeezed
    for label, prep in (("navigate", None),
                        ("light", lambda: w._apply_theme(False)),
                        ("narrow", lambda: w.resize(640, 480))):
        s.path = [label]
        try:
            if prep:
                prep()
                s.settle()
            for mode in w._CALENDAR_MODES:
                s.path = [label, f"view[{mode}]"]
                w._set_view(mode)
                s.settle()
                for step in ([w._on_next] * 3 + [w._on_prev] * 6 + [w._on_today]):
                    step()
                    s.settle()
                s.mouse(w._stack.currentWidget(), 0)
        except Exception:
            s.hook(*sys.exc_info())
    w.resize(1400, 900)
    s.path = ["settings"]
    try:
        from assistant.calendar_ui.settings_dialog import open_settings
        s.arm(0)
        open_settings(w)
        s.settle()
    except Exception:
        s.hook(*sys.exc_info())

    s.finish()
    report = "\n\n".join(f"#{i + 1} at {p}\n{tb}" for i, (p, tb) in enumerate(s.raised))
    print(f"\nclicks: {s.clicks}  modals explored: {sorted(s.seen_modals)}")
    assert not s.raised, f"{len(s.raised)} exception(s) from clicks:\n\n{report}"


class _FakeStack:
    """The menu-bar app's processes, none of them real."""
    port = 8080

    def start(self, api=True):
        return []

    def stop(self):
        pass

    stop_api = stop

    def status(self):
        return {}

    def pull_model(self):
        return True


#: Menu-bar entries that reach the rest of the Mac even from a test: a login
#: item, the running thinking card, Jude, quitting.
_TRAY_SKIP = ("open at login", "show thinking card", "open jude", "quit")


def test_the_card_and_the_menu_bar_app_survive_every_click(app, quarantine, monkeypatch, tmp_path):
    import assistant.thinking_hud as hud_mod
    from PyQt6.QtCore import QSettings
    from assistant.host import tray as tray_mod
    s = _Sweep(app)
    monkeypatch.setattr(sys, "excepthook", s.hook)
    s.start_watchdog()

    # the thinking card, every view of it
    monkeypatch.setattr(hud_mod, "STATE_PATH", str(tmp_path / "pos.json"))
    s.path = ["hud"]
    try:
        from PyQt6.QtWidgets import QPushButton
        hud = hud_mod.ThinkingHUD(None)
        hud.show()
        s.settle()
        views = [b for b in hud.findChildren(QPushButton) if b.text() in ("Graph", "History", "LLM")]
        chrome = set(views) | {b for b in hud.findChildren(QPushButton) if b.text() in ("–", "×")}
        for v in views + views[:1]:           # each view, then back to the first
            s.path = ["hud", f"view[{v.text()}]"]
            s.poke(v, 0)
            for w in [c for c in s.controls(hud) if c not in chrome]:
                s.poke(w, 0)
                if not hud.isVisible():
                    hud.show()
            s.mouse(hud, 0)
        hud.close()
    except Exception:
        s.hook(*sys.exc_info())

    # the menu-bar app: every menu entry, and the windows they open
    s.path = ["tray"]
    try:
        t = tray_mod.HostTray(app, stack=_FakeStack(), start=False)
        t.timer.stop()
        t._settings = QSettings(str(tmp_path / "host.ini"), QSettings.Format.IniFormat)

        def entries(menu):
            for act in menu.actions():
                if act.menu() is not None:
                    yield from entries(act.menu())
                elif not act.isSeparator():
                    yield act
        for act in list(entries(t.menu)):
            if not act.isEnabled() or any(k in act.text().lower() for k in _TRAY_SKIP):
                continue
            s.path = ["tray", f"menu[{act.text()}]"]
            s.clicks += 1
            s.log(" › ".join(s.path))
            from PyQt6.QtWidgets import QApplication
            before = {id(x) for x in QApplication.topLevelWidgets() if x.isVisible()}
            s.arm(0)
            act.trigger()
            s.settle()
            s.log(f"after {act.text()!r}: " + ", ".join(
                f"{type(x).__name__}:{x.windowTitle()!r}" for x in QApplication.topLevelWidgets()
                if x.isVisible()))
            for win in QApplication.topLevelWidgets():   # a window it opened, not modal
                if win.isVisible() and id(win) not in before:
                    s.path.append(f"window[{type(win).__name__}]")
                    s.log(f"sweeping {win.windowTitle()!r}: {len(s.controls(win))} controls, "
                          f"{sum(1 for c in s.controls(win) if c.isVisible() and c.isEnabled())} live")
                    s.sweep(win)
                    from PyQt6 import sip as _sip
                    if not _sip.isdeleted(win):
                        win.close()
                    s.path.pop()
    except Exception:
        s.hook(*sys.exc_info())

    s.finish()
    report = "\n\n".join(f"#{i + 1} at {p}\n{tb}" for i, (p, tb) in enumerate(s.raised))
    print(f"\nclicks: {s.clicks}  modals explored: {sorted(s.seen_modals)}")
    assert not s.raised, f"{len(s.raised)} exception(s) from clicks:\n\n{report}"

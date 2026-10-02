"""One command, drawn as a graph: the sentence, the asks it split into, who
decided each one, and what each became.

Gil, 2026-09-28: *"in the HUD can you add a more interactive viz option as
well, like a graph, but also that doesn't get too cluttered that is nice and
interactive for user to use"* — and, of the two graphs offered, the COMMAND
graph: what the list view cannot show is how ONE sentence became SEVERAL
objects, and which part of the engine decided each one.

    “dentist fri 3pm and buy milk”
      │  2 asks
      ├── dentist fri 3pm ──(rules)──▶ Event · Fri 2 Oct 15:00
      └── buy milk ─────────(rules)──▶ To-do · today
      ✓ every field traced back to the words · 0.4 s

Kept uncluttered on purpose. One row per ask, and nothing else on the canvas:
stage timings, prompts and the X-values live one CLICK away, in the detail
line under the graph, never drawn all at once. Hovering an ask lights its path
and dims the others; clicking any node says what is behind it.

Two halves, so the reading can be tested without a screen:

  `build_graph(steps, boundaries, result)` → `Graph`   pure data, no Qt
  `CommandGraphView`                                    paints a `Graph`

The graph is read from the TRACE — the same steps and boundaries the timeline
draws — so it needs no engine hook of its own. Boundaries carry `parts` (one
dict per item) since 2026-09-28; an older trace in History has only the clipped
display strings, and those are parsed as a fallback, never required.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

# ----------------------------------------------------------------- the model


@dataclass
class Lane:
    """One ask, from the words that said it to what it became."""
    text: str                       # the ask, as said
    kind: str = ""                  # event / task / other, as segmentation typed it
    time: str = ""                  # the time still as spoken (X2)
    decided_by: str = "rules"       # "rules" | "model"
    decided_ms: int = 0
    decided_detail: str = ""
    action: str = ""                # create_event, create_todo, … ; "" = nothing made
    outcome: str = ""               # the short second line of the outcome node
    outcome_detail: str = ""        # what was written, in full
    junk: str = ""                  # why it was thrown out, when it was
    resolved: dict = field(default_factory=dict)   # X3's fields for this ask


@dataclass
class Graph:
    heard: str = ""                 # X0
    repaired: str = ""              # X1
    fixes: str = ""                 # what the vocabulary step changed, if anything
    path: str = ""                  # "fast" | "deep" | ""
    split_detail: str = ""
    lanes: list = field(default_factory=list)
    loops: int = 0                  # judge loop-backs
    check: str = ""                 # the cross-check's line
    check_ok: "bool | None" = None
    total: str = ""                 # the done step's line
    message: str = ""               # the reply the speaker got
    running: bool = False


def _data(step: dict) -> dict:
    d = step.get("data")
    return d if isinstance(d, dict) else {}


def _ms(step: dict) -> int:
    try:
        return int(step.get("ms") or 0)
    except (TypeError, ValueError):
        return 0


def _last(boundaries: list, label: str) -> "dict | None":
    """The LAST value of a boundary — after a judge loop-back the chain runs
    again and the second pass is the one that was committed."""
    for b in reversed(boundaries or []):
        if (b or {}).get("label") == label:
            return b
    return None


_X2_ITEM = re.compile(r"^\((?P<kind>[^)]*)\)\s*(?P<text>.*?)(?:\s·\s(?P<time>[^·]*))?$")


def _parse_x2(value: str) -> list:
    """An older trace's X2 display string → items. '(event) dentist · fri 3pm |
    (task) buy milk'. Clipped strings lose the tail; that is why `parts` exist."""
    out = []
    for chunk in (value or "").split(" | "):
        chunk = re.sub(r"\s\+\d+ more$", "", chunk.strip()).rstrip("…")
        m = _X2_ITEM.match(chunk)
        if m:
            out.append({"kind": m["kind"].strip(), "text": m["text"].strip(),
                        "time": (m["time"] or "").strip()})
    return out


def _parse_x4(value: str) -> list:
    """An older trace's X4 display string → object lines, built ones only."""
    if not value or value.strip() == "nothing built":
        return []
    out = []
    for line in value.split(" | "):
        line = re.sub(r"\s\+\d+ more$", "", line.strip())
        head, _, rest = line.partition(" · ")
        fields = dict(re.findall(r"(\w+)=([^·]+?)(?=\s·\s|$)", rest))
        out.append({"action": head.strip().replace(" ", "_"),
                    "title": fields.get("title", "").strip(),
                    "date": fields.get("date", "").split(" ")[0],
                    "start_time": fields.get("start_time", "").split(" ")[0],
                    "line": line})
    return out


def _when(part: dict) -> str:
    """'Sun 27 Sep 10:30' from an object's fields — short enough for a node."""
    bits = []
    date = str(part.get("date") or part.get("due_date") or "")
    try:
        d = _dt.date.fromisoformat(date[:10])
        today = _dt.date.today()
        bits.append("today" if d == today else "tomorrow" if d == today + _dt.timedelta(days=1)
                    else d.strftime("%a %-d %b"))
    except ValueError:
        pass
    if part.get("start_time"):
        bits.append(str(part["start_time"])[:5])
    if part.get("recurrence"):
        bits.append(f"every {'day' if part['recurrence'] == 'daily' else str(part['recurrence']).removesuffix('ly')}")
    return " ".join(bits)


_ACTION_LABEL = {
    "create_event": "Event", "create_todo": "To-do",
    "update_event": "Changed event", "update_todo": "Changed to-do",
    "delete_event": "Deleted event", "delete_todo": "Deleted to-do",
    "complete_todo": "Ticked off", "query_schedule": "Looked up",
    "query_todos": "Looked up",
}


def unsupported(check: str) -> str:
    """'date = … — nothing in the words said it; start_time = 10:30' → 'date,
    start_time weren't in the words' — the cross-check line, said short."""
    names = list(dict.fromkeys(re.findall(r"(\w+) = ", check or "")))
    if not names:
        return "a field wasn't in the words"
    return f"{', '.join(names)} {'was' if len(names) == 1 else 'were'}n't in the words"


def action_label(action: str) -> str:
    return _ACTION_LABEL.get(action, action.replace("_", " ").capitalize() if action else "Nothing")


_PART_N = re.compile(r"part\s+(?:r\d+_)?(\d+)", re.I)


def build_graph(steps: list, boundaries: list | None = None,
                result: dict | None = None, heard: str = "",
                running: bool = False) -> Graph:
    """Read one command's trace into a `Graph`. Never raises on odd input — a
    display must not be able to fail — it draws what it could read."""
    steps = [s for s in (steps or []) if isinstance(s, dict)]
    result = result or {}
    boundaries = list(boundaries or []) or list(result.get("boundaries") or [])
    g = Graph(running=running, message=str(result.get("message") or ""))

    # -- the sentence ------------------------------------------------------
    g.heard = heard
    for s in steps:
        if s.get("stage") == "stt" and not g.heard:
            g.heard = str(_data(s).get("transcript") or s.get("detail") or "")
        if s.get("stage") == "vocab":
            g.repaired = str(_data(s).get("transcript") or "")
            det = str(s.get("detail") or "")
            if det and not det.lower().startswith("no correction"):
                g.fixes = det
    x1 = _last(boundaries, "X1")
    if x1 and x1.get("value"):
        g.repaired = str(x1["value"])
    g.heard = g.heard or str(result.get("transcript") or g.repaired)
    g.repaired = g.repaired or g.heard

    for s in steps:
        if s.get("stage") == "done":
            g.path = str(_data(s).get("path") or g.path)
            g.total = str(s.get("detail") or "")
        elif s.get("stage") == "verify" and s.get("title") == "Looping back":
            g.loops += 1
        elif s.get("stage") == "verify":
            g.check = str(s.get("detail") or "")
            g.check_ok = bool(s.get("ok", True))
    if not g.path:
        g.path = "fast" if any(s.get("title") == "Fast answer" for s in steps) else (
            "deep" if _last(boundaries, "X2") else "")

    # -- the lanes ---------------------------------------------------------
    x2, x3, x4 = (_last(boundaries, k) for k in ("X2", "X3", "X4"))
    items = (x2 or {}).get("parts") or _parse_x2((x2 or {}).get("value", ""))
    objs = (x4 or {}).get("parts")
    if objs is not None:
        # every item, built or not, aligned with the items by position
        lanes = [Lane(text=o.get("text") or o.get("title") or "", kind=o.get("kind", ""),
                      action=o.get("action", ""), junk=o.get("junk", ""),
                      outcome=_when(o), outcome_detail=o.get("line", ""))
                 for o in objs]
        for lane, it in zip(lanes, items):
            lane.time = it.get("time", "")
            lane.kind = lane.kind or it.get("kind", "")
    else:
        lanes = [Lane(text=it.get("text", ""), kind=it.get("kind", ""), time=it.get("time", ""))
                 for it in items]
        built = _parse_x4((x4 or {}).get("value", ""))
        if not lanes:
            lanes = [Lane(text=o["title"] or o["line"], action=o["action"],
                          outcome=_when(o), outcome_detail=o["line"]) for o in built]
        elif len(built) == len(lanes):
            for lane, o in zip(lanes, built):
                lane.action, lane.outcome, lane.outcome_detail = o["action"], _when(o), o["line"]
    for lane, r in zip(lanes, (x3 or {}).get("parts") or []):
        lane.resolved = dict(r.get("when") or {})

    # Nothing structured at all (a trace from before boundaries existed): one
    # lane per object written, read off the execute steps.
    execs = [s for s in steps if s.get("stage") == "execute"]
    if not lanes:
        for s in execs:
            action = _exec_action(s)
            lanes.append(Lane(text=str(s.get("detail") or ""), action=action,
                              outcome_detail=str(s.get("detail") or "")))
        if not lanes and g.heard and not running:
            lanes.append(Lane(text=g.repaired))
    else:
        _land_writes(lanes, execs)

    # -- who decided each ask ---------------------------------------------
    # The rule step's time is the WHOLE command's, so it is an ask's own only
    # when the command was one ask; a model call is always one ask's own.
    rule = next((s for s in steps if s.get("stage") == "rule"), None)
    built = next((s for s in steps if s.get("title") in ("Built the objects", "Build objects")), None)
    for lane in lanes:
        lane.decided_detail = str((built or rule or {}).get("detail") or "")
        lane.decided_ms = _ms(rule or {}) if len(lanes) == 1 else 0
    for s in steps:
        if s.get("stage") != "llm":
            continue
        m = _PART_N.search(str(s.get("title") or ""))
        i = int(m.group(1)) - 1 if m else (0 if len(lanes) == 1 else -1)
        if 0 <= i < len(lanes):
            lane = lanes[i]
            if lane.decided_by != "model":
                lane.decided_by, lane.decided_ms, lane.decided_detail = "model", 0, ""
            lane.decided_ms += _ms(s)
            lane.decided_detail = (lane.decided_detail + "\n" if lane.decided_detail else "") + \
                f"{s.get('title')}: {s.get('detail') or ''}"
    split = next((s for s in steps if s.get("title") in ("Split into commands", "Segmentation")), None)
    g.split_detail = str((split or {}).get("detail") or "")
    g.lanes = lanes
    return g


_ON_DAY = re.compile(r"\bon (\w{3})\w*, (\w{3})\w* (\d{1,2})")
_FROM = re.compile(r"\bfrom (\d{1,2}(?::\d{2})? ?[AP]M)", re.I)
_TO_LIST = re.compile(r"\bto (Today|General)\b")


def when_from_detail(detail: str) -> str:
    """'Created event 'x' on Friday, Sep 25, 2026 from 1 PM to 2 PM.' → 'Fri 25
    Sep 1 PM'; 'Added 'milk' to Today' → 'today'. The short line of an
    outcome whose fields only survive in the sentence that reported it."""
    d = detail or ""
    bits = []
    m = _ON_DAY.search(d)
    if m:
        bits.append(f"{m.group(1)} {m.group(3)} {m.group(2)}")
    m = _FROM.search(d)
    if m:
        bits.append(m.group(1))
    if not bits:
        m = _TO_LIST.search(d)
        if m:
            bits.append(m.group(1).lower())
    return " ".join(bits)


def _exec_action(step: dict) -> str:
    return re.sub(r"\s+", "_", str(step.get("title") or "").strip().lower())


def _land_writes(lanes: list, execs: list) -> None:
    """Put what was actually WRITTEN (the execute steps, in order) onto the
    lanes that wrote it.

    X4 is published when FastRule finishes — BEFORE the rescue's model call —
    so an ask the model went on to build reads "nothing built" there. The
    execute steps are the truth about what happened, so a lane left empty by X4
    takes its object from them. Lanes are matched in order; a thrown-out ask
    never takes one.
    """
    if not execs:
        return
    open_ = [ln for ln in lanes if not ln.junk]
    made = [ln for ln in open_ if ln.action]
    if len(made) == len(execs):
        targets = made
    elif len(open_) == len(execs):
        targets = open_
    else:
        # counts disagree (an ask made two objects, or a write failed): fill
        # the empty lanes with what X4 did not already account for, in order
        spare = execs[len(made):] if len(made) < len(execs) else []
        for lane, s in zip([ln for ln in open_ if not ln.action], spare):
            lane.action = lane.action or _exec_action(s)
            lane.outcome_detail = str(s.get("detail") or "")
            lane.outcome = lane.outcome or when_from_detail(lane.outcome_detail)
        for lane, s in zip(made, execs):
            lane.outcome_detail = str(s.get("detail") or lane.outcome_detail)
        return
    for lane, s in zip(targets, execs):
        lane.action = lane.action or _exec_action(s)
        lane.outcome_detail = str(s.get("detail") or lane.outcome_detail)
        lane.outcome = lane.outcome or when_from_detail(lane.outcome_detail)


def two_lines(fm, text: str, width: int) -> list:
    """At most two lines that fit `width` — the second elided. Word-wrap alone
    can break into three and spill out of the node."""
    words, line1 = (text or "").split(), ""
    while words and fm.horizontalAdvance((line1 + " " + words[0]).strip()) <= width:
        line1 = (line1 + " " + words.pop(0)).strip()
    if not line1:                                # one word wider than the line
        return [fm.elidedText(text, Qt.TextElideMode.ElideRight, width)]
    rest = " ".join(words)
    return [line1] + ([fm.elidedText(rest, Qt.TextElideMode.ElideRight, width)] if rest else [])


# ------------------------------------------------------------------ the view

_PAD = 12
_ROOT_H = 34
_LANE_H = 42
_LANE_GAP = 10
_TRUNK_X = _PAD + 10
_ASK_X = _PAD + 26
_EDGE_W = 64          # the edge that carries the decider chip
_FOOT_H = 30

#: The user's loading screen as frames (TASKS 48). The magic-words helper
#: writes them — this card runs in the HUD's own process and cannot ask it —
#: and the "working…" foot plays them. Re-read at most every few seconds.
_LOADER: dict = {"dir": None, "pix": [], "fps": 15.0, "checked": -1e9}


def _loader_frames() -> "tuple[list, float]":
    import os
    import time
    now = time.monotonic()
    if now - _LOADER["checked"] > 5:
        _LOADER["checked"] = now
        try:
            from assistant import magic_words
            info = magic_words.loader_frames()
        except Exception:                       # never worth breaking the card over
            info = None
        d = info["dir"] if info else None
        if d != _LOADER["dir"]:
            pix = []
            if d:
                for i in range(int(info.get("frames", 0))):
                    pm = QPixmap(os.path.join(d, f"{i:03d}.png"))
                    if not pm.isNull():
                        pix.append(pm)
            _LOADER.update(dir=d, pix=pix, fps=float(info.get("fps", 15)) if info else 15.0)
    return _LOADER["pix"], _LOADER["fps"]


class CommandGraphView(QWidget):
    """Paints a `Graph`. Hover an ask to follow it; click any node for what is
    behind it (`picked(heading, text)`); click the same node again to close."""

    picked = pyqtSignal(str, str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._g = Graph()
        self._hover: int | None = None          # lane under the pointer
        self._sel: tuple | None = None          # (node kind, lane index)
        self._hits: list = []                   # (QRectF, node kind, lane index)
        self._tick = 0
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # A slow pulse on the asks still waiting for an answer — the only
        # animation, and only while something is actually in flight.
        self._pulse = QTimer(self)
        self._pulse.setInterval(90)
        self._pulse.timeout.connect(self._on_pulse)

    # -- feeding --------------------------------------------------------

    @property
    def graph(self) -> Graph:
        return self._g

    def set_graph(self, g: Graph) -> None:
        self._g = g
        if self._sel and self._sel[1] is not None and self._sel[1] >= len(g.lanes):
            self._sel = None
        if g.running:
            # faster while the loader's frames play, so they don't stutter
            self._pulse.setInterval(66 if _loader_frames()[0] else 90)
            self._pulse.start()
        else:
            self._pulse.stop()
        self.setFixedHeight(self._content_height())
        self.update()

    def apply_theme(self, theme) -> None:
        self._theme = theme
        self.update()

    def _on_pulse(self) -> None:
        self._tick = (self._tick + 1) % 40
        self.update()

    # -- geometry ---------------------------------------------------------

    def _content_height(self) -> int:
        n = max(1, len(self._g.lanes))
        return int(self._lane_top() + n * _LANE_H + (n - 1) * _LANE_GAP + 14 + _FOOT_H)

    def _lane_top(self) -> float:
        return _PAD + _ROOT_H + 26

    def _lane_rect(self, i: int) -> QRectF:
        return QRectF(0, self._lane_top() + i * (_LANE_H + _LANE_GAP), self.width(), _LANE_H)

    def _ask_w(self) -> float:
        return max(90.0, (self.width() - _ASK_X - _PAD - _EDGE_W) * 0.52)

    def _out_x(self) -> float:
        return _ASK_X + self._ask_w() + _EDGE_W

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _event) -> None:   # noqa: N802 - Qt naming
        t, g = self._theme, self._g
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        base = QFont(self.font())
        small = QFont(base)
        small.setPointSizeF(max(8.0, base.pointSizeF() - 2))
        bold = QFont(base)
        bold.setWeight(QFont.Weight.DemiBold)

        # the sentence
        root = QRectF(_PAD, _PAD, self.width() - 2 * _PAD, _ROOT_H)
        sel = self._sel == ("root", None)
        self._node(p, root, QColor(t.accent if sel else t.border), QColor(t.surface))
        p.setFont(base)
        p.setPen(QColor(t.text))
        text_r = root.adjusted(10, 0, -10 - (54 if g.fixes else 0), 0)
        p.drawText(text_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(base).elidedText(f"“{g.repaired or g.heard or '…'}”",
                                                 Qt.TextElideMode.ElideRight, int(text_r.width())))
        if g.fixes:
            chip = QRectF(root.right() - 58, root.center().y() - 9, 50, 18)
            self._chip(p, chip, "fixed", QColor(t.orange), small)
        self._hits.append((root, "root", None))

        # the trunk, and what the split was
        lanes = g.lanes
        trunk_top = root.bottom()
        if lanes:
            trunk_bot = self._lane_rect(len(lanes) - 1).center().y()
            pen = QPen(QColor(t.border), 1.6)
            p.setPen(pen)
            p.drawLine(QPointF(_TRUNK_X, trunk_top), QPointF(_TRUNK_X, trunk_bot - 8))
        p.setFont(small)
        p.setPen(QColor(t.text2))
        n = len(lanes)
        how = ("the rules read it whole" if g.path == "fast"
               else "split" if n > 1 else "one ask")
        label = f"{n} ask{'s' if n != 1 else ''} · {how}" if n else (
            "listening…" if g.running else "nothing to do")
        if g.loops:
            label += f" · looped back ×{g.loops}"
        split_r = QRectF(_TRUNK_X + 10, trunk_top + 4, self.width() - _TRUNK_X - 2 * _PAD, 18)
        p.drawText(split_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        self._hits.append((split_r, "split", None))

        for i, lane in enumerate(lanes):
            dim = self._hover is not None and self._hover != i
            p.setOpacity(0.32 if dim else 1.0)
            self._paint_lane(p, i, lane, base, small, bold)
        p.setOpacity(1.0)

        # the foot: did every field trace back, and how long it took
        foot = QRectF(_PAD, self.height() - _FOOT_H, self.width() - 2 * _PAD, _FOOT_H - 6)
        p.setFont(small)
        if g.running:
            p.setPen(QColor(t.text2))
            frames, fps = _loader_frames()
            if frames:
                import time
                pm = frames[int(time.monotonic() * fps) % len(frames)]
                side = foot.height()
                p.drawPixmap(QRectF(foot.left(), foot.top(), side, side), pm, QRectF(pm.rect()))
                foot = foot.adjusted(side + 6, 0, 0, 0)
            p.drawText(foot, Qt.AlignmentFlag.AlignVCenter, "working…")
        else:
            mark = "✓" if g.check_ok is not False else "✗"
            colour = QColor(t.green if g.check_ok is not False else t.orange)
            check = ("every field traced back to the words" if g.check_ok is not False
                     else unsupported(g.check))
            tail = self._short_total(g.total)
            p.setPen(colour)
            p.drawText(foot, Qt.AlignmentFlag.AlignVCenter, mark)
            p.setPen(QColor(t.text2))
            rest = foot.adjusted(16, 0, 0, 0)
            p.drawText(rest, Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(small).elidedText(
                           f"{check}{' · ' + tail if tail else ''}",
                           Qt.TextElideMode.ElideRight, int(rest.width())))
            self._hits.append((foot, "check", None))
        p.end()

    @staticmethod
    def _short_total(total: str) -> str:
        m = re.search(r"(\d+(?:\.\d+)?)\s*s\b", total or "")
        return f"{m.group(1)} s" if m else ""

    def _paint_lane(self, p, i, lane, base, small, bold) -> None:
        t = self._theme
        r = self._lane_rect(i)
        cy = r.center().y()
        hot = self._hover == i

        # the branch off the trunk: a short elbow, rounded
        path = QPainterPath(QPointF(_TRUNK_X, cy - 8))
        path.quadTo(QPointF(_TRUNK_X, cy), QPointF(_TRUNK_X + 8, cy))
        path.lineTo(QPointF(_ASK_X, cy))
        p.setPen(QPen(QColor(t.accent if hot else t.border), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # the ask
        ask = QRectF(_ASK_X, r.top(), self._ask_w(), _LANE_H)
        self._node(p, ask, QColor(t.accent if (hot or self._sel == ("ask", i)) else t.border),
                   QColor(t.surface))
        p.setFont(base)
        p.setPen(QColor(t.text))
        inner = ask.adjusted(9, 3, -9, -3)
        fm = QFontMetrics(base)
        lines = two_lines(fm, lane.text or "…", int(inner.width()))
        line_h = fm.height()
        top = inner.center().y() - line_h * len(lines) / 2
        for k, line in enumerate(lines):
            p.drawText(QRectF(inner.left(), top + k * line_h, inner.width(), line_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, line)
        self._hits.append((ask, "ask", i))

        # the edge, and who decided on it
        x0, x1 = ask.right(), self._out_x()
        pending = self._g.running and not lane.action and not lane.junk
        pen = QPen(QColor(t.accent if hot else t.border), 1.6)
        if pending:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(x0, cy), QPointF(x1 - 4, cy))
        head = QPainterPath(QPointF(x1 - 1, cy))
        head.lineTo(QPointF(x1 - 7, cy - 4))
        head.lineTo(QPointF(x1 - 7, cy + 4))
        head.closeSubpath()
        p.fillPath(head, QColor(t.accent if hot else t.border))
        model = lane.decided_by == "model"
        chip_c = QColor(t.text2 if pending and not model else t.purple if model else t.accent)
        chip = QRectF((x0 + x1) / 2 - 24, cy - 17, 48, 16)
        self._chip(p, chip, "…" if pending and not model else "model" if model else "rules",
                   chip_c, small, filled=self._sel == ("decider", i))
        if lane.decided_ms:
            p.setFont(small)
            p.setPen(QColor(t.text2))
            p.drawText(QRectF(x0, cy + 2, x1 - x0, 14), Qt.AlignmentFlag.AlignCenter,
                       self._fmt_ms(lane.decided_ms))
        self._hits.append((QRectF(x0, r.top(), x1 - x0, _LANE_H), "decider", i))

        # what it became
        out = QRectF(x1, r.top(), self.width() - _PAD - x1, _LANE_H)
        if lane.action:
            colour = QColor(t.destructive if lane.action.startswith("delete")
                            else t.green if lane.action.startswith("create") else t.accent)
            title, sub = action_label(lane.action), lane.outcome
        elif lane.junk:
            colour, title, sub = QColor(t.text2), "Thrown out", "list management"
        elif pending:
            colour, title, sub = QColor(t.text2), "…", "deciding"
        else:
            colour, title, sub = QColor(t.orange), "Nothing", "couldn't tell what"
        border = QColor(colour)
        if pending:
            border.setAlphaF(0.35 + 0.65 * abs(20 - self._tick) / 20)
        self._node(p, out, border, QColor(t.surface), width=2.0 if hot else 1.4,
                   dashed=pending, selected=self._sel == ("outcome", i))
        p.setFont(bold)
        p.setPen(colour)
        inner = out.adjusted(9, 4, -8, -4)
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), inner.height() / 2),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(bold).elidedText(title, Qt.TextElideMode.ElideRight, int(inner.width())))
        if sub:
            p.setFont(small)
            p.setPen(QColor(t.text2))
            p.drawText(QRectF(inner.left(), inner.center().y(), inner.width(), inner.height() / 2),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(small).elidedText(sub, Qt.TextElideMode.ElideRight, int(inner.width())))
        self._hits.append((out, "outcome", i))

    def _node(self, p, rect, border, fill, width=1.4, dashed=False, selected=False) -> None:
        pen = QPen(QColor(self._theme.accent) if selected else border, 2.0 if selected else width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRoundedRect(rect, 8, 8)

    def _chip(self, p, rect, text, colour, font, filled=False) -> None:
        bg = QColor(colour)
        bg.setAlphaF(0.9 if filled else 0.16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setFont(font)
        p.setPen(QColor(self._theme.on_accent) if filled else colour)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"

    # -- interaction ------------------------------------------------------

    def _hit(self, pos) -> "tuple | None":
        # later entries sit on top (the chip over its edge), so search backwards
        for rect, kind, i in reversed(self._hits):
            if rect.contains(QPointF(pos)):
                return kind, i
        return None

    def mouseMoveEvent(self, event) -> None:   # noqa: N802 - Qt naming
        hit = self._hit(event.position())
        lane = hit[1] if hit and hit[1] is not None else None
        self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
        if lane != self._hover:
            self._hover = lane
            self.update()

    def leaveEvent(self, _event) -> None:   # noqa: N802 - Qt naming
        if self._hover is not None:
            self._hover = None
            self.update()

    def mousePressEvent(self, event) -> None:   # noqa: N802 - Qt naming
        hit = self._hit(event.position())
        if hit is None or hit == self._sel:
            self._sel = None
            self.picked.emit("", "")
        else:
            self._sel = hit
            self.picked.emit(*self.describe(*hit))
        self.update()

    def node_center(self, kind: str, lane: "int | None" = None) -> "QPointF | None":
        """Where a node is on screen — for a test to click it, and nothing else."""
        for rect, k, i in self._hits:
            if k == kind and i == lane:
                return rect.center()
        return None

    def describe(self, kind: str, i: "int | None") -> tuple:
        """(heading, text) for the detail line under the graph."""
        g = self._g
        if kind == "root":
            lines = [f"heard: {g.heard}"]
            if g.repaired and g.repaired != g.heard:
                lines.append(f"read as: {g.repaired}")
            if g.fixes:
                lines.append(f"fixed: {g.fixes}")
            return "What you said", "\n".join(lines)
        if kind == "split":
            if g.path == "fast":
                return "Split", "The rules read the whole command at once and were sure enough to act — no model."
            return "Split", g.split_detail or f"{len(g.lanes)} ask(s)"
        if kind == "check":
            return "Cross-check", g.check or "every field traced back to the words"
        lane = g.lanes[i]
        if kind == "ask":
            bits = [lane.text]
            if lane.kind:
                bits.append(f"read as: {'a to-do' if lane.kind == 'task' else 'an ' + lane.kind if lane.kind[0] in 'aeiou' else 'a ' + lane.kind}")
            if lane.time:
                bits.append(f"time as said: {lane.time}")
            if lane.resolved:
                bits.append("resolved: " + ", ".join(f"{k}={v}" for k, v in lane.resolved.items()))
            return f"Ask {i + 1}", "\n".join(bits)
        if kind == "decider":
            who = ("The model read this ask — the rules could not settle it."
                   if lane.decided_by == "model" else "The rules read this ask — no model call.")
            return f"Ask {i + 1} · {lane.decided_by}", \
                f"{who}{' (' + self._fmt_ms(lane.decided_ms) + ')' if lane.decided_ms else ''}\n{lane.decided_detail}".strip()
        # outcome
        if lane.action:
            return f"Ask {i + 1} · {action_label(lane.action)}", lane.outcome_detail or lane.outcome
        if lane.junk:
            return f"Ask {i + 1} · thrown out", lane.junk
        return f"Ask {i + 1} · nothing made", g.message or "The assistant couldn't tell what to make of this part."

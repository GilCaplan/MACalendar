"""The LLM call log — a SECOND append-only stream, deliberately not the trace bus.

`trace_bus.jsonl` cannot carry these, for three reasons the HUD's own code makes
unavoidable:

  ONE RUN AT A TIME. `ThinkingHUD.apply_entry` keeps a single `_current_run`; a
  line whose run does not match calls `panel.begin()` and inserts a divider. LLM
  calls interleave with a run rather than replacing it, so sharing the file
  would tear the timeline.

  ONE OFFSET. `_BusReader` holds a single scalar offset and `trace_bus.read_since`
  closes over the module-global `BUS_PATH` — there is no path parameter. Two
  streams need two readers with two offsets.

  A SHARED 200-LINE TRIM BUDGET. `_trim` keeps the last 200 LINES. One deep
  command makes several LLM calls, so a chatty second stream in the same file
  would evict finished runs — and `read_history` reads that file as the durable
  record the History view shows.

So: its own file, its own env override, its own budget, same shape.

**It holds real transcripts.** Prompts and responses are logged verbatim, which
means the user's own speech and their personal vocabulary. It lives beside the
other personal stores in `~/.assistant_tools/`, honours an override so tests and
measurement runs never touch the real one, and drops `source: "test"` traffic
entirely — the same rule the NLU log and the trace bus History already apply.
"""
from __future__ import annotations

import json
import os
import time

#: Resolved at import, like trace_bus.BUS_PATH — the stores are read at import
#: time throughout this project and a fixture set later is too late.
BUS_PATH = (os.environ.get("MACALENDAR_LLM_BUS")
            or os.path.expanduser("~/.assistant_tools/llm_calls.jsonl"))

#: Its own budget. Deep commands make several calls each, so this is line-hungry
#: in a way the trace bus is not.
MAX_ENTRIES = 400

#: Prompts can be enormous — the registry system prompt plus a memory few-shot
#: block. Truncated on write, with the original length kept, so the console can
#: say "12 KB, showing the first 4" instead of silently lying about the prompt.
MAX_FIELD = 4000


def _clip(text: str) -> "tuple[str, int]":
    text = text or ""
    return (text[:MAX_FIELD], len(text))


def record(*, transport: str, caller: str, model: str, system: str, user: str,
           response: str = "", ms: int = 0, schema: bool = False,
           error: str = "", source: str = "", run: str = "") -> None:
    """Append one call. Never raises — logging must not fail a command."""
    if source == "test":
        return
    try:
        sys_t, sys_n = _clip(system)
        usr_t, usr_n = _clip(user)
        rsp_t, rsp_n = _clip(response)
        entry = {
            "ts": time.time(), "transport": transport, "caller": caller,
            "model": model, "ms": ms, "schema": schema, "error": error,
            "source": source, "run": run,
            "system": sys_t, "system_len": sys_n,
            "user": usr_t, "user_len": usr_n,
            "response": rsp_t, "response_len": rsp_n,
        }
        _trim()
        os.makedirs(os.path.dirname(BUS_PATH), exist_ok=True)
        with open(BUS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def note(kind: str, detail: str, **extra) -> None:
    """A PROTOCOL event rather than a call — lock waits, coalescing, queue drains.

    Same stream on purpose: the console's value is seeing a concatenation and
    the calls it produced in one ordered list.
    """
    # Same rule as record(): a measurement run must not write into the real
    # log. record() had this guard and note() did not, so every sweep would
    # have published its lock waits and coalesces into ~/.assistant_tools —
    # the asymmetry only mattered once protocol events became frequent.
    if extra.get("source") == "test":
        return
    try:
        entry = {"ts": time.time(), "transport": "protocol", "kind": kind,
                 "detail": detail, "caller": "", "model": "", "ms": 0}
        entry.update(extra)
        _trim()
        os.makedirs(os.path.dirname(BUS_PATH), exist_ok=True)
        with open(BUS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


#: Cheap gate before the expensive check. A line here averages well under
#: 1 KB, so a file under this cannot hold MAX_ENTRIES*2 lines and does not
#: need reading to find that out.
_TRIM_PROBE_BYTES = MAX_ENTRIES * 2 * 200


def _trim() -> None:
    try:
        # SIZE FIRST. This used to readlines() the WHOLE file before every
        # append — fine when protocol events were rare, but the live view
        # raises the rate to several per command, twice around the engine's
        # lock. A full read+write of up to 800 lines inside the request path
        # is not something a visualisation should cost.
        try:
            if os.path.getsize(BUS_PATH) < _TRIM_PROBE_BYTES:
                return
        except OSError:
            return
        with open(BUS_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_ENTRIES * 2:
            with open(BUS_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines[-MAX_ENTRIES:])
    except Exception:
        pass


def size() -> int:
    try:
        return os.path.getsize(BUS_PATH)
    except OSError:
        return 0


def read_since(offset: int) -> "tuple[list, int]":
    """New entries past `offset`. Mirrors trace_bus.read_since, including its
    trim handling: a file shorter than the offset was rewritten, so restart."""
    try:
        current = os.path.getsize(BUS_PATH)
    except OSError:
        return [], 0
    if current < offset:
        return [], current
    if current == offset:
        return [], offset
    out = []
    try:
        with open(BUS_PATH, encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return out, f.tell()
    except OSError:
        return [], offset


def read_history(limit: int = 200) -> list:
    """The most recent entries, newest LAST (render order)."""
    try:
        with open(BUS_PATH, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def clear() -> None:
    """Empty the log — the console's Clear button."""
    try:
        open(BUS_PATH, "w").close()
    except OSError:
        pass


def caller_label() -> str:
    """WHERE this call came from, as a name a reader recognises.

    Walks the stack for the outermost interesting frame rather than the
    innermost: the immediate caller of a transport is always the transport
    wrapper, and what a reader wants is the STAGE — `llmjudge.extract_asks`,
    `_recheck_not_found`, `objects._parse_item`. Frames inside the parser and
    this module are skipped for that reason.
    """
    import inspect
    skip = ("assistant/llm_bus.py", "assistant/intent/parser.py",
            "assistant/engine/llm.py")
    try:
        for frame in inspect.stack()[1:14]:
            path = frame.filename.replace("\\", "/")
            if any(s in path for s in skip) or "/lib/python" in path:
                continue
            if "/assistant/" not in path:
                continue
            mod = path.split("/assistant/")[-1].removesuffix(".py").replace("/", ".")
            mod = mod.removesuffix(".__init__")
            return f"{mod}.{frame.function}"
    except Exception:
        pass
    return "unknown"

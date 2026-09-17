"""What it takes to be an external app this assistant can host.

An INTEGRATION is a program with its own repository, its own dependencies and
its own server, which this assistant starts, gates and proxies — without
vendoring it and without editing it. Jude is the first; the shape is written
down here so the second one is a subclass rather than a second pile of
bespoke plumbing.

## The four promises an integration makes

1.  **It is OPTIONAL.** Not installed, not enabled, or refusing to start are
    all NORMAL states, and each must produce a sentence a person can act on.
    Never a traceback, and never a surface that silently does nothing.
2.  **It is found, not assumed.** `marker` is a file that must exist inside the
    checkout. Pointing `path` at the wrong folder then says "that isn't Jude"
    instead of failing later with an ImportError from inside uvicorn.
3.  **Its model calls are THIS project's model calls.** Every integration that
    touches Ollama sits behind `integrations.ollama_gate`, so its traffic is
    arbitrated by `assistant/model_protocol.py` like everything else. An
    integration that talks to Ollama directly is a door with no lock on it —
    see CONVENTION.md, "the fifth door".
4.  **It is reached THROUGH this API.** Clients get one host, one key, one
    tailnet hop. The integration's own port stays on loopback, because it
    almost certainly has no authentication of its own.

## Why `status()` is a dict with a `reason` in it

Every surface — the Mac window, the iOS tab, the toolbar button — has to decide
what to draw before it knows whether the thing exists. So status NEVER raises:
it returns the same shape whatever is wrong, `ready` says whether to draw the
real UI, and `reason` is the sentence to show when `ready` is false. One shape
means a new integration needs no new client code to report itself.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class IntegrationUnavailable(RuntimeError):
    """This integration cannot serve the request, and the message says why.

    The message is shown to a PERSON, so it names the thing to do about it
    rather than the exception that caused it.
    """


class Integration(ABC):
    """One external app. Subclass, fill in the class attributes, done."""

    #: Short machine name — the URL prefix and the config key. "jude".
    name: str = ""
    #: What a person calls it. "Jude".
    label: str = ""
    #: The repository it lives in, quoted in every "it isn't here" message so
    #: the answer to "what do I do about it" travels with the complaint.
    repo: str = ""
    #: A path INSIDE the checkout that proves it is the right checkout.
    marker: str = ""
    #: How long to wait for it to answer after we start it. Generous by
    #: default: the alternative to waiting is telling the user it failed
    #: while it is still loading an index.
    start_timeout_s: int = 90

    # -- configuration ---------------------------------------------------

    @abstractmethod
    def config(self):
        """This integration's config block (`cfg.jude`, `cfg.something`)."""

    @property
    def env_path_var(self) -> str:
        """The env var that overrides the checkout path."""
        return f"MACALENDAR_{self.name.upper()}_PATH"

    def enabled(self) -> bool:
        return bool(getattr(self.config(), "enabled", False))

    def port(self) -> int:
        return int(getattr(self.config(), "port", 0) or 0)

    def autostart(self) -> bool:
        return bool(getattr(self.config(), "autostart", True))

    # -- where it is -----------------------------------------------------

    def root(self) -> "str | None":
        """The checkout's absolute path, or None if there isn't a valid one.

        The env override wins, then `config.path`. A RELATIVE path is resolved
        against this repository rather than the working directory — the
        assistant is launched from Finder, where the working directory is not
        something to depend on.
        """
        raw = os.environ.get(self.env_path_var) or getattr(self.config(), "path", "")
        if not raw:
            return None
        path = os.path.expanduser(raw)
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(_repo_root(), path))
        return path if os.path.isfile(os.path.join(path, self.marker)) else None

    # -- how it runs -----------------------------------------------------

    @abstractmethod
    def command(self, python: str) -> "list[str]":
        """The argv that starts its server, given the interpreter to use."""

    def environment(self) -> dict:
        """The environment the child is started with. Override to pin things."""
        return dict(os.environ)

    # -- what the surfaces ask -------------------------------------------

    def blueprint(self):
        """This integration's Flask blueprint, or None if it has no HTTP surface.

        Declared here rather than left to duck typing. `registry.register`
        calls it inside a try/except, so an integration that merely misspelled
        the name would have silently registered NO ROUTES and still started
        cleanly — the failure would surface later as 404s from a client that
        had no way to know the difference. A default of None makes "I have no
        routes" a deliberate answer instead of an accident.
        """
        return None

    def before_request(self) -> None:
        """Re-establish anything this integration needs, before proxying to it.

        Called on EVERY proxied request, and must be idempotent and cheap.

        It exists because of a lifetime mismatch that took Jude down silently.
        The ollama gate is a daemon thread inside the API SERVER process, and
        the API runs with `--reload` — so editing any file under `assistant/`
        restarts it and takes the gate with it. Jude is a separate process, so
        it survives that restart still pointed at `OLLAMA_HOST=127.0.0.1:11435`
        with nothing listening there any more.

        Nothing errored. Retrieval returned zero sources and the router
        "finished" in 12ms, because every model call failed instantly and every
        stage fell back to its default. An answer built on no sources is the
        one failure this system must never produce quietly.
        """

    def readiness_problem(self) -> str:
        """A blocker this integration can name for itself, or "".

        Installed and switched on is not the same as ABLE TO ANSWER: an
        integration can depend on data it cannot ship. Jude's vector index is
        2.2 GB and lives outside both repositories, and when it went missing
        every surface said "isn't running yet" — a sentence that is true,
        useless, and indistinguishable from a slow start. Nobody could have
        guessed from it that 924 MB of vectors had gone.

        So a subclass gets to say what is actually wrong, in a sentence with
        the fix in it. Checked after `installed`, because a missing checkout is
        the more basic problem and its own message is the better one.
        """
        return ""

    def extra_status(self) -> dict:
        """Integration-specific fields to merge into `status()`."""
        return {}

    def status(self) -> dict:
        """Everything a client needs to decide what to draw. NEVER raises.

        `reason` is empty when `ready` is true, and otherwise is the sentence
        to put on screen. `ready` means "installed and switched on" rather than
        "already running", because an integration that autostarts is ready
        before it is running — the first question is what starts it.
        """
        from assistant.integrations import process

        enabled = self.enabled()
        path = self.root()
        port = self.port()
        running = process.is_listening(port) if (enabled and port) else False

        # `reason` is PROSE and `repo` is the LINK — the sentence does not
        # contain the URL. Both used to carry it, so every client that did the
        # right thing (show the sentence, and the repo as something tappable)
        # printed the URL twice: once mid-sentence, wrapping across three
        # lines, and once as a link underneath it.
        reason = ""
        if not enabled:
            reason = (f"{self.label} is switched off — set {self.name}.enabled: "
                      f"true in config.yaml once you have a checkout of its "
                      f"repository.")
        elif path is None:
            reason = (f"{self.label} isn't installed here. It is a separate "
                      f"repository — clone it, then point {self.name}.path at "
                      f"the checkout.")
        elif self.readiness_problem():
            # Before the running check: "it will start in a moment" is a lie
            # when it cannot start at all.
            reason = self.readiness_problem()
        elif not running:
            reason = (f"{self.label} isn't running yet — it starts on your first "
                      "question and takes a moment to load."
                      if self.autostart() else
                      f"{self.label} isn't running, and autostart is off. "
                      f"Start it yourself in {path}.")

        out = {
            "name": self.name,
            "label": self.label,
            "enabled": enabled,
            "installed": path is not None,
            "running": running,
            "ready": enabled and path is not None and not self.readiness_problem(),
            "path": path or "",
            "port": port,
            "repo": self.repo,
            "reason": reason,
        }
        out.update(self.extra_status())
        return out


def _repo_root() -> str:
    # assistant/integrations/base.py -> assistant/integrations -> assistant -> repo
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))

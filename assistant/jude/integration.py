"""Jude, as an `Integration` — where it is, how it starts, whose model it uses.

Jude is a five-stage RAG pipeline over ~289,000 Sefaria passages, in its own
repository (github.com/GilCaplan/JudeTheJudaicChatBot), with its own corpus and
a ~2 GB vector index. It is NOT vendored here and should not be: copying it in
would make this repository unclonable and would fork a project still being
worked on separately. What lives here is the wiring.

Everything specific to Jude is in this folder. Everything generic — spawn and
wait, the status shape, the ollama gate — is `assistant/integrations/`, so the
next external app is a sibling folder rather than a second pile of plumbing.
"""

from __future__ import annotations

import os

from assistant.integrations import Integration
from assistant.integrations import ollama_gate

#: Jude's roles, each resolved from `<ROLE>_PROVIDER` / `<ROLE>_MODEL` in its
#: `backend/llm.py`. Pinning all five is what stops a stray `.env` in the
#: checkout re-enabling the cloud cascade: `_get_fallback_chain` reads the
#: explicit per-role provider BEFORE it builds the cascade.
ROLES = ("ROUTER", "FILTER", "SUMMARY", "SYNTH", "TOOLS")

#: Keys that would build that cascade. Blanked in the child's environment —
#: belt and braces behind the per-role pin.
CLOUD_KEYS = ("GEMINI_API_KEY", "LLMOD_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")


class JudeIntegration(Integration):
    name = "jude"
    label = "Jude"
    repo = "https://github.com/GilCaplan/JudeTheJudaicChatBot"
    # The file that proves a directory is actually Jude. Pointing `path` at the
    # wrong folder then says "that isn't Jude" rather than failing later with
    # an ImportError from inside uvicorn.
    marker = os.path.join("backend", "main.py")
    # It loads a multi-gigabyte ChromaDB collection and warms an embedding
    # model on the way up. On a cold page cache that genuinely is a minute-plus.
    start_timeout_s = 120

    def config(self):
        from assistant.config import load_config
        return load_config().jude

    def _ollama(self):
        from assistant.config import load_config
        return load_config().ollama

    def command(self, python: str) -> "list[str]":
        return [python, "-m", "uvicorn", "backend.main:app",
                "--host", "127.0.0.1", "--port", str(self.port())]

    # -- the model protocol ----------------------------------------------

    def model(self) -> str:
        """Which ollama model Jude's roles use.

        `ollama.model` unless `jude.model` overrides it, so Jude and the
        assistant share ONE resident model rather than making a laptop hold
        two — which on this machine is the difference between a warm model and
        a multi-second reload on every switch.
        """
        cfg = self.config()
        return (getattr(cfg, "model", "") or "").strip() or self._ollama().model

    def environment(self) -> dict:
        """The environment Jude's server is started with.

        Three things happen here, and each one is load-bearing.

        **1. Every role is pinned to local ollama.** Jude defaults to a cloud
        cascade (Gemini, then LLMod, then ollama). That default is wrong here
        in a way that matters: this project does not touch the internet —
        `tests/unit/test_offline.py` blocks every non-loopback socket and fails
        the build if that stops being true — and a question about one's own
        practice is not a thing to hand to someone else's server by accident.

        **2. Ollama is reached through the GATE, not directly.** `OLLAMA_HOST`
        points at `integrations.ollama_gate`, which takes `model_protocol.
        hold()` around every call. Without it Jude is a fifth, unarbitrated
        door to the one ollama this machine has — five calls per question, one
        of them a 30-90 second synthesis, none of them yielding to a voice
        command. See `ollama_gate.py`.

        **3. The shim is prepended to PYTHONPATH.** Jude hardcodes ollama's
        address for its ChromaDB embedding function, so `OLLAMA_HOST` alone
        leaves the retrieval path ungated. We do not edit Jude, so the patch
        rides in as a `sitecustomize` — see `integrations/shim/`.

        `jude.allow_cloud: true` hands 1 back: Jude is then started with the
        environment it would have had on its own, `.env` and all. A deliberate,
        named choice, and from then on the traffic is Jude's, not ours. The
        gate stays in place regardless, because arbitration is about this
        machine's ollama rather than about privacy.
        """
        cfg = self.config()
        ollama_cfg = self._ollama()
        env = dict(os.environ)

        upstream = ollama_cfg.base_url.rstrip("/")
        gate_port = int(getattr(cfg, "gate_port", 11435) or 11435)
        priority = (getattr(cfg, "priority", "") or "background").strip().lower()
        gate_url = ollama_gate.start(gate_port, upstream, priority)

        env["OLLAMA_HOST"] = gate_url
        # Read by the shim. Also its on/off switch: without them it is inert,
        # which matters because PYTHONPATH is inherited by anything Jude spawns.
        env["MACALENDAR_OLLAMA_GATE"] = gate_url
        env["MACALENDAR_OLLAMA_UPSTREAM"] = upstream
        env["PYTHONPATH"] = os.pathsep.join(
            [_shim_dir()] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

        if not getattr(cfg, "allow_cloud", False):
            model = self.model()
            for role in ROLES:
                env[f"{role}_PROVIDER"] = "ollama"
                env[f"{role}_MODEL"] = model
            for key in CLOUD_KEYS:
                env[key] = ""
            env["LLM_MODEL"] = model
        return env

    def extra_status(self) -> dict:
        cfg = self.config()
        return {
            "model": self.model(),
            "cloud": bool(getattr(cfg, "allow_cloud", False)),
            "gated": ollama_gate.is_running(
                int(getattr(cfg, "gate_port", 11435) or 11435)),
            "priority": (getattr(cfg, "priority", "") or "background").strip().lower(),
        }

    def blueprint(self):
        from assistant.jude.routes import blueprint
        return blueprint


def _shim_dir() -> str:
    """The directory holding `sitecustomize.py`.

    Located by path rather than by importing it as a package: it must contain
    NOTHING importable but `sitecustomize`, because PYTHONPATH goes to the
    FRONT of the child's `sys.path` and anything else in here would shadow the
    child's own module of that name.
    """
    import assistant.integrations as pkg
    return os.path.join(os.path.dirname(os.path.abspath(pkg.__file__)), "shim")

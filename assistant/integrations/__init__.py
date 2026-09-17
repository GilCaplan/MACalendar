"""Hosting somebody else's program without swallowing it.

An INTEGRATION is an external app — its own repository, its own dependencies,
its own server — that this assistant starts, gates and proxies. Jude (the
Judaic study assistant) is the first. The convention is written down in
`CONVENTION.md`; the short version is four modules:

    base.py         the Integration contract: discover, env, status
    process.py      the supervised child: spawn, wait for the port, reap
    ollama_gate.py  model_protocol.hold() in front of ollama, per call
    registry.py     the list, and the one line server.py calls
    shim/           sitecustomize, for children we may not edit

Adding one is a folder with an `Integration` subclass and a Flask blueprint in
it. Nothing under `integrations/` learns its name except `registry.py`.
"""

from assistant.integrations.base import (  # noqa: F401
    Integration,
    IntegrationUnavailable,
)

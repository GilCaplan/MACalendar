"""Jude — the Judaic study assistant, wired in without being swallowed.

Jude lives in its own repository (github.com/GilCaplan/JudeTheJudaicChatBot):
a five-stage RAG pipeline over ~289,000 Sefaria passages, with its own corpus
and a multi-gigabyte ChromaDB index. It is not vendored here and should not be
— copying it in would make this repository unclonable, and would fork a
project that is still being worked on separately. What lives here is the
bridge: where the checkout is, how its server is started, and the two rules
that make it part of *this* system rather than a second system running beside
it.

**Rule one: it speaks this project's LLM protocol.** Jude ships a cloud
fallback cascade (Gemini → LLMod → Ollama). This project does not touch the
internet — `tests/unit/test_offline.py` blocks every non-loopback socket and
fails the build if that stops being true — so `bridge.environment()` pins every
one of Jude's roles to local Ollama, on the model the assistant has already
loaded. One model resident, not two, and nothing leaves the machine.

**Rule two: it is reached through this API.** The phone talks to
`http://<mac>:8080/jude/*` with the same `X-API-Key` over the same tailnet as
everything else; the server proxies to Jude on localhost. Jude's port is never
exposed, and the phone learns no second address.

See `DOCUMENTATION/JUDE.md`.
"""

from assistant.jude.bridge import (  # noqa: F401
    JudeUnavailable,
    checkout_path,
    ensure_running,
    environment,
    is_listening,
    status,
    stop,
)

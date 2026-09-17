"""Jude — the Judaic study assistant, wired in without being swallowed.

Everything about Jude lives in this folder: how its checkout is found and
started (`integration.py`), the HTTP surface the clients use (`routes.py`),
the Mac app (`app.py`, `ui/`) and the map of all of it (`ARCHITECTURE.md`).
The generic machinery it stands on — spawn-and-wait, the status shape, the
ollama gate — is `assistant/integrations/`, and Jude is its first consumer.

Jude is its own repository (github.com/GilCaplan/JudeTheJudaicChatBot), a
five-stage RAG pipeline over ~289,000 Sefaria passages with a ~2 GB vector
index. It is NOT vendored here, it is NOT edited by us, and nothing in this
project requires it: without a checkout `jude.enabled` stays false, the Mac
app says so, and the iOS tab is off.
"""

from assistant.jude.integration import JudeIntegration  # noqa: F401

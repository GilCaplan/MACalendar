"""Patched into a child we are not allowed to edit.

## Why this file exists

An integration is somebody else's repository, and we do not edit it. Jude,
reasonably enough for a program that expected to be run on its own, HARDCODES
ollama's address in two places rather than reading `OLLAMA_HOST`:

    backend/retriever.py:37   OllamaEmbeddingFunction(url="http://localhost:11434/api/embeddings")
    backend/indexer.py:69     the same, for the one-time index build

Its LLM calls go through `ollama.Client()`, which DOES honour `OLLAMA_HOST`, so
pointing that at `integrations.ollama_gate` catches routing, filtering,
summarisation, synthesis and tools. It does not catch the embedding call on the
retrieval path — and a gate with a hole in it is worse than no gate, because it
reads as covered.

## How it gets in

Python imports `sitecustomize` automatically at interpreter start if it is
anywhere on `sys.path` (that is what the `site` module is for). So the child is
spawned with this directory prepended to `PYTHONPATH`, and the patch is in
place before `backend.retriever` is ever imported.

The directory holds NOTHING ELSE, deliberately: `PYTHONPATH` goes to the front
of `sys.path`, so any other module in here would shadow the child's own modules
of the same name.

## Rules this file lives by

- **It never breaks the child.** Every patch is wrapped: a chromadb that moved
  its embedding function, or a child that does not use chromadb at all, must
  lose the patch and keep running, not fail to start.
- **It chains.** If the environment already had a `sitecustomize`, it is
  imported first — ours is an addition to the child's world, not a replacement
  for it.
- **It only rewrites addresses we are redirecting.** A URL pointing somewhere
  other than the ollama we are shadowing is left exactly as it is.
"""

import os


def _chain_existing() -> None:
    """Run any sitecustomize we are shadowing, so we add rather than replace.

    Loaded UNDER ANOTHER NAME, by file path. The obvious version — pop
    "sitecustomize" out of `sys.modules` and re-import it — corrupts the import
    that is running right now: this module IS `sys.modules["sitecustomize"]`
    while its body executes, and removing it makes the machinery fail its own
    bookkeeping with `KeyError: 'sitecustomize'`. The child then dies at
    interpreter start, before it runs a line of its own code, which is the
    worst failure this file could possibly have.
    """
    import importlib.machinery
    import importlib.util
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    elsewhere = [p for p in sys.path if os.path.abspath(p) != here]
    try:
        spec = importlib.machinery.PathFinder.find_spec("sitecustomize", elsewhere)
        if spec is None or spec.loader is None:
            return                # the normal case: there wasn't one
        module = importlib.util.module_from_spec(spec)
        # Never registered as "sitecustomize" — that name belongs to us for the
        # life of this interpreter.
        sys.modules["_macalendar_chained_sitecustomize"] = module
        spec.loader.exec_module(module)
    except Exception:             # noqa: BLE001 - theirs failing is not ours failing
        pass


def _redirect_chromadb_ollama(from_hosts, to_host: str) -> None:
    """Make chromadb's Ollama embedding function point at the gate.

    Patched at the CLASS level rather than by editing the call site, because
    the call site is in the child's source. `__init__` is wrapped so whatever
    url the child passes is rewritten on the way through.

    `from_hosts` is every spelling of the upstream at once — `localhost` and
    `127.0.0.1` name the same server but are different strings, and the child
    picked one of them. Passing them together matters because this function is
    idempotent: patching once per spelling meant whichever ran first won and
    the other spelling was never redirected at all.

    The signature is `(url, model_name, timeout)` with `url` DEFAULTING to
    ollama's own address, so a caller that passes no url must be redirected
    too — otherwise the default quietly bypasses the gate, which is exactly
    the hole this file exists to close.
    """
    try:
        from chromadb.utils import embedding_functions
    except Exception:         # noqa: BLE001 - not every child uses chromadb
        return

    cls = getattr(embedding_functions, "OllamaEmbeddingFunction", None)
    if cls is None or getattr(cls, "_macalendar_gated", False):
        return

    original_init = cls.__init__
    hosts = tuple(from_hosts)

    def _rewrite(url: str) -> str:
        for host in hosts:
            if host in url:
                return url.replace(host, to_host)
        return url

    def gated_init(self, *args, **kwargs):
        if "url" in kwargs:
            kwargs["url"] = _rewrite(kwargs["url"])
        elif args and isinstance(args[0], str):
            args = (_rewrite(args[0]),) + args[1:]
        else:
            kwargs["url"] = to_host          # it would have used the default
        return original_init(self, *args, **kwargs)

    try:
        cls.__init__ = gated_init
        cls._macalendar_gated = True
    except Exception:         # noqa: BLE001 - a frozen class stays unpatched
        pass


def _install() -> None:
    # Set by the parent alongside PYTHONPATH. Absent means "not our child" —
    # this file is then inert, which matters because PYTHONPATH is inherited
    # by anything the child itself spawns.
    to_host = os.environ.get("MACALENDAR_OLLAMA_GATE", "").strip()
    from_host = os.environ.get("MACALENDAR_OLLAMA_UPSTREAM", "").strip()
    if not to_host or not from_host:
        return
    _redirect_chromadb_ollama(
        {from_host,
         from_host.replace("localhost", "127.0.0.1"),
         from_host.replace("127.0.0.1", "localhost")},
        to_host)


_chain_existing()
try:
    _install()
except Exception:             # noqa: BLE001 - a shim must never stop the child
    pass

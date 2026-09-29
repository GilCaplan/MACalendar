"""Model helpers: other computers that lend the brain their model (DEVQA Q70).

Gil, 2026-09-29: *"a way to decide and control server — primary … and if other
OS devices are capable of running models, control what is primary and
secondary, and make sure the protocol is matched for model calls no matter
what OS"*. Ruled: a secondary is a **model helper**.

- The **primary** is the machine running the brain (``assistant.api``): the
  engine, the calendar, the command memory. There is one.
- A **helper** is any Mac, Linux or Windows machine that runs
  ``python -m assistant.host`` in the helper role: ollama behind the SAME
  gate (``integrations/ollama_gate.py`` + ``model_protocol.hold()``), open to
  the network only with a token it issued.

**The protocol is matched by construction, and checked.** The engine builds
every prompt, schema and seed on the primary and sends the finished request,
so a helper runs exactly what the primary would have run. What could still
differ is the MODEL, so a helper is used for a model only when it holds that
model with the SAME digest as the primary (``router.plan``), and only when it
speaks the same gate version. A seeded process — a board — never leaves this
machine: different hardware is not guaranteed to produce identical tokens,
and a measurement must be.

**Order is the person's.** ``order`` lists the machines, this one included;
a call goes to the first that is up and matched, and skips THIS machine while
its model is busy if a helper comes after it (overflow). A helper that fails
is marked down for a minute and the call moves on; this machine is always the
last resort.

    store.py   the helpers and the order (~/.assistant_tools/model_hosts.json)
    router.py  health, matching, and ``post`` — the one door to a model
    routes.py  GET /servers, the helper list, the order, the server log
"""

"""Pairing: a phone finds this server and is trusted by it without typing.

DEVQA Q69 (Gil, 2026-09-29: *"clickable and easy to set up server without
needing to type in any links … as automatic as possible"*). Until then the
phone's Settings asked for ``http://100.x.x.x:8080`` by hand. Two ways in now,
and neither involves a keyboard:

- **At home — found.** The server announces itself on the local network
  (Bonjour / mDNS, ``_macalendar._tcp``; ``discovery.py``). The phone's
  "Your Mac" page lists what it hears; one tap connects.
- **Anywhere — scanned.** The server's menu-bar app (``assistant.host``) and
  the calendar window's More menu show a QR code: a ``macalendar://pair`` link
  carrying every address the server can be reached at (Tailscale first) and a
  ONE-TIME code (``codes.py``). The iPhone's Camera opens it in the app, which
  picks the first address that answers and redeems the code at
  ``POST /devices/pair`` for its device id and token.

The one-time code is also a trust boundary the plain ``/devices/enroll`` does
not have: a code is issued only to a caller ON the server itself
(``POST /pair/start`` is loopback-only), so a device holding one was paired by
someone standing at the Mac. ``pairing.require_code`` makes that the ONLY way
in for a remote device.

Everything here is HTTP plumbing and the local network — nothing parses a
command, and nothing reaches the internet (the announcement is link-local
multicast; ``tests/unit/test_offline.py`` still holds).
"""

"""Pairing (DEVQA Q69): a phone finds the server and joins it without typing.

What must hold:
- a one-time code works ONCE, and only until it expires;
- a code is issued only on the server itself;
- the QR's link carries every address, Tailscale first, and the key only
  when the server has one;
- nothing is announced on the network by building the app (a test must not
  multicast) — only ``assistant.api.main`` announces;
- ``pairing.require_code`` closes plain enrolment to other machines.
"""
from __future__ import annotations

import plistlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import assistant.api.server as server
from assistant.config import PairingConfig
from assistant.pairing import addresses, codes, discovery, link

ROOT = Path(__file__).resolve().parents[2]


# -- codes -----------------------------------------------------------------

def test_a_code_works_once():
    c = codes.issue(60)
    assert codes.redeem(c)
    assert not codes.redeem(c), "a redeemed code must be gone"


def test_a_code_expires():
    c = codes.issue(60, now=1000.0)
    assert not codes.redeem(c, now=1061.0)


def test_a_code_survives_being_read_aloud():
    c = codes.issue(60)
    shown = codes.pretty(c).lower()                   # "abcd-efgh"
    assert "-" in shown and codes.redeem(shown)


def test_codes_have_no_look_alike_characters():
    assert not set("0O1IL") & set(codes.ALPHABET)


def test_an_unknown_code_is_refused():
    assert not codes.redeem("")
    assert not codes.redeem("NOPE-NOPE")


# -- addresses and the link -------------------------------------------------

def test_tailscale_comes_first_and_nothing_repeats():
    ips = [("192.168.1.20", "lan"), ("100.101.1.2", "tailscale"), ("192.168.1.20", "lan")]
    assert addresses.candidate_urls(8080, ips, ask_cli=False) == [
        "http://100.101.1.2:8080", "http://192.168.1.20:8080"]


def test_the_link_carries_every_address_the_code_and_the_name():
    url = link.pair_link(["http://100.1.2.3:8080", "http://192.168.1.5:8080"],
                         "ABCDEFGH", "Gil's MacBook")
    u = urlparse(url)
    q = parse_qs(u.query)
    assert (u.scheme, u.netloc) == ("macalendar", "pair")
    assert q["u"] == ["http://100.1.2.3:8080", "http://192.168.1.5:8080"]
    assert q["c"] == ["ABCDEFGH"] and q["n"] == ["Gil's MacBook"]
    assert "k" not in q, "no key configured, none in the QR"


def test_the_key_rides_along_only_when_the_server_has_one():
    q = parse_qs(urlparse(link.pair_link(["http://x:8080"], "C", "N", key="s3cret")).query)
    assert q["k"] == ["s3cret"]


def test_the_qr_is_square_and_has_a_quiet_zone():
    m = link.qr_matrix(link.pair_link(["http://100.1.2.3:8080"], "ABCDEFGH", "Mac"))
    assert len(m) >= 25 and all(len(r) == len(m) for r in m)
    assert not any(m[0]) and not any(r[0] for r in m)


def test_the_announcement_fits_one_txt_string():
    urls = [f"http://192.168.{i}.{i}:8080" for i in range(40)]
    t = discovery.txt(urls, "Mac")
    assert len("urls=" + t["urls"]) <= 255
    assert t["urls"].split(",") == urls[:len(t["urls"].split(","))], "dropped from the end"


# -- routes ------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(addresses, "candidate_urls",
                        lambda port, ips=None, ask_cli=True: [f"http://100.64.0.9:{port}"])
    monkeypatch.setattr(addresses, "server_name", lambda: "Test Mac")
    app = server.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _remote(ip="192.168.1.77"):
    return {"environ_base": {"REMOTE_ADDR": ip}}


def test_a_code_is_issued_on_the_server_itself(client):
    r = client.post("/pair/start")
    assert r.status_code == 200
    body = r.get_json()
    assert body["link"].startswith("macalendar://pair?")
    assert body["urls"] == ["http://100.64.0.9:80"] or body["urls"][0].startswith("http://100.64.0.9:")
    assert body["name"] == "Test Mac" and body["expires_in"] > 0


def test_a_code_is_never_issued_to_another_machine(client):
    assert client.post("/pair/start", **_remote()).status_code == 403


def test_a_phone_pairs_with_a_live_code_once(client):
    code = client.post("/pair/start").get_json()["code"]
    r = client.post("/devices/pair", json={"code": code, "source": "ios",
                                           "label": "iPhone · test"}, **_remote())
    assert r.status_code == 200
    got = r.get_json()
    assert got["device_id"].startswith("ios-") and got["token"] and got["server"] == "Test Mac"
    again = client.post("/devices/pair", json={"code": code, "source": "ios"}, **_remote())
    assert again.status_code == 403


def test_pairing_refuses_a_source_it_does_not_know(client):
    code = client.post("/pair/start").get_json()["code"]
    assert client.post("/devices/pair", json={"code": code, "source": "test"}).status_code == 400


def test_require_code_closes_plain_enrolment_to_other_machines(client, monkeypatch):
    cfg = server.load_config()
    cfg.pairing.require_code = True
    monkeypatch.setattr(server, "load_config", lambda *a, **k: cfg)
    assert client.post("/devices/enroll", json={"source": "ios"}, **_remote()).status_code == 403
    assert client.post("/devices/enroll", json={"source": "mac"}).status_code == 200, \
        "the Mac's own clients still enrol"


def test_plain_enrolment_stays_open_by_default(client):
    assert PairingConfig().require_code is False
    assert client.post("/devices/enroll", json={"source": "ios"}, **_remote()).status_code == 200


def test_pairing_works_before_anyone_signs_in():
    from assistant.users.routes import OPEN_PATHS
    assert {"/devices/pair", "/pair/start"} <= OPEN_PATHS


def test_building_the_app_announces_nothing():
    """Only the process that owns the port announces; create_app never does,
    so a test (or the reloader's child) cannot multicast."""
    src = (ROOT / "assistant/api/server.py").read_text()
    assert "discovery" not in src
    main = (ROOT / "assistant/api/__init__.py").read_text()
    assert "advertise(args.port)" in main and 'WERKZEUG_RUN_MAIN' in main
    assert "MACALENDAR_NO_DISCOVERY" in main


def test_the_pairing_setting_is_mirrored_in_the_example_config():
    ex = (ROOT / "config.example.yaml").read_text()
    for key in ("pairing:", "advertise:", "code_minutes:", "require_code:"):
        assert key in ex


# -- the phone and the server agree -------------------------------------------

IOS = ROOT / "MACalendar-iOS" / "MACalendar-iOS"


def test_the_phone_reads_the_link_the_server_writes():
    """Same scheme, host and keys on both sides: a renamed key on one side
    would pair nothing and fail silently."""
    swift = (IOS / "API" / "Pairing.swift").read_text()
    assert 'url.scheme == "macalendar", url.host == "pair"' in swift
    for key in ('$0.name == "u"', 'one("c")', 'one("n")', 'one("k")'):
        assert key in swift, key
    assert link.pair_link(["http://a:1"], "C", "N", "K").startswith("macalendar://pair?u=")


def test_the_phone_is_allowed_to_browse_for_the_announcement():
    """iOS finds ONLY the Bonjour types its Info.plist lists."""
    plist = plistlib.loads((IOS / "Info.plist").read_bytes())
    service = discovery.SERVICE.removesuffix(".local.")          # _macalendar._tcp
    assert service in plist["NSBonjourServices"]
    assert f'type: "{service}"' in (IOS / "API" / "Pairing.swift").read_text()
    assert "urls" in discovery.txt(["http://a:1"], "Mac")
    assert 'txt["urls"]' in (IOS / "API" / "Pairing.swift").read_text()


def test_the_phone_may_pair_before_signing_in():
    client = (IOS / "API" / "APIClient.swift").read_text()
    assert '"/devices/pair"' in client


def test_the_server_app_is_the_menu_bar_host():
    build = (ROOT / "scripts" / "build_apps.sh").read_text()
    assert "-m assistant.host\" true" in build

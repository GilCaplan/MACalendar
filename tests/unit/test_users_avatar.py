"""Profile photos: a person sets their own, everyone signed in sees it.

The clients crop and shrink the photo before sending, so the server only
checks the bytes are a JPEG or PNG under the cap and keeps them in the
person's own folder — which is why removing a person takes their photo along
to legacy/ with the rest of their data.
"""
from __future__ import annotations

import base64
import os

import pytest

from assistant.users import paths, registry

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MACALENDAR_USERS", str(tmp_path / "users.json"))
    monkeypatch.setenv("MACALENDAR_SESSIONS", str(tmp_path / "sessions.json"))
    from assistant.users import routes
    routes._fails.clear()
    from assistant.api import server
    return server.create_app().test_client()


@pytest.fixture
def people(app_client):
    return (registry.create_user("gil", "admin-pass", role="admin"),
            registry.create_user("dana", "dana-pass"))


def _tok(c, name, pw):
    r = c.post("/auth/login", json={"username": name, "password": pw, "source": "test"})
    assert r.status_code == 200, r.get_json()
    return {"X-Session-Token": r.get_json()["session_token"]}


def _put(c, h, data):
    return c.put("/users/me/avatar", headers=h, json={"image": base64.b64encode(data).decode()})


def test_a_person_sets_their_photo_and_everyone_sees_it(app_client, people):
    _, dana = people
    r = _put(app_client, _tok(app_client, "dana", "dana-pass"), JPEG)
    assert r.status_code == 200 and r.get_json()["avatar"]["type"] == "jpeg"
    gil = _tok(app_client, "gil", "admin-pass")
    listed = {u["id"]: u for u in app_client.get("/users", headers=gil).get_json()}
    assert listed[dana]["avatar"]["v"] == r.get_json()["avatar"]["v"]
    got = app_client.get(f"/users/{dana}/avatar", headers=gil)
    assert got.status_code == 200 and got.mimetype == "image/jpeg" and got.data == JPEG


def test_it_lives_in_their_own_folder_and_a_png_replaces_a_jpeg(app_client, people):
    _, dana = people
    h = _tok(app_client, "dana", "dana-pass")
    _put(app_client, h, JPEG)
    _put(app_client, h, PNG)
    folder = paths.user_dir(dana)
    assert sorted(f for f in os.listdir(folder) if f.startswith("avatar")) == ["avatar.png"]
    assert app_client.get(f"/users/{dana}/avatar", headers=h).mimetype == "image/png"


def test_anything_but_a_small_jpeg_or_png_is_refused(app_client, people):
    h = _tok(app_client, "dana", "dana-pass")
    assert _put(app_client, h, b"GIF89a" + b"\x00" * 10).status_code == 400
    assert _put(app_client, h, JPEG + b"\x00" * registry.AVATAR_MAX_BYTES).status_code == 400
    assert app_client.put("/users/me/avatar", headers=h, json={"image": "not base64!"}).status_code == 400
    assert registry.get(people[1]).get("avatar") is None


def test_removing_the_photo_goes_back_to_the_initial(app_client, people):
    _, dana = people
    h = _tok(app_client, "dana", "dana-pass")
    _put(app_client, h, JPEG)
    assert app_client.delete("/users/me/avatar", headers=h).get_json().get("avatar") is None
    assert app_client.get(f"/users/{dana}/avatar", headers=h).status_code == 404
    assert not os.path.exists(os.path.join(paths.user_dir(dana), "avatar.jpeg"))


def test_a_photo_never_leaves_with_the_password_hash(app_client, people):
    h = _tok(app_client, "dana", "dana-pass")
    body = _put(app_client, h, JPEG).get_json()
    assert "password" not in body


def test_the_admin_sets_and_removes_anyones_photo(app_client, people):
    _, dana = people
    gil = _tok(app_client, "gil", "admin-pass")
    img = {"image": base64.b64encode(PNG).decode()}
    r = app_client.put(f"/admin/users/{dana}/avatar", headers=gil, json=img)
    assert r.status_code == 200 and r.get_json()["avatar"]["type"] == "png"
    assert registry.avatar_file(dana)[1] == "image/png"
    _put(app_client, _tok(app_client, "dana", "dana-pass"), JPEG)      # they change it back
    assert app_client.delete(f"/admin/users/{dana}/avatar", headers=gil).status_code == 200
    assert registry.avatar_file(dana) is None                          # and the admin's removal wins


def test_only_the_admin_touches_someone_elses_photo(app_client, people):
    gil_id, _ = people
    dana = _tok(app_client, "dana", "dana-pass")
    img = {"image": base64.b64encode(JPEG).decode()}
    assert app_client.put(f"/admin/users/{gil_id}/avatar", headers=dana, json=img).status_code == 403
    assert app_client.delete(f"/admin/users/{gil_id}/avatar", headers=dana).status_code == 403
    gil = _tok(app_client, "gil", "admin-pass")
    assert app_client.put("/admin/users/u_nobody/avatar", headers=gil, json=img).status_code == 404

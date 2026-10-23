import base64

import pytest
from fastapi.testclient import TestClient

from purple_api import accounts
from purple_api.main import create_app
from purple_api.store import Store
from test_api import FakeProvider


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("PURPLE_PASSWORD", "s3cret")
    monkeypatch.setenv("PURPLE_MAX_USERS", "2")
    monkeypatch.setenv("PURPLE_LIVE_LOOP", "0")
    return create_app(store=Store(":memory:"), provider=FakeProvider())


def test_owner_signs_in_by_name_or_basic_and_friends_register_until_seats_run_out(app):
    owner, a, b, c = (TestClient(app) for _ in range(4))
    assert owner.get("/api/auth/me").json() == {"accounts": True, "signed_in": False, "name": None, "role": None,
                                                "seats_left": 2}
    assert owner.post("/api/auth/login", json={"name": "owner", "password": "nope"}).status_code == 401
    assert owner.post("/api/auth/login", json={"name": "Owner", "password": "s3cret"}).json()["role"] == "owner"
    basic = base64.b64encode(b"x:s3cret").decode()
    assert TestClient(app).get("/api/desk", headers={"Authorization": f"Basic {basic}"}).status_code == 200
    assert a.post("/api/auth/register", json={"name": "owner", "password": "longenough"}).status_code == 422
    assert a.post("/api/auth/register", json={"name": "Asha", "password": "short"}).status_code == 422
    r = a.post("/api/auth/register", json={"name": "Asha", "password": "longenough"}).json()
    assert r["role"] == "member" and r["name"] == "Asha" and r["seats_left"] == 1
    assert b.post("/api/auth/register", json={"name": "asha", "password": "longenough"}).status_code == 409
    assert b.post("/api/auth/register", json={"name": "Ben", "password": "longenough"}).status_code == 200
    assert c.post("/api/auth/register", json={"name": "Cyrus", "password": "longenough"}).status_code == 403  # full
    fresh = TestClient(app)
    assert fresh.post("/api/auth/login", json={"name": "ASHA", "password": "longenough"}).json()["name"] == "Asha"
    assert fresh.post("/api/auth/logout").json()["signed_in"] is False
    assert fresh.get("/api/desk").status_code == 401


def test_friends_view_the_bot_but_cannot_change_it_and_keep_their_own_items_private(app):
    owner, friend, other = TestClient(app), TestClient(app), TestClient(app)
    owner.post("/api/auth/login", json={"name": "owner", "password": "s3cret"})
    friend.post("/api/auth/register", json={"name": "Asha", "password": "longenough"})
    other.post("/api/auth/register", json={"name": "Ben", "password": "longenough"})
    assert friend.get("/api/desk").status_code == 200  # sees the owner's bot
    for path in ("/api/desk", "/api/desk/stop", "/api/desk/decide", "/api/desk/coach/rules/R1/retire"):
        assert friend.post(path, json={"capital": 500000, "days": 7}).status_code == 403
    assert friend.get("/api/desk/review?save=true").status_code == 403
    assert friend.get("/api/auth/users").status_code == 403
    mine = owner.post("/api/strategies", json={"name": "Owner bot"}).json()["id"]
    hers = friend.post("/api/strategies", json={"name": "Asha bot"}).json()["id"]
    assert [s["name"] for s in friend.get("/api/strategies").json()] == ["Asha bot"]
    assert [s["name"] for s in owner.get("/api/strategies").json()] == ["Owner bot"]
    assert other.get("/api/strategies").json() == []
    assert friend.get(f"/api/strategies/{mine}").status_code == 404
    assert other.delete(f"/api/strategies/{hers}").status_code == 404
    assert friend.get(f"/api/strategies/{hers}").status_code == 200
    users = owner.get("/api/auth/users").json()
    assert [u["name"] for u in users["users"]] == ["Asha", "Ben"] and users["users"][0]["strategies"] == 1
    gone = owner.delete(f"/api/auth/users/{users['users'][1]['id']}").json()
    assert [u["name"] for u in gone["users"]] == ["Asha"]
    assert other.get("/api/strategies").status_code == 401  # signed out


def test_friends_never_use_the_server_ai(app):
    friend = TestClient(app)
    friend.post("/api/auth/register", json={"name": "Asha", "password": "longenough"})
    ai = friend.get("/api/health").json()["ai"]
    assert ai["available"] is False and "own free AI key" in ai["detail"]
    owner = TestClient(app)
    owner.post("/api/auth/login", json={"name": "owner", "password": "s3cret"})
    assert owner.get("/api/health").json()["ai"]["available"] is True


def test_no_accounts_without_a_password(monkeypatch):
    monkeypatch.delenv("PURPLE_PASSWORD", raising=False)
    c = TestClient(create_app(store=Store(":memory:"), provider=FakeProvider()))
    assert c.get("/api/auth/me").json()["accounts"] is False
    assert c.get("/api/desk").status_code == 200


def test_password_hashes():
    h = accounts.hash_password("longenough")
    assert h.startswith("scrypt$") and accounts.check_password("longenough", h)
    assert not accounts.check_password("wrong", h) and not accounts.check_password("x", "garbage")

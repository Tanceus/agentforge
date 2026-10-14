from tests.conftest import auth_header, register


def test_register_login_and_me(client):
    created = register(client)
    assert created["user"]["email"] == "ada@example.com"
    assert created["access_token"]
    me = client.get("/api/v1/auth/me", headers=auth_header(created["access_token"]))
    assert me.status_code == 200
    assert me.json()["full_name"] == "Ada Lovelace"

    bad = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong-password"})
    assert bad.status_code == 401

    logged = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "password123"})
    assert logged.status_code == 200
    assert logged.json()["user"]["role"] == "user"


def test_duplicate_email_conflict(client):
    register(client)
    again = client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "password": "password123", "full_name": "Ada"},
    )
    assert again.status_code == 409


def test_refresh_rotation_and_logout(client):
    created = register(client)
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": created["refresh_token"]})
    assert refreshed.status_code == 200
    old = client.post("/api/v1/auth/refresh", json={"refresh_token": created["refresh_token"]})
    assert old.status_code == 401
    me = client.get("/api/v1/auth/me", headers=auth_header(refreshed.json()["access_token"]))
    assert me.status_code == 200
    logout = client.post("/api/v1/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]})
    assert logout.status_code == 204
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": refreshed.json()["refresh_token"]})
    assert reused.status_code == 401


def test_profile_and_password_change(client):
    created = register(client)
    headers = auth_header(created["access_token"])
    updated = client.patch("/api/v1/auth/me", json={"full_name": "Ada K."}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Ada K."
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "password123", "new_password": "newpassword123"},
        headers=headers,
    )
    assert changed.status_code == 204
    relogin = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "newpassword123"})
    assert relogin.status_code == 200


def test_admin_overview_is_role_gated(client, db):
    created = register(client)
    headers = auth_header(created["access_token"])
    forbidden = client.get("/api/v1/admin/overview", headers=headers)
    assert forbidden.status_code == 403

    from app.models import User

    user = db.get(User, created["user"]["id"])
    user.role = "admin"
    db.commit()
    allowed = client.get("/api/v1/admin/overview", headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["users"] >= 1

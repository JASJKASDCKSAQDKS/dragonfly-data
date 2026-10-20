"""
Login-flow tests for the developer dashboard gate.

Covers the app's original requirement: the seeded developer account signs in
with email + password only (no MFA), receives a working token, and the login
page is the app's entry point.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from jarvis.web.server import app
from jarvis.auth.service import AuthService
from jarvis.auth.models import Role, UserStatus, LoginRequest
from jarvis import config

# NOTE: TestClient is used WITHOUT the context manager on purpose — that keeps
# the app's lifespan (heartbeat loop, DB-backed work) from starting during
# these unit tests, so they need no live database.
client = TestClient(app)


# ---------------------------------------------------------------------------
# Seeded developer (unit — auth service directly)
# ---------------------------------------------------------------------------

def test_seeded_developer_exists_and_is_active():
    """The bootstrap developer must be ACTIVE so email+password login works."""
    auth = AuthService()
    user = auth.get_user_by_email(config.DEVELOPER_EMAIL)

    assert user is not None, "Seeded developer should exist from DEVELOPER_EMAIL"
    assert user.role == Role.DEVELOPER
    assert user.status == UserStatus.ACTIVE


def test_seeded_developer_authenticates_without_mfa():
    """Email + password alone must yield a usable access token."""
    auth = AuthService()
    response = auth.authenticate(
        LoginRequest(email=config.DEVELOPER_EMAIL, password=config.DEVELOPER_PASSWORD),
        client_ip="unit-test-no-mfa",
    )

    assert response.requires_mfa is False
    assert response.access_token
    assert response.refresh_token

    user, tenant = auth.verify_access_token(response.access_token)
    assert user.email == config.DEVELOPER_EMAIL
    assert tenant is None  # developers are not tenant-bound


def test_wrong_password_is_rejected_at_service_level():
    """A bare auth service rejects bad credentials for the seeded developer."""
    auth = AuthService()
    # Use a throwaway account so we never trip the real developer's lockout.
    auth.create_user("locked-target@test.com", "correct-horse", Role.CLIENT, tenant_id=1)

    try:
        auth.authenticate(
            LoginRequest(email="locked-target@test.com", password="wrong"),
            client_ip="unit-test-bad-pw",
        )
        assert False, "Authentication should have failed"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Login endpoint + pages (API level)
# ---------------------------------------------------------------------------

def test_login_endpoint_returns_tokens_for_developer():
    response = client.post(
        "/api/auth/login",
        json={"email": config.DEVELOPER_EMAIL, "password": config.DEVELOPER_PASSWORD},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["role"] == "developer"


def test_protected_endpoint_needs_token():
    client.cookies.clear()
    assert client.get("/api/status").status_code == 401


def test_protected_endpoint_accepts_developer_token():
    login = client.post(
        "/api/auth/login",
        json={"email": config.DEVELOPER_EMAIL, "password": config.DEVELOPER_PASSWORD},
    )
    token = login.json()["access_token"]

    response = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert "memory_count" in response.json()


def test_login_page_is_the_entry_point():
    response = client.get("/")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_login_path_serves_login_page():
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_app_page_serves_dashboard_and_loads_auth():
    response = client.get("/app")
    assert response.status_code == 200
    # The dashboard must pull in the auth core so its fetch() calls authenticate.
    assert "/static/auth.js" in response.text


def test_static_auth_assets_are_served():
    for path in ("/static/auth.js", "/static/login.js", "/static/login.css"):
        assert client.get(path).status_code == 200, path

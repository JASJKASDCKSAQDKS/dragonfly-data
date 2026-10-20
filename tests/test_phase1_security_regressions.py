from fastapi.testclient import TestClient

from jarvis.auth.models import Role
from jarvis.auth.service import get_auth_service
from jarvis.web.server import app


client = TestClient(app)


def _developer_token() -> str:
    auth = get_auth_service()
    user = auth.get_user_by_email("phase1-developer@gmail.com")
    if user is None:
        user = auth.create_user(
            "phase1-developer@gmail.com",
            "phase1-test-password",
            Role.DEVELOPER,
        )
        user.status = "active"
        auth.update_user(user)

    response = client.post(
        "/api/auth/login",
        json={
            "email": "phase1-developer@gmail.com",
            "password": "phase1-test-password",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_legacy_chat_requires_developer_role():
    response = client.post(
        "/api/chat",
        json={"message": "inspect the system"},
    )
    assert response.status_code == 401


def test_legacy_voice_requires_developer_role():
    response = client.post("/api/voice/tts", json={"text": "hello"})
    assert response.status_code == 401


def test_developer_can_still_reach_legacy_status():
    token = _developer_token()
    response = client.get(
        "/api/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_login_sets_http_only_session_cookies():
    from jarvis import config

    response = client.post(
        "/api/auth/login",
        json={
            "email": config.DEVELOPER_EMAIL or "admin@localhost",
            "password": config.DEVELOPER_PASSWORD or "changeme123",
        },
    )
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any("jarvis_access=" in cookie and "HttpOnly" in cookie for cookie in cookies)
    assert any("jarvis_refresh=" in cookie and "HttpOnly" in cookie for cookie in cookies)

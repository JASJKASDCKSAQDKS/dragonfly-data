from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from jarvis import config
from jarvis.assistant.service import _assistant_services, get_assistant_service
from jarvis.auth.client_accounts import ClientAccount
from jarvis.auth.models import Role, Tenant, User
from jarvis.auth.dependencies import require_developer
from jarvis.web.server import app


def _developer() -> User:
    return User(
        id=9001,
        email="security-test-developer@example.com",
        password_hash="unused",
        role=Role.DEVELOPER,
    )


def _account() -> ClientAccount:
    timestamp = datetime.now(timezone.utc).isoformat()
    return ClientAccount(
        id=1,
        db_name="redaction_test",
        display_name="Redaction Test",
        username="redaction_test",
        email="redaction_test@example.com",
        password="persistent-login-secret",
        password_hash="persistent-password-hash",
        db_user="persistent-db-user",
        db_password="persistent-db-secret",
        tenant_id=42,
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_client_listing_redacts_all_persistent_credentials(monkeypatch):
    """The developer client API must not disclose stored credential material."""
    import jarvis.auth.client_routes as client_routes

    monkeypatch.setattr(client_routes, "list_client_accounts", lambda: [_account()])
    app.dependency_overrides[require_developer] = lambda: _developer()
    try:
        response = TestClient(app).get("/api/clients")
    finally:
        app.dependency_overrides.pop(require_developer, None)

    assert response.status_code == 200, response.text
    payload = response.json()["clients"][0]
    assert "password" not in payload
    assert "password_hash" not in payload
    assert "db_user" not in payload
    assert "db_password" not in payload
    assert "persistent-login-secret" not in response.text
    assert "persistent-db-secret" not in response.text


def test_same_tenant_assistant_sessions_are_owned_by_user(monkeypatch):
    """A client in the same tenant cannot read or delete another user's session."""
    data_dir = Path("test_session_ownership_data")
    shutil.rmtree(data_dir, ignore_errors=True)
    monkeypatch.setattr(config, "DATA_DIR", str(data_dir))
    tenant = Tenant(
        id=9101,
        name="same_tenant",
        display_name="Same Tenant",
        db_name="same_tenant",
        db_user="db_user",
        db_password="db_password",
    )
    _assistant_services.clear()
    owner = get_assistant_service(tenant, user_id=101)
    other_user = get_assistant_service(tenant, user_id=202)
    owner.conversation_manager.add_turn(
        owner._session_key("shared-session"), "user", "owner's private message"
    )

    try:
        assert [turn.content for turn in owner.get_conversation_history("shared-session")] == [
            "owner's private message"
        ]
        assert other_user.get_conversation_history("shared-session") == []
        assert other_user.get_recent_sessions() == []
        assert other_user.delete_session("shared-session") == 0
        assert [turn.content for turn in owner.get_conversation_history("shared-session")] == [
            "owner's private message"
        ]
    finally:
        _assistant_services.clear()
        shutil.rmtree(data_dir, ignore_errors=True)

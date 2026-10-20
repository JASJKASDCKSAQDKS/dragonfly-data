from pathlib import Path

from fastapi.testclient import TestClient

from jarvis.auth.models import LoginRequest, Role
from jarvis.auth.service import get_auth_service
from jarvis.imports.service import ImportJobService
from jarvis.privacy import PrivacyRequestService
from jarvis.tenants.models import Tenant
from jarvis.web.server import app
import jarvis.tenants.routes as tenant_routes


def test_import_job_registry_round_trips_and_is_tenant_scoped(tmp_path: Path):
    service = ImportJobService(str(tmp_path / "jobs.json"))
    job = service.create(7, "sales", "sales.csv")
    assert service.get(job.id, tenant_id=7).status == "queued"
    assert service.get(job.id, tenant_id=8) is None
    service.update(job.id, status="completed", rows_imported=12)
    reloaded = ImportJobService(str(tmp_path / "jobs.json"))
    assert reloaded.get(job.id).rows_imported == 12


def test_privacy_requests_are_request_only_and_persist(tmp_path: Path):
    service = PrivacyRequestService(str(tmp_path / "privacy.json"))
    item = service.create(7, "deletion", requested_by=3)
    assert item["status"] == "requested"
    assert service.list(tenant_id=8) == []
    assert PrivacyRequestService(str(tmp_path / "privacy.json")).list()[0]["type"] == "deletion"


def test_developer_privacy_endpoint_does_not_delete(monkeypatch, tmp_path: Path):
    tenant = Tenant(7, "demo", "Demo", "demo", "u", "p")
    monkeypatch.setattr(tenant_routes, "get_tenant_service",
                        lambda: type("S", (), {"get_tenant": lambda self, _: tenant})())
    monkeypatch.setattr(tenant_routes, "get_privacy_request_service",
                        lambda: PrivacyRequestService(str(tmp_path / "privacy.json")))
    auth = get_auth_service()
    user = auth.get_user_by_email("surface-developer@example.com")
    if user is None:
        user = auth.create_user("surface-developer@example.com", "surface-password", Role.DEVELOPER)
        user.status = "active"
        auth.update_user(user)
    token = auth.authenticate(
        LoginRequest(email=user.email, password="surface-password"),
        client_ip="surface-test",
    ).access_token
    response = TestClient(app).post(
        "/api/tenants/7/privacy-requests",
        headers={"Authorization": f"Bearer {token}"},
        json={"request_type": "deletion"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "requested"
    assert tenant.status == "active"

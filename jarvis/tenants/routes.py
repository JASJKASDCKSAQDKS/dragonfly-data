"""
Tenant management API routes (developer only).

Endpoints:
- POST /api/tenants - Create tenant
- GET /api/tenants - List tenants
- GET /api/tenants/{tenant_id} - Get tenant details
- POST /api/tenants/{tenant_id}/suspend - Suspend tenant
- POST /api/tenants/{tenant_id}/reactivate - Reactivate tenant
- DELETE /api/tenants/{tenant_id} - Delete tenant (irreversible)
- POST /api/tenants/{tenant_id}/migrate - Run migrations
- GET /api/tenants/{tenant_id}/settings - Get tenant settings
- PUT /api/tenants/{tenant_id}/settings - Update tenant settings
- GET /api/tenants/{tenant_id}/test-connection - Test DB connection
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from jarvis.auth.dependencies import require_developer
from jarvis.auth.models import User
from jarvis.tenants.models import Tenant, TenantSettings
from jarvis.tenants.service import get_tenant_service
from jarvis.rails.audit import log_event
from jarvis.imports.service import get_import_job_service
from jarvis.privacy import get_privacy_request_service

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


class TenantCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(..., min_length=1, max_length=150)
    timezone: str = "UTC"
    business_day_start_hour: int = Field(default=6, ge=0, le=23)


class TenantResponse(BaseModel):
    id: int
    name: str
    display_name: str
    db_name: str
    db_user: str
    status: str
    timezone: str
    business_day_start_hour: int
    created_at: str
    updated_at: str


class TenantSettingsRequest(BaseModel):
    cache_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    ai_model: str = Field(default="ollama", pattern=r"^(ollama|gemini)$")
    ai_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    date_format: str = Field(default="DD/MM/YYYY")
    enable_voice: bool = True
    enable_ai_assistant: bool = True
    enable_3d_animation: bool = False


class TenantSettingsResponse(BaseModel):
    tenant_id: int
    cache_ttl_seconds: int
    ai_model: str
    ai_temperature: float
    currency: str
    date_format: str
    enable_voice: bool
    enable_ai_assistant: bool
    enable_3d_animation: bool


class PrivacyRequestCreate(BaseModel):
    """A request is queued for operator review; it never deletes data."""
    request_type: str = Field(..., pattern=r"^(export|deletion)$")


def _tenant_or_404(tenant_id: int):
    tenant = get_tenant_service().get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("/{tenant_id}/imports")
async def list_import_jobs(
    tenant_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(require_developer),
):
    """Developer-only demo import status list (metadata only)."""
    _tenant_or_404(tenant_id)
    jobs = get_import_job_service().list(tenant_id=tenant_id, limit=limit)
    return {"jobs": [job.__dict__ for job in jobs]}


@router.get("/{tenant_id}/imports/{job_id}")
async def get_import_job(tenant_id: int, job_id: str, user: User = Depends(require_developer)):
    """Return one tenant-scoped import job without exposing imported data."""
    _tenant_or_404(tenant_id)
    job = get_import_job_service().get(job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
    return job.__dict__


@router.get("/{tenant_id}/privacy-requests")
async def list_privacy_requests(tenant_id: int, user: User = Depends(require_developer)):
    """List GDPR export/deletion requests for operator review."""
    _tenant_or_404(tenant_id)
    return {"requests": get_privacy_request_service().list(tenant_id=tenant_id)}


@router.post("/{tenant_id}/privacy-requests", status_code=status.HTTP_202_ACCEPTED)
async def create_privacy_request(
    tenant_id: int,
    request: PrivacyRequestCreate,
    user: User = Depends(require_developer),
):
    """Queue an export or deletion request.

    This demo intentionally performs no export and no deletion. A separate,
    reviewed worker must fulfill requests after identity, legal-hold, backup,
    and retention checks.
    """
    _tenant_or_404(tenant_id)
    item = get_privacy_request_service().create(tenant_id, request.request_type, user.id)
    log_event("PRIVACY", request.request_type.upper() + "_REQUESTED",
              {"tenant_id": tenant_id, "request_id": item["id"]}, user_id=user.id)
    return item


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(request: TenantCreateRequest, user: User = Depends(require_developer)):
    """Create a new tenant with database and read-only user."""
    tenant_service = get_tenant_service()
    
    try:
        tenant = tenant_service.create_tenant(
            name=request.name,
            display_name=request.display_name,
            timezone=request.timezone,
            business_day_start_hour=request.business_day_start_hour,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    log_event("TENANT", "CREATED", {"tenant_id": tenant.id, "name": tenant.name}, user_id=user.id)
    
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        display_name=tenant.display_name,
        db_name=tenant.db_name,
        db_user=tenant.db_user,
        status=tenant.status,
        timezone=tenant.timezone,
        business_day_start_hour=tenant.business_day_start_hour,
        created_at=tenant.created_at.isoformat(),
        updated_at=tenant.updated_at.isoformat(),
    )


@router.get("", response_model=list[TenantResponse])
async def list_tenants(user: User = Depends(require_developer)):
    """List all tenants."""
    tenant_service = get_tenant_service()
    tenants = tenant_service.list_tenants()
    
    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            display_name=t.display_name,
            db_name=t.db_name,
            db_user=t.db_user,
            status=t.status,
            timezone=t.timezone,
            business_day_start_hour=t.business_day_start_hour,
            created_at=t.created_at.isoformat(),
            updated_at=t.updated_at.isoformat(),
        )
        for t in tenants
    ]


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: int, user: User = Depends(require_developer)):
    """Get tenant details."""
    tenant_service = get_tenant_service()
    tenant = tenant_service.get_tenant(tenant_id)
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        display_name=tenant.display_name,
        db_name=tenant.db_name,
        db_user=tenant.db_user,
        status=tenant.status,
        timezone=tenant.timezone,
        business_day_start_hour=tenant.business_day_start_hour,
        created_at=tenant.created_at.isoformat(),
        updated_at=tenant.updated_at.isoformat(),
    )


@router.post("/{tenant_id}/suspend")
async def suspend_tenant(tenant_id: int, user: User = Depends(require_developer)):
    """Suspend a tenant."""
    tenant_service = get_tenant_service()
    
    if not tenant_service.suspend_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    log_event("TENANT", "SUSPENDED", {"tenant_id": tenant_id}, user_id=user.id)
    
    return {"status": "success", "message": "Tenant suspended"}


@router.post("/{tenant_id}/reactivate")
async def reactivate_tenant(tenant_id: int, user: User = Depends(require_developer)):
    """Reactivate a suspended tenant."""
    tenant_service = get_tenant_service()
    
    if not tenant_service.reactivate_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    log_event("TENANT", "REACTIVATED", {"tenant_id": tenant_id}, user_id=user.id)
    
    return {"status": "success", "message": "Tenant reactivated"}


@router.delete("/{tenant_id}")
async def delete_tenant(tenant_id: int, user: User = Depends(require_developer)):
    """Delete a tenant and its database (irreversible!)."""
    tenant_service = get_tenant_service()
    
    if not tenant_service.delete_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    log_event("TENANT", "DELETED", {"tenant_id": tenant_id}, user_id=user.id)
    
    return {"status": "success", "message": "Tenant deleted"}


@router.post("/{tenant_id}/migrate")
async def run_migrations(tenant_id: int, user: User = Depends(require_developer)):
    """Run database migrations for tenant."""
    tenant_service = get_tenant_service()
    
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    success = tenant_service.run_migrations(tenant_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Migration failed",
        )
    
    return {"status": "success", "message": "Migrations applied"}


@router.get("/{tenant_id}/settings", response_model=TenantSettingsResponse)
async def get_tenant_settings(tenant_id: int, user: User = Depends(require_developer)):
    """Get tenant settings."""
    tenant_service = get_tenant_service()
    
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    settings = tenant_service.get_settings(tenant_id)
    
    return TenantSettingsResponse(
        tenant_id=settings.tenant_id,
        cache_ttl_seconds=settings.cache_ttl_seconds,
        ai_model=settings.ai_model,
        ai_temperature=settings.ai_temperature,
        currency=settings.currency,
        date_format=settings.date_format,
        enable_voice=settings.enable_voice,
        enable_ai_assistant=settings.enable_ai_assistant,
        enable_3d_animation=settings.enable_3d_animation,
    )


@router.put("/{tenant_id}/settings", response_model=TenantSettingsResponse)
async def update_tenant_settings(
    tenant_id: int,
    request: TenantSettingsRequest,
    user: User = Depends(require_developer),
):
    """Update tenant settings."""
    tenant_service = get_tenant_service()
    
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    settings = TenantSettings(
        tenant_id=tenant_id,
        cache_ttl_seconds=request.cache_ttl_seconds,
        ai_model=request.ai_model,
        ai_temperature=request.ai_temperature,
        currency=request.currency,
        date_format=request.date_format,
        enable_voice=request.enable_voice,
        enable_ai_assistant=request.enable_ai_assistant,
        enable_3d_animation=request.enable_3d_animation,
    )
    
    updated = tenant_service.update_settings(tenant_id, settings)
    
    return TenantSettingsResponse(
        tenant_id=updated.tenant_id,
        cache_ttl_seconds=updated.cache_ttl_seconds,
        ai_model=updated.ai_model,
        ai_temperature=updated.ai_temperature,
        currency=updated.currency,
        date_format=updated.date_format,
        enable_voice=updated.enable_voice,
        enable_ai_assistant=updated.enable_ai_assistant,
        enable_3d_animation=updated.enable_3d_animation,
    )


@router.get("/{tenant_id}/test-connection")
async def test_tenant_connection(tenant_id: int, user: User = Depends(require_developer)):
    """Test connection to tenant database (read-only user)."""
    tenant_service = get_tenant_service()
    
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    # Test read-only connection
    ro_ok = tenant_service.test_tenant_connection(tenant_id, read_only=True)
    # Test admin connection
    admin_ok = tenant_service.test_tenant_connection(tenant_id, read_only=False)
    
    return {
        "tenant_id": tenant_id,
        "read_only_connection": ro_ok,
        "admin_connection": admin_ok,
    }
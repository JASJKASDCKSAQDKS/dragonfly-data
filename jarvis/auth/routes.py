"""
Authentication API routes.

Endpoints:
- POST /api/auth/login - Login with email/password (+ MFA)
- POST /api/auth/refresh - Refresh access token
- POST /api/auth/logout - Revoke refresh token
- GET /api/auth/me - Get current user info
- POST /api/auth/mfa/setup - Setup MFA (developer only)
- POST /api/auth/mfa/verify - Verify MFA code
- GET /api/auth/mfa/qr - Get MFA QR code
- POST /api/auth/tenants - Create tenant (developer only)
- GET /api/auth/tenants - List tenants (developer only)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from jarvis.auth.models import (
    LoginRequest, LoginResponse, RefreshRequest, RefreshResponse,
    UserResponse, TenantCreateRequest, TenantResponse,
    MFASetupResponse, MFAVerifyRequest,
    Role, UserStatus,
)
from jarvis.auth.service import get_auth_service
from jarvis.auth.dependencies import (
    get_current_user, require_developer, require_client, get_current_tenant,
)
from jarvis.rails.audit import log_event

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set browser session cookies while retaining token fields for native clients."""
    from jarvis import config

    common = {
        "secure": config.AUTH_COOKIE_SECURE,
        "httponly": True,
        "samesite": config.AUTH_COOKIE_SAMESITE,
        "domain": config.AUTH_COOKIE_DOMAIN,
        "path": "/",
    }
    response.set_cookie(
        config.AUTH_COOKIE_NAME,
        access_token,
        max_age=15 * 60,
        **common,
    )
    response.set_cookie(
        config.REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=30 * 24 * 60 * 60,
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    from jarvis import config

    response.delete_cookie(config.AUTH_COOKIE_NAME, path="/", domain=config.AUTH_COOKIE_DOMAIN)
    response.delete_cookie(config.REFRESH_COOKIE_NAME, path="/", domain=config.AUTH_COOKIE_DOMAIN)


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, http_request: Request, http_response: Response):
    """Login with email and password. Returns access + refresh tokens."""
    client_ip = http_request.client.host if http_request.client else "unknown"
    auth_service = get_auth_service()
    
    try:
        auth_response = auth_service.authenticate(request, client_ip)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    
    # If MFA required, return special response
    if auth_response.requires_mfa:
        log_event("AUTH", "LOGIN_MFA_REQUIRED", {"email": request.email}, status="CHALLENGE")
        return LoginResponse(
            access_token="",
            refresh_token="",
            expires_in=0,
            user=auth_response.user,
            requires_mfa=True,
        )
    
    _set_auth_cookies(http_response, auth_response.access_token, auth_response.refresh_token)
    log_event(
        "AUTH",
        "LOGIN_SUCCESS",
        {"user_id": auth_response.user.id, "role": auth_response.user.role.value},
        status="SUCCESS",
    )
    return auth_response


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: RefreshRequest, http_request: Request, http_response: Response):
    """Rotate refresh token and get new access token."""
    auth_service = get_auth_service()
    
    try:
        token = request.refresh_token or http_request.cookies.get("jarvis_refresh")
        auth_response = auth_service.refresh_tokens(RefreshRequest(refresh_token=token))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    
    _set_auth_cookies(http_response, auth_response.access_token, auth_response.refresh_token)
    log_event("AUTH", "TOKEN_REFRESH", {}, status="SUCCESS")
    return auth_response


@router.post("/logout")
async def logout(request: RefreshRequest, http_request: Request, http_response: Response):
    """Revoke refresh token (logout)."""
    auth_service = get_auth_service()
    
    # Find and revoke the refresh token
    import hashlib
    from jarvis import config
    refresh_token = request.refresh_token or http_request.cookies.get(config.REFRESH_COOKIE_NAME)
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest() if refresh_token else ""
    
    for rt in auth_service._refresh_tokens.values():
        if rt.token_hash == token_hash:
            from datetime import datetime, timezone
            rt.revoked_at = datetime.now(timezone.utc)
            break
    _clear_auth_cookies(http_response)
    log_event("AUTH", "LOGOUT", {}, status="SUCCESS")
    return {"status": "success", "message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user info."""
    auth_service = get_auth_service()
    tenant = None
    if user.tenant_id:
        tenant = auth_service.get_tenant_by_id(user.tenant_id)
    
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id,
        client_display_name=user.client_display_name,
        status=user.status,
    )


# MFA endpoints (developer only)

@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(user: User = Depends(require_developer)):
    """Setup MFA for developer account. Returns secret and QR code URI."""
    auth_service = get_auth_service()
    return auth_service.setup_mfa(user.id)


@router.post("/mfa/verify")
async def verify_mfa(request: MFAVerifyRequest, user: User = Depends(require_developer)):
    """Verify MFA code during setup or login."""
    auth_service = get_auth_service()
    
    if not auth_service.verify_mfa(user.id, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA code",
        )
    
    # If user was PENDING_MFA, activate them
    if user.status == UserStatus.PENDING_MFA:
        user.status = UserStatus.ACTIVE
        auth_service.update_user(user)
    
    return {"status": "success", "message": "MFA verified"}


@router.get("/mfa/qr")
async def get_mfa_qr(user: User = Depends(require_developer)):
    """Get MFA QR code as PNG image."""
    auth_service = get_auth_service()
    
    try:
        qr_bytes = auth_service.get_mfa_qr_code(user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    return Response(content=qr_bytes, media_type="image/png")


# Tenant management (developer only)

@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(request: TenantCreateRequest, user: User = Depends(require_developer)):
    """Create a new tenant with admin user."""
    auth_service = get_auth_service()
    
    try:
        tenant, admin_user = auth_service.create_tenant(request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        display_name=tenant.display_name,
        db_name=tenant.db_name,
        status=tenant.status,
        timezone=tenant.timezone,
        business_day_start_hour=tenant.business_day_start_hour,
        created_at=tenant.created_at,
    )


@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(user: User = Depends(require_developer)):
    """List all tenants."""
    auth_service = get_auth_service()
    tenants = auth_service.list_tenants()
    
    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            display_name=t.display_name,
            db_name=t.db_name,
            status=t.status,
            timezone=t.timezone,
            business_day_start_hour=t.business_day_start_hour,
            created_at=t.created_at,
        )
        for t in tenants
    ]


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(tenant_id: int, user: User = Depends(require_developer)):
    """Suspend a tenant."""
    auth_service = get_auth_service()
    
    if not auth_service.suspend_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    return {"status": "success", "message": "Tenant suspended"}


@router.post("/tenants/{tenant_id}/reactivate")
async def reactivate_tenant(tenant_id: int, user: User = Depends(require_developer)):
    """Reactivate a suspended tenant."""
    auth_service = get_auth_service()
    
    if not auth_service.reactivate_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    
    return {"status": "success", "message": "Tenant reactivated"}
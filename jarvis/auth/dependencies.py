"""
FastAPI dependencies for authentication and authorization.

Provides dependencies for:
- Getting current authenticated user
- Requiring specific roles (developer, client)
- Resolving tenant from token (never from client input)
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jarvis.auth.models import Role, User, Tenant
from jarvis.auth.service import get_auth_service
from jarvis import config

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """Get the current authenticated user from the access token."""
    token = (
        request.cookies.get(config.AUTH_COOKIE_NAME)
        or (credentials.credentials if credentials else None)
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    auth_service = get_auth_service()
    try:
        user, tenant = auth_service.verify_access_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Attach tenant to request state for downstream use
    request.state.user = user
    request.state.tenant = tenant
    
    return user


async def get_current_tenant(
    request: Request,
    user: User = Depends(get_current_user),
) -> Optional[Tenant]:
    """Resolve the active client tenant from the verified authentication context."""
    if user.role != Role.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client access required",
        )

    tenant = getattr(request.state, "tenant", None)
    if tenant is None or not tenant.is_active():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active tenant",
        )
    return tenant


def require_role(*allowed_roles: Role):
    """Dependency that requires the user to have one of the allowed roles."""
    async def _require_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in allowed_roles]}",
            )
        return user
    return _require_role


def require_tenant(user: User = Depends(get_current_user)) -> Tenant:
    """Dependency that requires the user to be a client with an active tenant."""
    if user.role != Role.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client access required",
        )
    
    from jarvis.auth.service import get_auth_service
    auth_service = get_auth_service()
    tenant = auth_service.get_tenant_by_id(user.tenant_id) if user.tenant_id else None

    if tenant is None or not tenant.is_active():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active tenant",
        )
    
    return tenant


def require_developer(user: User = Depends(get_current_user)) -> User:
    """Dependency that requires developer role."""
    if user.role != Role.DEVELOPER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Developer access required",
        )
    return user


# Convenience dependencies
require_client = require_role(Role.CLIENT)
require_developer = require_role(Role.DEVELOPER)
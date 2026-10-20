"""
Authentication & Authorization module for Jarvis.

Provides:
- User and Tenant models with roles
- Argon2 password hashing
- JWT access/refresh tokens with rotation
- Rate limiting and account lockout
- TOTP MFA for developer accounts
- FastAPI dependencies for auth/tenant resolution
"""

from jarvis.auth.models import User, Tenant, Role, RefreshToken, MFASecret
from jarvis.auth.service import AuthService
from jarvis.auth.dependencies import (
    get_current_user,
    require_role,
    require_tenant,
    get_current_tenant,
)
from jarvis.auth.routes import router as auth_router

__all__ = [
    "User",
    "Tenant", 
    "Role",
    "RefreshToken",
    "MFASecret",
    "AuthService",
    "get_current_user",
    "require_role",
    "require_tenant",
    "get_current_tenant",
    "auth_router",
]
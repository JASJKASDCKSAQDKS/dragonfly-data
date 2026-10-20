"""
Authentication models for Jarvis.

Defines the core data models for users, tenants, roles, tokens, and MFA.
"""

from __future__ import annotations

import enum
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from pydantic import BaseModel, EmailStr, Field

from jarvis import config


class Role(str, enum.Enum):
    """User roles in the system."""
    DEVELOPER = "developer"      # Full access: create/suspend tenants, manage users, imports, audit, health
    CLIENT = "client"            # Read-only: own business dashboard, AI assistant


class UserStatus(str, enum.Enum):
    """User account status."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_MFA = "pending_mfa"  # Developer awaiting MFA setup


@dataclass
class User:
    """User account."""
    id: int
    email: str
    password_hash: str
    role: Role
    tenant_id: Optional[int] = None  # None for developers, set for clients
    # Client-portal accounts link to a business database rather than a managed
    # tenant; these carry the generated login's database + pretty name.
    client_db_name: Optional[str] = None
    client_display_name: Optional[str] = None
    status: UserStatus = UserStatus.ACTIVE
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_locked(self) -> bool:
        """Check if account is currently locked."""
        if self.locked_until and self.locked_until > datetime.now(timezone.utc):
            return True
        return False

    def is_developer(self) -> bool:
        return self.role == Role.DEVELOPER

    def is_client(self) -> bool:
        return self.role == Role.CLIENT


@dataclass
class Tenant:
    """Tenant (business) account."""
    id: int
    name: str
    display_name: str
    db_name: str
    db_user: str
    db_password: str
    status: str = "active"  # active, suspended
    timezone: str = "UTC"
    business_day_start_hour: int = 6  # 6am default for bars/shops
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_active(self) -> bool:
        return self.status == "active"


@dataclass
class RefreshToken:
    """Rotating refresh token."""
    id: int
    user_id: int
    token_hash: str  # SHA-256 of the token
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: Optional[datetime] = None
    replaced_by_token_hash: Optional[str] = None  # For rotation tracking

    def is_valid(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(timezone.utc)


@dataclass
class MFASecret:
    """TOTP MFA secret for developer accounts."""
    id: int
    user_id: int
    secret: str  # Base32 encoded secret
    is_verified: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    verified_at: Optional[datetime] = None


# Pydantic models for API requests/responses

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_code: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserResponse"
    requires_mfa: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str = ""


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: int
    email: str
    role: Role
    tenant_id: Optional[int] = None
    client_display_name: Optional[str] = None
    status: UserStatus


class TenantCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(..., min_length=1, max_length=150)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=12)
    timezone: str = "UTC"
    business_day_start_hour: int = Field(default=6, ge=0, le=23)


class TenantResponse(BaseModel):
    id: int
    name: str
    display_name: str
    db_name: str
    status: str
    timezone: str
    business_day_start_hour: int
    created_at: datetime


class MFASetupResponse(BaseModel):
    secret: str
    qr_code_uri: str  # otpauth:// URI for QR code


class MFAVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


# Token configuration
ACCESS_TOKEN_EXPIRE_MINUTES = 15
# Client owners asked to remain signed in for 30 days. Refresh tokens are
# rotated on every use, so the session remains revocable while active.
REFRESH_TOKEN_EXPIRE_DAYS = 30
JWT_ALGORITHM = "HS256"


def create_access_token(user: User, tenant: Optional[Tenant] = None) -> str:
    """Create a short-lived JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "tenant_id": tenant.id if tenant else None,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    
    secret = config.JWT_SECRET_KEY
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def create_refresh_token(user: User) -> tuple[str, str]:
    """Create a refresh token and return (plain_token, token_hash)."""
    plain_token = secrets.token_urlsafe(32)
    import hashlib
    token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
    return plain_token, token_hash


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    secret = config.JWT_SECRET_KEY
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its Argon2 hash."""
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    try:
        ph.verify(password_hash, password)
        return True
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    return ph.hash(password)


# Update forward references
UserResponse.model_rebuild()

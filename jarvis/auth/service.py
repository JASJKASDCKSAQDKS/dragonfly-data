"""
Authentication service for Jarvis.

Handles user authentication, token management, MFA, rate limiting, and account lockout.
"""

from __future__ import annotations

import hashlib
import logging
import pyotp
import qrcode
import secrets
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional, Tuple

import jwt
from argon2 import PasswordHasher

from jarvis import config
from jarvis.auth.models import (
    User, Tenant, Role, UserStatus, RefreshToken, MFASecret,
    LoginRequest, LoginResponse, RefreshRequest, RefreshResponse,
    UserResponse, TenantCreateRequest, TenantResponse,
    MFASetupResponse, MFAVerifyRequest,
    create_access_token, create_refresh_token, decode_token,
    verify_password, hash_password,
    ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, JWT_ALGORITHM,
)

log = logging.getLogger(__name__)

# Rate limiting: max 5 requests per second per IP
RATE_LIMIT_WINDOW = 1.0  # seconds
RATE_LIMIT_MAX_REQUESTS = 5

# Account lockout: 5 failed attempts -> 15 minute lockout
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

# In-memory rate limit store (use Redis in production)
_rate_limit_store: dict[str, list[float]] = {}


class AuthService:
    """Authentication service with user management, tokens, MFA, and security features."""
    
    def __init__(self):
        self._ph = PasswordHasher()
        # In-memory stores (replace with database in production)
        self._users: dict[int, User] = {}
        self._users_by_email: dict[str, User] = {}
        self._tenants: dict[int, Tenant] = {}
        self._refresh_tokens: dict[int, RefreshToken] = {}
        self._mfa_secrets: dict[int, MFASecret] = {}
        self._next_user_id = 1
        self._next_tenant_id = 1
        self._next_token_id = 1
        self._next_mfa_id = 1
        
        # Create default developer user if none exists
        self._ensure_default_developer()
        # Load the persisted client-portal logins (one per business database).
        self.load_client_accounts()
    
    def _ensure_default_developer(self):
        """Create a default developer user from environment if no users exist."""
        if not self._users:
            dev_email = config.DEVELOPER_EMAIL or "admin@localhost"
            dev_password = config.DEVELOPER_PASSWORD or "changeme123"
            
            user = User(
                id=self._next_user_id,
                email=dev_email,
                password_hash=hash_password(dev_password),
                role=Role.DEVELOPER,
                # Seeded developer logs in with email + password only.
                # MFA is optional and never forced onto the bootstrap account.
                status=UserStatus.ACTIVE,
            )
            self._next_user_id += 1
            self._users[user.id] = user
            self._users_by_email[user.email] = user
            log.info(f"Created default developer user: {dev_email}")

    def load_client_accounts(self):
        """Register persisted client-portal logins so their owners can sign in.

        Called at startup and again whenever a database provisions an account.
        Existing users are refreshed in place (password hash + status) so a
        rotated password or a suspension takes effect without a restart.
        """
        from jarvis.auth import client_accounts

        client_accounts.migrate_legacy_email_domains()
        now = datetime.now(timezone.utc)
        accounts = client_accounts.list_client_accounts()
        for account in accounts:
            email = account.email.lower()
            status = (
                UserStatus.ACTIVE if account.status == "active"
                else UserStatus.SUSPENDED
            )
            existing = self._users_by_email.get(email)
            if existing is not None:
                existing.password_hash = account.password_hash
                existing.role = Role.CLIENT
                existing.status = status
                existing.tenant_id = account.tenant_id
                existing.client_db_name = account.db_name
                existing.client_display_name = account.display_name
                existing.updated_at = now
                self._users[existing.id] = existing
                continue

            user = User(
                id=self._next_user_id,
                email=email,
                password_hash=account.password_hash,
                role=Role.CLIENT,
                tenant_id=account.tenant_id,
                client_db_name=account.db_name,
                client_display_name=account.display_name,
                status=status,
            )
            self._next_user_id += 1
            self._users[user.id] = user
            self._users_by_email[email] = user
        log.info("Loaded %d client portal account(s)", len(accounts))
    
    # -----------------------------------------------------------------------
    # Rate Limiting
    # -----------------------------------------------------------------------
    
    def check_rate_limit(self, identifier: str) -> bool:
        """Check if identifier has exceeded rate limit. Returns True if allowed."""
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW
        
        if identifier not in _rate_limit_store:
            _rate_limit_store[identifier] = []
        
        # Clean old entries
        _rate_limit_store[identifier] = [
            t for t in _rate_limit_store[identifier] if t > window_start
        ]
        
        if len(_rate_limit_store[identifier]) >= RATE_LIMIT_MAX_REQUESTS:
            return False
        
        _rate_limit_store[identifier].append(now)
        return True
    
    # -----------------------------------------------------------------------
    # User Management
    # -----------------------------------------------------------------------
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        return self._users_by_email.get(email.lower())
    
    def create_user(
        self,
        email: str,
        password: str,
        role: Role,
        tenant_id: Optional[int] = None,
    ) -> User:
        """Create a new user."""
        email = email.lower()
        if email in self._users_by_email:
            raise ValueError("Email already registered")
        
        user = User(
            id=self._next_user_id,
            email=email,
            password_hash=hash_password(password),
            role=role,
            tenant_id=tenant_id,
            status=UserStatus.PENDING_MFA if role == Role.DEVELOPER else UserStatus.ACTIVE,
        )
        self._next_user_id += 1
        self._users[user.id] = user
        self._users_by_email[email] = user
        return user
    
    def update_user(self, user: User) -> User:
        """Update user (call after modifying user fields)."""
        user.updated_at = datetime.now(timezone.utc)
        self._users[user.id] = user
        self._users_by_email[user.email] = user
        return user
    
    # -----------------------------------------------------------------------
    # Tenant Management
    # -----------------------------------------------------------------------
    
    def get_tenant_by_id(self, tenant_id: int) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)
    
    def get_tenant_by_db_name(self, db_name: str) -> Optional[Tenant]:
        for tenant in self._tenants.values():
            if tenant.db_name == db_name:
                return tenant
        return None
    
    def create_tenant(self, request: TenantCreateRequest) -> Tuple[Tenant, User]:
        """Create a new tenant with an admin user."""
        # Check if tenant name/db_name already exists
        for t in self._tenants.values():
            if t.name == request.name:
                raise ValueError("Tenant name already exists")
            if t.db_name == request.name:
                raise ValueError("Database name already exists")
        
        # Generate DB credentials
        db_name = request.name
        db_user = f"tenant_{request.name}"
        db_password = secrets.token_urlsafe(24)
        
        tenant = Tenant(
            id=self._next_tenant_id,
            name=request.name,
            display_name=request.display_name,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            timezone=request.timezone,
            business_day_start_hour=request.business_day_start_hour,
        )
        self._next_tenant_id += 1
        self._tenants[tenant.id] = tenant
        
        # Create admin user for this tenant
        admin_user = self.create_user(
            email=request.admin_email,
            password=request.admin_password,
            role=Role.CLIENT,
            tenant_id=tenant.id,
        )
        
        return tenant, admin_user
    
    def list_tenants(self) -> list[Tenant]:
        return list(self._tenants.values())
    
    def suspend_tenant(self, tenant_id: int) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.status = "suspended"
        tenant.updated_at = datetime.now(timezone.utc)
        return True
    
    def reactivate_tenant(self, tenant_id: int) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.status = "active"
        tenant.updated_at = datetime.now(timezone.utc)
        return True
    
    # -----------------------------------------------------------------------
    # Authentication
    # -----------------------------------------------------------------------
    
    def authenticate(self, request: LoginRequest, client_ip: str) -> LoginResponse:
        """Authenticate user with email/password and optional MFA."""
        # Rate limiting
        if not self.check_rate_limit(f"login:{client_ip}"):
            raise ValueError("Too many login attempts. Please wait.")
        
        user = self.get_user_by_email(request.email)
        if not user:
            # Don't reveal if email exists
            time.sleep(0.5)  # Timing attack mitigation
            raise ValueError("Invalid credentials")
        
        # Check account lockout
        if user.is_locked():
            raise ValueError("Account temporarily locked. Try again later.")
        
        # Verify password
        if not verify_password(request.password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                log.warning(f"Account locked for {user.email} after {MAX_FAILED_ATTEMPTS} failed attempts")
            self.update_user(user)
            raise ValueError("Invalid credentials")
        
        # Reset failed attempts on successful password
        user.failed_login_attempts = 0
        user.locked_until = None

        if user.status == UserStatus.SUSPENDED:
            raise ValueError("Account suspended")
        
        # Check MFA for developers
        if user.is_developer() and config.DEVELOPER_MFA_REQUIRED:
            mfa_secret = self._mfa_secrets.get(user.id)
            if mfa_secret and mfa_secret.is_verified:
                if not request.mfa_code:
                    return LoginResponse(
                        access_token="",
                        refresh_token="",
                        user=self._user_to_response(user),
                        requires_mfa=True,
                    )
                if not self.verify_mfa(user.id, request.mfa_code):
                    raise ValueError("Invalid MFA code")
            elif mfa_secret and not mfa_secret.is_verified:
                # MFA setup in progress
                if not request.mfa_code:
                    return LoginResponse(
                        access_token="",
                        refresh_token="",
                        user=self._user_to_response(user),
                        requires_mfa=True,
                    )
                if not self.verify_mfa(user.id, request.mfa_code):
                    raise ValueError("Invalid MFA code")
                # Mark MFA as verified
                mfa_secret.is_verified = True
                mfa_secret.verified_at = datetime.now(timezone.utc)
        
        # Update last login
        user.last_login = datetime.now(timezone.utc)
        self.update_user(user)
        
        # Get tenant if client
        tenant = None
        if user.tenant_id:
            tenant = self.get_tenant_by_id(user.tenant_id)
            if not tenant or not tenant.is_active():
                raise ValueError("Tenant is suspended")
        
        # Create tokens
        access_token = create_access_token(user, tenant)
        refresh_plain, refresh_hash = create_refresh_token(user)
        
        # Store refresh token
        refresh_token = RefreshToken(
            id=self._next_token_id,
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self._next_token_id += 1
        self._refresh_tokens[refresh_token.id] = refresh_token
        
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_plain,
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=self._user_to_response(user, tenant),
        )
    
    def refresh_tokens(self, request: RefreshRequest) -> RefreshResponse:
        """Rotate refresh token and issue new access token."""
        token_hash = hashlib.sha256(request.refresh_token.encode()).hexdigest()
        
        # Find the refresh token
        refresh_token = None
        for rt in self._refresh_tokens.values():
            if rt.token_hash == token_hash:
                refresh_token = rt
                break
        
        if not refresh_token or not refresh_token.is_valid():
            raise ValueError("Invalid or expired refresh token")
        
        user = self.get_user_by_id(refresh_token.user_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise ValueError("User not found or inactive")
        
        # Get tenant if client
        tenant = None
        if user.tenant_id:
            tenant = self.get_tenant_by_id(user.tenant_id)
            if not tenant or not tenant.is_active():
                raise ValueError("Tenant is suspended")
        
        # Revoke old refresh token
        refresh_token.revoked_at = datetime.now(timezone.utc)
        
        # Create new tokens
        access_token = create_access_token(user, tenant)
        new_refresh_plain, new_refresh_hash = create_refresh_token(user)
        
        new_refresh_token = RefreshToken(
            id=self._next_token_id,
            user_id=user.id,
            token_hash=new_refresh_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
            replaced_by_token_hash=new_refresh_hash,
        )
        self._next_token_id += 1
        self._refresh_tokens[new_refresh_token.id] = new_refresh_token
        
        return RefreshResponse(
            access_token=access_token,
            refresh_token=new_refresh_plain,
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
    
    def verify_access_token(self, token: str) -> Tuple[User, Optional[Tenant]]:
        """Verify access token and return user + tenant."""
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            raise ValueError("Token expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")
        
        if payload.get("type") != "access":
            raise ValueError("Invalid token type")
        
        user_id = int(payload["sub"])
        user = self.get_user_by_id(user_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise ValueError("User not found or inactive")
        
        tenant = None
        tenant_id = payload.get("tenant_id")
        if tenant_id:
            tenant = self.get_tenant_by_id(tenant_id)
            if not tenant or not tenant.is_active():
                raise ValueError("Tenant not found or suspended")

        # Client-portal logins resolve their business database instead of a
        # managed tenant, so the analytics/assistant layers read the right data.
        if tenant is None and user.is_client() and user.client_db_name:
            tenant = self._tenant_from_client_account(user)
        
        return user, tenant
    
    # -----------------------------------------------------------------------
    # MFA (TOTP)
    # -----------------------------------------------------------------------
    
    def setup_mfa(self, user_id: int) -> MFASetupResponse:
        """Generate new MFA secret for user."""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        
        if not user.is_developer():
            raise ValueError("MFA only required for developer accounts")
        
        secret = pyotp.random_base32()
        
        mfa = MFASecret(
            id=self._next_mfa_id,
            user_id=user_id,
            secret=secret,
        )
        self._next_mfa_id += 1
        self._mfa_secrets[user_id] = mfa
        
        # Generate QR code URI
        totp = pyotp.TOTP(secret)
        qr_uri = totp.provisioning_uri(
            name=user.email,
            issuer_name="Jarvis",
        )
        
        return MFASetupResponse(secret=secret, qr_code_uri=qr_uri)
    
    def verify_mfa(self, user_id: int, code: str) -> bool:
        """Verify TOTP code."""
        mfa = self._mfa_secrets.get(user_id)
        if not mfa:
            return False
        
        totp = pyotp.TOTP(mfa.secret)
        return totp.verify(code, valid_window=1)
    
    def get_mfa_qr_code(self, user_id: int) -> bytes:
        """Generate QR code image for MFA setup."""
        mfa = self._mfa_secrets.get(user_id)
        if not mfa:
            raise ValueError("MFA not set up")
        
        user = self.get_user_by_id(user_id)
        totp = pyotp.TOTP(mfa.secret)
        qr_uri = totp.provisioning_uri(name=user.email, issuer_name="Jarvis")
        
        qr = qrcode.make(qr_uri)
        buf = BytesIO()
        qr.save(buf, format="PNG")
        return buf.getvalue()
    
    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    
    def _tenant_from_client_account(self, user: User) -> Optional[Tenant]:
        """Adapt a client-portal account into the Tenant the data layers read."""
        from jarvis.auth import client_accounts

        account = client_accounts.get_client_account(user.client_db_name)
        if account is None or account.status != "active":
            return None
        return Tenant(
            id=account.id,
            name=account.db_name,
            display_name=account.display_name,
            db_name=account.db_name,
            db_user=account.db_user,
            db_password=account.db_password,
            status=account.status,
        )

    def _user_to_response(self, user: User, tenant: Optional[Tenant] = None) -> UserResponse:
        return UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id,
            client_display_name=user.client_display_name,
            status=user.status,
        )


# Global singleton
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get the global AuthService singleton."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service

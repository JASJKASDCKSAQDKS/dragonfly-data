"""
Persistent client portal accounts.

Every time the app provisions a database for a business (a bar, a shop, ...)
it mints the login that business owner uses to reach the client interface: a
username, an email address and a strong password. This module owns that
registry — creating accounts, rotating their passwords, and looking them up
during login and tenant resolution.

The registry lives beside the other Jarvis registers (config.CLIENT_ACCOUNTS_PATH)
and stores, per database:

    * username / email / password  — the human credentials
    * password_hash                — Argon2, what login actually verifies
    * db_user / db_password        — the read-only account the portal reads with

The plaintext password is kept so a developer can hand the login to the
client and re-display it later, exactly as tenant DB passwords already are.
The file is written with 0600 permissions.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from jarvis import config
from jarvis.auth import client_credentials as creds
from jarvis.auth.models import hash_password
from jarvis.auth import readonly_db_user as ro_user

log = logging.getLogger(__name__)

_FALLBACK_DOMAIN = "clients.seline.example"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ClientAccount:
    """A login the owner of one database uses to reach the client interface."""

    id: int
    db_name: str
    display_name: str
    username: str
    email: str
    password: str                      # plaintext — developer-visible only
    password_hash: str                 # Argon2 — what login verifies
    db_user: str = ""                  # read-only MariaDB account
    db_password: str = ""
    tenant_id: Optional[int] = None
    status: str = "active"             # active | suspended
    must_change_password: bool = True
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ClientAccount":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def public(self) -> dict:
        """Account view with no credential material (safe to log or embed)."""
        return {
            "id": self.id,
            "db_name": self.db_name,
            "display_name": self.display_name,
            "username": self.username,
            "email": self.email,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "must_change_password": self.must_change_password,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------

def _path() -> str:
    return config.CLIENT_ACCOUNTS_PATH


def _load() -> list[dict]:
    try:
        with open(_path()) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(entries: list[dict]) -> None:
    path = _path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _next_id(entries: list[dict]) -> int:
    return max((int(e.get("id", 0)) for e in entries), default=0) + 1


def _find(entries: list[dict], db_name: str) -> Optional[dict]:
    for entry in entries:
        if entry.get("db_name") == db_name:
            return entry
    return None


def migrate_legacy_email_domains() -> int:
    """Move generated .local addresses to the validator-safe example domain."""
    entries = _load()
    changed = 0
    for entry in entries:
        email = str(entry.get("email", ""))
        if email.lower().endswith("@clients.seline.local"):
            entry["email"] = email[: -len("@clients.seline.local")] + "@clients.seline.example"
            entry["updated_at"] = _now()
            changed += 1
    if changed:
        _save(entries)
    return changed


def _registry_creds(db_name: str) -> Optional[tuple[str, str]]:
    """Read-only-capable creds from the AI-created database registry."""
    try:
        with open(config.DB_REGISTRY_PATH) as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if entry.get("name") == db_name and entry.get("user") and entry.get("password"):
            return entry["user"], entry["password"]
    return None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def list_client_accounts() -> list[ClientAccount]:
    return [ClientAccount.from_dict(e) for e in _load()]


def get_client_account(db_name: str) -> Optional[ClientAccount]:
    entry = _find(_load(), db_name)
    return ClientAccount.from_dict(entry) if entry else None


def get_client_account_by_email(email: str) -> Optional[ClientAccount]:
    needle = (email or "").strip().lower()
    for entry in _load():
        if str(entry.get("email", "")).lower() == needle:
            return ClientAccount.from_dict(entry)
    return None


def get_client_account_by_username(username: str) -> Optional[ClientAccount]:
    needle = (username or "").strip().lower()
    for entry in _load():
        if str(entry.get("username", "")).lower() == needle:
            return ClientAccount.from_dict(entry)
    return None


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

def _resolve_db_creds(db_name: str) -> tuple[str, str]:
    """Credentials the portal should read ``db_name`` with.

    Prefers a dedicated SELECT-only account; falls back to the registered
    credentials when the admin account cannot create users.
    """
    db_password = creds.generate_db_password()
    if ro_user.ensure_readonly_user(db_name, db_password):
        return ro_user.readonly_username(db_name), db_password
    fallback = _registry_creds(db_name)
    if fallback:
        log.info("client portal will read %s with registered credentials", db_name)
        return fallback
    log.warning("no readable credentials available for %s", db_name)
    return "", ""


def provision_client_account(
    db_name: str,
    display_name: str = "",
    tenant_id: Optional[int] = None,
    db_user: Optional[str] = None,
    db_password: Optional[str] = None,
) -> ClientAccount:
    """Create (or refresh) the client login for a database.

    Idempotent: calling it again for an existing database keeps the current
    credentials and only refreshes the display name / tenant link, so
    repeated provisioning never silently invalidates a handed-out password.
    """
    entries = _load()
    existing = _find(entries, db_name)
    label = display_name or db_name

    if existing is not None:
        changed = False
        if existing.get("display_name") != label:
            existing["display_name"] = label
            changed = True
        if tenant_id is not None and existing.get("tenant_id") != tenant_id:
            existing["tenant_id"] = tenant_id
            changed = True
        if changed:
            existing["updated_at"] = _now()
            _save(entries)
        return ClientAccount.from_dict(existing)

    slug = creds.slugify(db_name)
    taken_users = {str(e.get("username", "")).lower() for e in entries}
    taken_emails = {str(e.get("email", "")).lower() for e in entries}
    username = creds.username_for(slug, taken_users)
    email = creds.email_for(slug, config.CLIENT_EMAIL_DOMAIN or _FALLBACK_DOMAIN, taken_emails)
    password = creds.generate_password()

    if db_user and db_password:
        resolved_user, resolved_password = db_user, db_password
    else:
        resolved_user, resolved_password = _resolve_db_creds(db_name)

    account = ClientAccount(
        id=_next_id(entries),
        db_name=db_name,
        display_name=label,
        username=username,
        email=email,
        password=password,
        password_hash=hash_password(password),
        db_user=resolved_user,
        db_password=resolved_password,
        tenant_id=tenant_id,
    )
    entries.append(account.to_dict())
    _save(entries)
    log.info("provisioned client account %s for database %s", email, db_name)
    return account


def regenerate_password(db_name: str) -> Optional[ClientAccount]:
    """Mint a fresh login password for an account. Returns None if unknown."""
    entries = _load()
    entry = _find(entries, db_name)
    if entry is None:
        return None
    password = creds.generate_password()
    entry["password"] = password
    entry["password_hash"] = hash_password(password)
    entry["must_change_password"] = True
    entry["updated_at"] = _now()
    _save(entries)
    log.info("rotated client password for database %s", db_name)
    return ClientAccount.from_dict(entry)


def set_status(db_name: str, status: str) -> Optional[ClientAccount]:
    """Suspend or reactivate a client login."""
    if status not in ("active", "suspended"):
        raise ValueError("status must be 'active' or 'suspended'")
    entries = _load()
    entry = _find(entries, db_name)
    if entry is None:
        return None
    entry["status"] = status
    entry["updated_at"] = _now()
    _save(entries)
    return ClientAccount.from_dict(entry)


def delete_client_account(db_name: str) -> bool:
    """Remove an account and drop its read-only database user."""
    entries = _load()
    entry = _find(entries, db_name)
    if entry is None:
        return False
    remaining = [e for e in entries if e.get("db_name") != db_name]
    _save(remaining)
    if str(entry.get("db_user", "")).startswith("client_"):
        ro_user.drop_readonly_user(db_name)
    return True

"""
Tenant models for Jarvis.

Defines the data models for tenants and their database users.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Tenant:
    """Tenant (business) account."""
    id: int
    name: str                    # slug: lowercase, alphanumeric, underscore
    display_name: str            # Human-readable name
    db_name: str                 # MariaDB database name
    db_user: str                 # Read-only database user
    db_password: str             # Read-only database user password
    status: str = "active"       # active, suspended
    timezone: str = "UTC"
    business_day_start_hour: int = 6  # 6am default for bars/shops
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_active(self) -> bool:
        return self.status == "active"


@dataclass
class TenantDBUser:
    """Per-tenant read-only database user."""
    tenant_id: int
    username: str
    password: str
    # Grants: SELECT on tenant's database only
    grants: list[str] = field(default_factory=lambda: ["SELECT"])


@dataclass
class TenantSettings:
    """Tenant-specific settings."""
    tenant_id: int
    # Analytics settings
    cache_ttl_seconds: int = 300
    # AI settings
    ai_model: str = "ollama"  # or "gemini"
    ai_temperature: float = 0.3
    # Business settings
    currency: str = "EUR"
    date_format: str = "DD/MM/YYYY"
    # Feature flags
    enable_voice: bool = True
    enable_ai_assistant: bool = True
    enable_3d_animation: bool = False
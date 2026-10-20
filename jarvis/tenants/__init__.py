"""
Tenant management module for Jarvis.

Provides:
- Tenant provisioning with per-tenant read-only database users
- Schema migrations (Alembic)
- Tenant database lifecycle management
"""

from jarvis.tenants.models import Tenant, TenantDBUser
from jarvis.tenants.service import TenantService
from jarvis.tenants.routes import router as tenants_router

__all__ = [
    "Tenant",
    "TenantDBUser",
    "TenantService",
    "tenants_router",
]
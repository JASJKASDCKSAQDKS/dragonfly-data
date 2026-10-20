"""
Client-portal account API (developer only).

Lets a developer see, rotate and suspend the logins the app mints for each
business database. Every endpoint requires the developer role — these payloads
contain plaintext passwords, so they are never exposed to clients.

Endpoints:
- GET    /api/clients                     - list every client login
- POST   /api/clients/{db}/regenerate     - mint a new password
- POST   /api/clients/{db}/suspend        - disable a login
- POST   /api/clients/{db}/reactivate     - re-enable a login
- DELETE /api/clients/{db}                - remove the login (and its DB user)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from jarvis.auth.client_accounts import (
    ClientAccount,
    delete_client_account,
    list_client_accounts,
    regenerate_password,
    set_status,
)
from jarvis.auth.dependencies import require_developer
from jarvis.auth.models import User
from jarvis.auth.service import get_auth_service
from jarvis.rails.audit import log_event

router = APIRouter(prefix="/api/clients", tags=["clients"])


def _payload(account: ClientAccount, include_generated_password: bool = False) -> dict:
    """Return a client account without persistent credential material by default."""
    payload = account.public()
    if include_generated_password:
        payload["password"] = account.password
    return payload


@router.get("")
async def list_clients(user: User = Depends(require_developer)):
    """List generated client logins without passwords or DB credentials."""
    accounts = list_client_accounts()
    return {
        "status": "success",
        "clients": [_payload(a) for a in sorted(accounts, key=lambda a: a.db_name)],
    }


@router.post("/{db_name}/regenerate")
async def regenerate_client_password(db_name: str, user: User = Depends(require_developer)):
    """Mint a fresh password for one client login."""
    account = regenerate_password(db_name)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No client login for that database.")
    get_auth_service().load_client_accounts()
    log_event("CLIENT_ACCOUNT", "PASSWORD_REGENERATED", {"db_name": db_name}, user_id=user.id)
    return {"status": "success", "client": _payload(account, include_generated_password=True)}


@router.post("/{db_name}/suspend")
async def suspend_client(db_name: str, user: User = Depends(require_developer)):
    """Disable a client login without deleting it."""
    account = set_status(db_name, "suspended")
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No client login for that database.")
    get_auth_service().load_client_accounts()
    log_event("CLIENT_ACCOUNT", "SUSPENDED", {"db_name": db_name}, user_id=user.id)
    return {"status": "success", "client": _payload(account)}


@router.post("/{db_name}/reactivate")
async def reactivate_client(db_name: str, user: User = Depends(require_developer)):
    """Re-enable a suspended client login."""
    account = set_status(db_name, "active")
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No client login for that database.")
    get_auth_service().load_client_accounts()
    log_event("CLIENT_ACCOUNT", "REACTIVATED", {"db_name": db_name}, user_id=user.id)
    return {"status": "success", "client": _payload(account)}


@router.delete("/{db_name}")
async def delete_client(db_name: str, user: User = Depends(require_developer)):
    """Remove a client login and its read-only database user."""
    if not delete_client_account(db_name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No client login for that database.")
    get_auth_service().load_client_accounts()
    log_event("CLIENT_ACCOUNT", "DELETED", {"db_name": db_name}, user_id=user.id)
    return {"status": "success", "deleted": db_name}

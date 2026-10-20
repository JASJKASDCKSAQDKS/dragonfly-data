"""
Pending confirmation store (Tier 6 Safety Rails).

Bridges the safety gate to the web dashboard: when a tool call needs
explicit user approval in web mode, the gate creates a pending request,
the dashboard polls for it, and the user's Approve/Deny click resolves
the awaiting coroutine. Unresolved requests expire (treated as deny)
after the configured timeout so a turn can never hang forever.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

# req_id -> record dict. All access happens on the server's event loop.
_pending: dict[int, dict[str, Any]] = {}
_counter = itertools.count(1)


def create_pending(
    action_name: str,
    args: dict[str, Any],
    reason: str,
    timeout: float,
) -> int:
    """Register a new pending confirmation and return its id."""
    req_id = next(_counter)
    now = time.time()
    _pending[req_id] = {
        "id": req_id,
        "action": action_name,
        "args": args,
        "reason": reason,
        "created_at": now,
        "expires_at": now + timeout,
        "event": asyncio.Event(),
        "approved": None,
    }
    return req_id


def _expire_stale() -> None:
    """Mark timed-out requests as denied so waiters never hang."""
    now = time.time()
    for req in list(_pending.values()):
        if req["approved"] is None and now >= req["expires_at"]:
            req["approved"] = False
            req["event"].set()


def list_pending() -> list[dict[str, Any]]:
    """Expire stale requests, then return actionable ones for the dashboard."""
    _expire_stale()
    now = time.time()
    return [
        {
            "id": req["id"],
            "action": req["action"],
            "args": req["args"],
            "reason": req["reason"],
            "expires_in": round(max(req["expires_at"] - now, 0.0), 1),
        }
        for req in _pending.values()
        if req["approved"] is None
    ]


def resolve(req_id: int, approved: bool) -> bool:
    """Resolve a pending request. Returns False if unknown or already resolved."""
    req = _pending.get(req_id)
    if req is None or req["approved"] is not None:
        return False
    req["approved"] = approved
    req["event"].set()
    return True


async def wait_for_resolution(req_id: int, timeout: float) -> bool:
    """Await the user's decision. Returns approved; False on timeout."""
    req = _pending.get(req_id)
    if req is None:
        return False
    try:
        await asyncio.wait_for(req["event"].wait(), timeout=timeout)
    except asyncio.TimeoutError:
        if req["approved"] is None:
            req["approved"] = False
    finally:
        _pending.pop(req_id, None)
    return bool(req["approved"])

"""
Jarvis Audit Logger (Tier 6 Safety Rails).

Maintains a persistent, human-readable audit log of every tool call,
confirmation request/decision, heartbeat surface, and setting change.
Stored in ~/.jarvis/audit.log by default.

Extended with tenant_id and user_id for multi-tenant audit trails.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from jarvis import config


def get_audit_log_path() -> str:
    """Return the absolute path to the audit log file."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, "audit.log")


def log_event(
    event_type: str,
    action: str,
    details: Optional[Dict[str, Any]] = None,
    reasoning: str = "",
    status: str = "SUCCESS",
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    """Record an entry in the audit log.

    Args:
        event_type: Category (e.g. TOOL_CALL, CONFIRMATION, HEARTBEAT, SETTING, KILL_SWITCH).
        action: Specific action description or tool name.
        details: Dictionary of parameters or context.
        reasoning: Explanation or safety note.
        status: Outcome status (e.g. SUCCESS, DENIED, FAILED).
        tenant_id: Optional tenant ID for multi-tenant audit trails.
        user_id: Optional user ID for audit trails.
    """
    timestamp = datetime.now().isoformat()
    entry = {
        "timestamp": timestamp,
        "event_type": event_type,
        "action": action,
        "details": details or {},
        "reasoning": reasoning,
        "status": status,
        "tenant_id": tenant_id,
        "user_id": user_id,
    }

    # Format human-readable string line
    details_str = f" | details={json.dumps(details)}" if details else ""
    reason_str = f" | reasoning='{reasoning}'" if reasoning else ""
    tenant_str = f" | tenant_id={tenant_id}" if tenant_id is not None else ""
    user_str = f" | user_id={user_id}" if user_id is not None else ""
    line = f"[{timestamp}] [{event_type}] {action} -> {status}{tenant_str}{user_str}{details_str}{reason_str}\n"

    try:
        path = get_audit_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception as exc:
        print(f"[Audit Log Warning] Could not write to audit log: {exc}", file=sys.stderr)


def get_recent_logs(limit: int = 15, tenant_id: Optional[int] = None) -> list[str]:
    """Retrieve the last N lines from the audit log, optionally filtered by tenant."""
    path = get_audit_log_path()
    if not os.path.exists(path):
        return ["(Audit log is empty)"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        if tenant_id is not None:
            # Filter lines containing the tenant_id
            filtered = [line for line in lines if f"tenant_id={tenant_id}" in line]
            return [line.strip() for line in filtered[-limit:]] if filtered else ["(No logs for this tenant)"]
        
        return [line.strip() for line in lines[-limit:]] if lines else ["(Audit log is empty)"]
    except Exception as exc:
        return [f"Error reading audit log: {exc}"]

"""
Safety rails package — single source of truth for gate behavior.

The confirmation rules live in ``jarvis.rails.gate``; this package
re-exports them so callers can simply ``from jarvis.rails import
requires_confirmation, request_confirmation``. Data guarding lives in
``jarvis.rails.guard``.
"""

from __future__ import annotations

from typing import Any

from jarvis.rails.audit import log_event, get_recent_logs  # noqa: F401
from jarvis.rails.gate import request_confirmation, requires_confirmation  # noqa: F401
from jarvis.rails.guard import wrap_external_data  # noqa: F401


def wrap_external_data_compat(data: Any, source: str) -> str:
    """Backward-compatible wrapper that coerces non-string data first."""
    return wrap_external_data(str(data), source=source)

"""
Kill Switch State Manager (Tier 5 Heartbeat).

Provides an instant pause/resume trigger for proactive background tasks
without interrupting the main interactive REPL session.
"""

from __future__ import annotations

from jarvis.rails.audit import log_event

_killswitch_active: bool = False


def is_killswitch_active() -> bool:
    """Return True if background heartbeat is currently killed/paused."""
    return _killswitch_active


def set_killswitch(active: bool) -> bool:
    """Set the killswitch state."""
    global _killswitch_active
    _killswitch_active = active
    status = "PAUSED (Killed)" if active else "ACTIVE (Resumed)"
    log_event(
        event_type="KILL_SWITCH",
        action="TOGGLE_KILL_SWITCH",
        details={"active": active},
        reasoning=f"Killswitch changed to {status}",
        status="SUCCESS",
    )
    return _killswitch_active


def toggle_killswitch() -> bool:
    """Toggle killswitch between active and paused."""
    return set_killswitch(not _killswitch_active)

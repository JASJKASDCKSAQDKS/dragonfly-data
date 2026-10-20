"""
Jarvis Heartbeat Package — Tier 5 Proactive Engine.
"""

from jarvis.heartbeat.killswitch import (
    is_killswitch_active,
    set_killswitch,
    toggle_killswitch,
)
from jarvis.heartbeat.manager import (
    add_reminder,
    get_due_reminders,
    heartbeat_loop,
)
from jarvis.heartbeat.quiet import (
    flush_missed_notices,
    get_missed_notices,
    get_quiet_hours,
    is_quiet_hours,
    queue_missed_notice,
    set_quiet_hours,
)

__all__ = [
    "is_killswitch_active",
    "set_killswitch",
    "toggle_killswitch",
    "add_reminder",
    "get_due_reminders",
    "heartbeat_loop",
    "is_quiet_hours",
    "set_quiet_hours",
    "get_quiet_hours",
    "queue_missed_notice",
    "get_missed_notices",
    "flush_missed_notices",
]

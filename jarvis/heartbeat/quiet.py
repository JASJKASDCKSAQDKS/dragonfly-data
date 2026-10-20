"""
Quiet Hours & Missed Notices (Tier 5 Heartbeat).

Ensures Jarvis is "quiet by default" — holding non-critical proactive
notifications during quiet hours (default: 22:00–07:00) and queueing
them as missed notices to be surfaced on the next user interaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

_quiet_start_hour: int = 22
_quiet_end_hour: int = 7
_missed_notices: List[str] = []


def set_quiet_hours(start: int, end: int) -> None:
    """Configure quiet hours range (0-23)."""
    global _quiet_start_hour, _quiet_end_hour
    _quiet_start_hour = start % 24
    _quiet_end_hour = end % 24


def get_quiet_hours() -> tuple[int, int]:
    """Return (start_hour, end_hour)."""
    return _quiet_start_hour, _quiet_end_hour


def is_quiet_hours() -> bool:
    """Return True if current local time is within quiet hours."""
    now_hour = datetime.now().hour
    if _quiet_start_hour > _quiet_end_hour:
        # Crosses midnight, e.g., 22:00 to 07:00
        return now_hour >= _quiet_start_hour or now_hour < _quiet_end_hour
    else:
        # Same day range, e.g., 01:00 to 06:00
        return _quiet_start_hour <= now_hour < _quiet_end_hour


def queue_missed_notice(notice: str) -> None:
    """Hold a notice to surface later."""
    _missed_notices.append(notice)


def get_missed_notices() -> List[str]:
    """Return pending missed notices."""
    return list(_missed_notices)


def flush_missed_notices() -> List[str]:
    """Return queued missed notices and clear the queue."""
    global _missed_notices
    notices = list(_missed_notices)
    _missed_notices.clear()
    return notices

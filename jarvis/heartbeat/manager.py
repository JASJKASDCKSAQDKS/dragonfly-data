"""
Heartbeat Task Manager (Tier 5 Heartbeat).

Provides background loop scheduling, reminder triggers, and SQLite persistence
for proactive notifications.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from jarvis import config
from jarvis.heartbeat.killswitch import is_killswitch_active
from jarvis.heartbeat.quiet import is_quiet_hours, queue_missed_notice
from jarvis.rails.audit import log_event


def get_db_path() -> str:
    """Return path to heartbeat SQLite database."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, "heartbeat.db")


def init_db() -> None:
    """Initialize heartbeat tables."""
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                trigger_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING'
            )
        """)
        conn.commit()


def add_reminder(text: str, delay_spec: str) -> str:
    """Add a scheduled reminder.

    Args:
        text: Reminder message text.
        delay_spec: E.g., "5m", "10s", "1h", "2d", or ISO time string.

    Returns:
        Confirmation message string.
    """
    init_db()

    now = datetime.now()
    trigger_dt = now

    spec = delay_spec.strip().lower()
    if spec.endswith("s"):
        trigger_dt += timedelta(seconds=int(spec[:-1]))
    elif spec.endswith("m"):
        trigger_dt += timedelta(minutes=int(spec[:-1]))
    elif spec.endswith("h"):
        trigger_dt += timedelta(hours=int(spec[:-1]))
    elif spec.endswith("d"):
        trigger_dt += timedelta(days=int(spec[:-1]))
    else:
        try:
            trigger_dt = datetime.fromisoformat(delay_spec)
        except ValueError:
            # Fallback default: 5 minutes if spec unparseable
            trigger_dt += timedelta(minutes=5)

    trigger_str = trigger_dt.isoformat()
    created_str = now.isoformat()

    path = get_db_path()
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (text, trigger_at, created_at, status) VALUES (?, ?, ?, 'PENDING')",
            (text, trigger_str, created_str),
        )
        conn.commit()
        rem_id = cursor.lastrowid

    log_event(
        event_type="HEARTBEAT",
        action="ADD_REMINDER",
        details={"id": rem_id, "text": text, "trigger_at": trigger_str},
        reasoning="Scheduled proactive reminder",
        status="SUCCESS",
    )

    fmt_time = trigger_dt.strftime("%H:%M:%S")
    return f"⏰ Reminder #{rem_id} scheduled for {fmt_time}: '{text}'"


def get_due_reminders() -> List[dict]:
    """Fetch all pending reminders that are due."""
    init_db()
    now_str = datetime.now().isoformat()
    path = get_db_path()
    due = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reminders WHERE status = 'PENDING' AND trigger_at <= ?",
            (now_str,),
        )
        for row in cursor.fetchall():
            due.append(dict(row))
    return due


def list_pending_reminders() -> List[dict]:
    """Fetch all still-pending reminders (regardless of due time)."""
    init_db()
    path = get_db_path()
    pending = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders WHERE status = 'PENDING' ORDER BY trigger_at")
        for row in cursor.fetchall():
            pending.append(dict(row))
    return pending


def mark_reminder_done(rem_id: int) -> None:
    """Mark a reminder as COMPLETED."""
    path = get_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE reminders SET status = 'COMPLETED' WHERE id = ?", (rem_id,))
        conn.commit()


async def heartbeat_loop(
    on_notice: Optional[Callable[[str], None]] = None,
    tick_interval_seconds: int = 10,
) -> None:
    """Background asyncio loop running periodic tasks."""
    init_db()

    while True:
        try:
            await asyncio.sleep(tick_interval_seconds)

            if is_killswitch_active():
                continue

            due_list = get_due_reminders()
            for rem in due_list:
                rem_id = rem["id"]
                text = rem["text"]
                notice_str = f"⏰ [Reminder] {text}"

                mark_reminder_done(rem_id)

                if is_quiet_hours():
                    queue_missed_notice(notice_str)
                    log_event(
                        event_type="HEARTBEAT",
                        action="SURFACE_NOTICE",
                        details={"id": rem_id, "text": text},
                        reasoning="Queued into missed notices due to quiet hours",
                        status="QUEUED",
                    )
                else:
                    if on_notice:
                        on_notice(notice_str)
                    log_event(
                        event_type="HEARTBEAT",
                        action="SURFACE_NOTICE",
                        details={"id": rem_id, "text": text},
                        reasoning="Surfaced proactive reminder to user",
                        status="DELIVERED",
                    )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log_event(
                event_type="HEARTBEAT",
                action="LOOP_ERROR",
                details={"error": str(exc)},
                status="ERROR",
            )

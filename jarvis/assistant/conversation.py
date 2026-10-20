"""
Assistant Conversation Manager for Jarvis.

Manages per-tenant conversation history and memory using SQLite.
Each tenant has their own conversation database file.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jarvis import config
from jarvis.tenants.models import Tenant

log = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""
    id: int
    role: str  # "user" or "assistant"
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_results: Optional[list[dict]] = None
    created_at: str = ""


class AssistantConversationManager:
    """Manages per-tenant conversation history."""
    
    def __init__(self, tenant: Tenant):
        self.tenant = tenant
        self._db_path = self._get_db_path(tenant.id)
        self._local = threading.local()
        self._init_db()
    
    def _get_db_path(self, tenant_id: int) -> str:
        """Get the database path for a tenant's conversations."""
        tenant_dir = Path(config.DATA_DIR) / "tenants" / str(tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return str(tenant_dir / "conversations.db")
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn
    
    def _init_db(self):
        """Initialize the conversation database."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_results TEXT,
                created_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_conversations_session 
            ON conversations(session_id, created_at);
            
            CREATE INDEX IF NOT EXISTS idx_conversations_created 
            ON conversations(created_at);
        """)
        conn.commit()
        log.debug(f"Initialized conversation database for tenant {self.tenant.name}")
    
    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list[dict]] = None,
        tool_results: Optional[list[dict]] = None,
    ) -> int:
        """Add a turn to the conversation."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        
        cursor = conn.execute(
            """INSERT INTO conversations (session_id, role, content, tool_calls, tool_results, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                json.dumps(tool_results) if tool_results else None,
                now,
            ),
        )
        conn.commit()
        turn_id = cursor.lastrowid
        return turn_id
    
    def get_conversation_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ConversationTurn]:
        """Get conversation history for a session."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT id, role, content, tool_calls, tool_results, created_at
               FROM conversations
               WHERE session_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        
        turns = []
        for row in reversed(rows):  # Reverse to get chronological order
            turns.append(ConversationTurn(
                id=row[0],
                role=row[1],
                content=row[2],
                tool_calls=json.loads(row[3]) if row[3] else None,
                tool_results=json.loads(row[4]) if row[4] else None,
                created_at=row[5],
            ))
        return turns
    
    def get_recent_sessions(self, limit: int = 10) -> list[str]:
        """Get recent session IDs."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT DISTINCT session_id FROM conversations
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [row[0] for row in rows]
    
    def delete_session(self, session_id: str) -> int:
        """Delete a conversation session."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM conversations WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        return cursor.rowcount
    
    def clear_all(self) -> int:
        """Clear all conversations for this tenant."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM conversations")
        conn.commit()
        return cursor.rowcount
    
    def close(self):
        """Close the database connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
    
    def __del__(self):
        self.close()


# Global cache of conversation managers per tenant
_conversation_managers: dict[int, AssistantConversationManager] = {}


def get_conversation_manager(tenant: Tenant) -> AssistantConversationManager:
    """Get or create a conversation manager for a tenant."""
    if tenant.id not in _conversation_managers:
        _conversation_managers[tenant.id] = AssistantConversationManager(tenant)
    return _conversation_managers[tenant.id]
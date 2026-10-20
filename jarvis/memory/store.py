"""
SQLite memory store — the persistence layer for Jarvis's long-term memory.

Uses Python's built-in ``sqlite3`` module with FTS5 for full-text search.
No external dependencies required.

Database location: ``~/.jarvis/memory.db`` (configurable via JARVIS_DATA_DIR).

Tables:
    - ``memories``: facts, preferences, notes — things Jarvis should "know"
    - ``memories_fts``: FTS5 index for fast keyword search
    - ``sessions``: conversation session logs (JSON-encoded turns)
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
from typing import Any

from jarvis import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Memory:
    """A single memory entry."""
    id: int
    content: str
    category: str
    source: str
    created_at: str
    updated_at: str
    active: bool
    consolidated: bool = False
    meta: str = ""  # JSON blob: importance, evidence_ids, etc.

    @staticmethod
    def from_row(row: tuple) -> Memory:
        return Memory(
            id=row[0],
            content=row[1],
            category=row[2],
            source=row[3],
            created_at=row[4],
            updated_at=row[5],
            active=bool(row[6]),
            consolidated=bool(row[7]) if len(row) > 7 else False,
            meta=row[8] if len(row) > 8 else "",
        )


@dataclass
class Session:
    """A conversation session record."""
    id: int
    started_at: str
    ended_at: str | None
    summary: str | None
    turns: list[dict]

    @staticmethod
    def from_row(row: tuple) -> Session:
        return Session(
            id=row[0],
            started_at=row[1],
            ended_at=row[2],
            summary=row[3],
            turns=json.loads(row[4]),
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class MemoryStore:
    """SQLite-backed memory store with FTS5 search."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or config.MEMORY_DB
        self._ensure_dir()
        self._local = threading.local()  # one connection per thread
        self._init_db()

    def _ensure_dir(self) -> None:
        """Create the data directory if it doesn't exist."""
        dir_path = Path(self._db_path).parent
        dir_path.mkdir(parents=True, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """Return this thread's database connection (lazy, thread-local).

        The store is a process-wide singleton shared by the event loop,
        FastAPI's threadpool, and background threads — a single shared
        connection would raise cross-thread errors. WAL mode lets each
        thread hold its own connection safely.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                content      TEXT NOT NULL,
                category     TEXT NOT NULL DEFAULT 'general',
                source       TEXT NOT NULL DEFAULT 'user',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                active       INTEGER NOT NULL DEFAULT 1,
                consolidated INTEGER NOT NULL DEFAULT 0,
                meta         TEXT NOT NULL DEFAULT ''
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                category,
                content=memories,
                content_rowid=id
            );

            -- Triggers to keep FTS5 index in sync
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, category)
                VALUES (new.id, new.content, new.category);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
                INSERT INTO memories_fts(rowid, content, category)
                VALUES (new.id, new.content, new.category);
            END;

            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT NOT NULL,
                ended_at    TEXT,
                summary     TEXT,
                turns       TEXT NOT NULL
            );
        """)
        self._migrate_schema(conn)
        conn.commit()
        log.debug("Memory database initialized at %s", self._db_path)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after the initial release (idempotent)."""
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "consolidated" not in existing:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN consolidated INTEGER NOT NULL DEFAULT 0"
            )
            log.info("Migrated memories table: added 'consolidated' column")
        if "meta" not in existing:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN meta TEXT NOT NULL DEFAULT ''"
            )
            log.info("Migrated memories table: added 'meta' column")

    # ------------------------------------------------------------------
    # Memories — CRUD
    # ------------------------------------------------------------------

    def add_memory(
        self,
        content: str,
        category: str = "general",
        source: str = "user",
        meta: str = "",
    ) -> Memory:
        """Add a new memory and return it."""
        now = _now_iso()
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO memories (content, category, source, created_at, updated_at, meta)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (content, category, source, now, now, meta),
        )
        conn.commit()
        row_id = cursor.lastrowid
        log.info("Added memory #%d: %s [%s]", row_id, content[:50], category)
        return Memory(
            id=row_id,
            content=content,
            category=category,
            source=source,
            created_at=now,
            updated_at=now,
            active=True,
            meta=meta,
        )

    def get_memory(self, memory_id: int) -> Memory | None:
        """Get a single memory by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ? AND active = 1", (memory_id,)
        ).fetchone()
        return Memory.from_row(row) if row else None

    def delete_memory(self, memory_id: int) -> bool:
        """Soft-delete a memory. Returns True if found and deleted."""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE memories SET active = 0, updated_at = ? WHERE id = ? AND active = 1",
            (_now_iso(), memory_id),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            log.info("Deleted memory #%d", memory_id)
        return deleted

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        """List all active memories, optionally filtered by category."""
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE active = 1 AND category = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE active = 1
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [Memory.from_row(r) for r in rows]

    def get_recent_memories(self, limit: int = 20) -> list[Memory]:
        """Get the most recently created active memories."""
        return self.list_memories(limit=limit)

    def get_unconsolidated_memories(self, limit: int = 50) -> list[Memory]:
        """Get active memories the reflection engine has not yet reviewed."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM memories
               WHERE active = 1 AND consolidated = 0 AND category != 'insight'
               ORDER BY created_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [Memory.from_row(r) for r in rows]

    def mark_memories_consolidated(self, memory_ids: list[int]) -> int:
        """Flag memories as reviewed by the reflection engine. Returns count updated."""
        if not memory_ids:
            return 0
        conn = self._get_conn()
        placeholders = ", ".join("?" for _ in memory_ids)
        cursor = conn.execute(
            f"""UPDATE memories SET consolidated = 1, updated_at = ?
                WHERE id IN ({placeholders})""",
            (_now_iso(), *memory_ids),
        )
        conn.commit()
        return cursor.rowcount

    def add_insight(
        self,
        content: str,
        category: str = "insight",
        importance: float = 0.8,
        evidence_ids: list[int] | None = None,
        source: str = "reflection",
    ) -> Memory:
        """Add a synthesized insight with importance/evidence stored in meta."""
        meta = json.dumps({
            "importance": importance,
            "evidence_ids": evidence_ids or [],
        })
        return self.add_memory(content, category=category, source=source, meta=meta)

    # ------------------------------------------------------------------
    # Memories — Search (FTS5)
    # ------------------------------------------------------------------

    def search_memories(self, query: str, limit: int = 10) -> list[Memory]:
        """Full-text search across memories using FTS5.

        The query is tokenized by FTS5 — supports AND, OR, NOT, phrases.
        Falls back to LIKE search if FTS5 fails.
        """
        conn = self._get_conn()

        try:
            rows = conn.execute(
                """SELECT m.* FROM memories m
                   JOIN memories_fts f ON m.id = f.rowid
                   WHERE memories_fts MATCH ? AND m.active = 1
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [Memory.from_row(r) for r in rows]
        except sqlite3.OperationalError:
            # FTS5 query syntax error — fall back to LIKE.
            log.debug("FTS5 query failed, falling back to LIKE: %r", query)
            rows = conn.execute(
                """SELECT * FROM memories
                   WHERE active = 1 AND content LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (f"%{query}%", limit),
            ).fetchall()
            return [Memory.from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Sessions — CRUD
    # ------------------------------------------------------------------

    def save_session(
        self,
        turns: list[dict],
        started_at: str | None = None,
        summary: str | None = None,
    ) -> int:
        """Save a conversation session and return its ID."""
        if not turns:
            return -1

        now = _now_iso()
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO sessions (started_at, ended_at, summary, turns)
               VALUES (?, ?, ?, ?)""",
            (started_at or now, now, summary, json.dumps(turns)),
        )
        conn.commit()
        session_id = cursor.lastrowid
        log.info("Saved session #%d (%d turns)", session_id, len(turns))
        return session_id

    def get_last_session(self) -> Session | None:
        """Get the most recent session."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return Session.from_row(row) if row else None

    def get_sessions(self, limit: int = 10) -> list[Session]:
        """Get recent sessions (most recent first)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Session.from_row(r) for r in rows]

    def get_recent_sessions(self, limit: int = 5) -> list[Session]:
        """Get the most recent sessions with non-empty content (oldest-last order)."""
        sessions = self.get_sessions(limit=limit)
        sessions.reverse()  # chronological order for prompt building
        return sessions

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close this thread's database connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def __del__(self) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: MemoryStore | None = None


def get_store() -> MemoryStore:
    """Return the global MemoryStore singleton (lazy-initialized)."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

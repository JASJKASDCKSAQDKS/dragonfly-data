"""
Bridge to the persistent ``ai_memory`` MariaDB database.

Every web chat turn is logged to the ``conversations`` table, and after a
restart the most recent transcript is replayed into the system prompt — so
the assistant remembers past conversations across sessions.

Credentials are read from ``~/bar-ai-system/.env`` at call time. If MariaDB
is unreachable (or the connector isn't installed), every function degrades
to a silent no-op: chat must never break because the memory DB is down.
"""

from __future__ import annotations

import logging

from jarvis import config

log = logging.getLogger(__name__)

_warned_unavailable = False


def _credentials() -> dict:
    """Connection settings for the ai_memory database, from the project .env."""
    return {
        "host": config.DB_HOST,
        "port": config.DB_PORT,
        "user": config.AI_DB_USER or "ai_app",
        "password": config.AI_DB_PASSWORD,
        "database": config.AI_DB_NAME or "ai_memory",
    }


def _connect():
    """Return a live connection, or None if the bridge is unavailable."""
    global _warned_unavailable
    try:
        import mysql.connector
    except ImportError:
        if not _warned_unavailable:
            log.warning("mysql-connector-python not installed — ai_memory bridge disabled")
            _warned_unavailable = True
        return None
    try:
        return mysql.connector.connect(connection_timeout=3, **_credentials())
    except Exception as exc:
        if not _warned_unavailable:
            log.warning("ai_memory MariaDB unreachable (%s) — bridge disabled this run", exc)
            _warned_unavailable = True
        return None


def log_message(role: str, content: str) -> None:
    """Append one chat turn to the persistent conversation log (no-op on failure)."""
    if role not in ("user", "assistant", "system") or not content:
        return
    conn = _connect()
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO conversations (role, content) VALUES (%s, %s)",
            (role, content),
        )
        conn.commit()
        cur.close()
    except Exception:
        log.exception("ai_memory log_message failed")
    finally:
        conn.close()


def save_fact(content: str, category: str = "fact", source: str = "auto") -> None:
    """Mirror a durable fact into the ai_memory `memories` table (no-op on failure)."""
    if not content:
        return
    conn = _connect()
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO memories (category, content, source, importance) "
            "VALUES (%s, %s, %s, %s)",
            (category, content, source, 4),
        )
        conn.commit()
        cur.close()
    except Exception:
        log.exception("ai_memory save_fact failed")
    finally:
        conn.close()


def recent_turns(limit: int = 10) -> list[dict]:
    """Return the last `limit` logged turns as [{'role': ..., 'content': ...}].

    Oldest first, ready to be preloaded into a Conversation as genuine
    dialogue history (works far better with small models than a
    system-prompt summary). Empty list if unavailable or no history.
    """
    conn = _connect()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM conversations ORDER BY conv_id DESC LIMIT %s",
            (limit,),
        )
        rows = list(reversed(cur.fetchall()))
        cur.close()
        return [{"role": role, "content": content} for role, content in rows]
    except Exception:
        log.exception("ai_memory recent_turns failed")
        return []
    finally:
        conn.close()


_STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "are", "was", "were", "the", "and", "your", "you", "yours", "mine",
    "tell", "about", "that", "this", "these", "those", "have", "has",
    "with", "from", "they", "them", "their", "will", "would", "could",
    "should", "did", "does", "please", "know", "remember", "rememeber",
    "said", "anything", "something", "still", "really", "much", "many",
    "mean",
}


def search_turns(query: str, limit: int = 5) -> list[dict]:
    """Find past logged turns mentioning the query's keywords.

    Used to recall older conversations on demand: keywords are the
    non-stopword words of the user's message (>= 4 chars, max 4). Oldest
    first. Empty list if unavailable or nothing matches.
    """
    words = [w.strip("?.,!;:()\"'").lower() for w in query.split()]
    keywords = [w for w in words if len(w) >= 4 and w not in _STOPWORDS][:4]
    if not keywords:
        return []
    conn = _connect()
    if conn is None:
        return []
    try:
        where = " OR ".join(["content LIKE %s"] * len(keywords))
        params = [f"%{kw}%" for kw in keywords]
        cur = conn.cursor()
        cur.execute(
            f"SELECT role, content FROM conversations WHERE {where} "
            "ORDER BY conv_id DESC LIMIT %s",
            (*params, limit),
        )
        rows = list(reversed(cur.fetchall()))
        cur.close()
        return [{"role": role, "content": content} for role, content in rows]
    except Exception:
        log.exception("ai_memory search_turns failed")
        return []
    finally:
        conn.close()


def recent_transcript(limit: int = 10) -> str:
    """Return the last `limit` logged turns formatted for the system prompt.

    Oldest first, one per line ("User: ..." / "Jarvis: ..."), each truncated
    to 300 chars. Empty string if the bridge is unavailable or no history.
    """
    conn = _connect()
    if conn is None:
        return ""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM conversations ORDER BY conv_id DESC LIMIT %s",
            (limit,),
        )
        rows = list(reversed(cur.fetchall()))
        cur.close()
    except Exception:
        log.exception("ai_memory recent_transcript failed")
        return ""
    finally:
        conn.close()

    lines = []
    for role, content in rows:
        speaker = "User" if role == "user" else "Jarvis"
        text = content if len(content) <= 300 else content[:297] + "..."
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def is_available() -> bool:
    """True when the ai_memory database is reachable right now."""
    conn = _connect()
    if conn is None:
        return False
    conn.close()
    return True

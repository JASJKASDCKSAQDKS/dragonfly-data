"""
Jarvis memory subsystem — Tier 4 (persistent context).

Provides long-term memory that survives restarts:
  - Facts, preferences, and notes (searchable via FTS5)
  - Conversation session logs (auto-saved, resumable)

All data lives in a single SQLite file at ~/.jarvis/memory.db.
"""

from jarvis.memory.manager import (  # noqa: F401
    recall,
    remember,
    forget,
    list_all,
    save_conversation,
    load_last_session,
)

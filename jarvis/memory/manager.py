"""
Memory manager — high-level operations used by the brain and REPL.

Wraps the low-level ``MemoryStore`` with formatted output and
context-building logic.  This is the public API that the rest of
the codebase interacts with.
"""

from __future__ import annotations

import logging

from jarvis import config
from jarvis.memory.store import get_store, Memory

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recall — build memory context for the system prompt
# ---------------------------------------------------------------------------

def recall(query: str | None = None) -> str:
    """Retrieve relevant memories formatted for inclusion in the system prompt.

    Args:
        query: Optional search query. If provided, does FTS search.
               If None, returns the most recent memories.

    Returns:
        A formatted string of memories, or empty string if none found.
        Truncated to MEMORY_MAX_CONTEXT characters.
    """
    store = get_store()

    if query:
        memories = store.search_memories(query, limit=15)
    else:
        memories = store.get_recent_memories(limit=30)

    if not memories:
        return ""

    lines = []
    for m in memories:
        tag = f"[{m.category}]" if m.category != "general" else ""
        lines.append(f"- {m.content} {tag}".strip())

    result = "\n".join(lines)

    # Truncate to stay within context budget.
    max_chars = config.MEMORY_MAX_CONTEXT
    if len(result) > max_chars:
        result = result[:max_chars] + "\n[... more memories available]"

    return result


# ---------------------------------------------------------------------------
# Remember — store a new fact
# ---------------------------------------------------------------------------

def remember(content: str, category: str = "general") -> str:
    """Store a new memory and return a confirmation message.

    Args:
        content: The fact, preference, or note to remember.
        category: Category tag (general, preference, fact, goal, note).

    Returns:
        Human-readable confirmation string.
    """
    content = content.strip()
    if not content:
        return "Nothing to remember — empty input."

    # Normalize category.
    valid_categories = {"general", "preference", "fact", "goal", "note"}
    category = category.lower().strip()
    if category not in valid_categories:
        category = "general"

    store = get_store()
    memory = store.add_memory(content, category=category, source="user")
    
    from jarvis.rails.audit import log_event
    log_event("MEMORY", "REMEMBER", details={"id": memory.id, "content": content, "category": category}, status="SUCCESS")

    return f"Remembered (#{memory.id}): \"{content}\" [{category}]"


# ---------------------------------------------------------------------------
# Forget — delete a memory
# ---------------------------------------------------------------------------

def forget(memory_id: int) -> str:
    """Delete a memory by ID and return a confirmation message.

    Args:
        memory_id: The ID of the memory to forget.

    Returns:
        Human-readable confirmation or error string.
    """
    store = get_store()
    memory = store.get_memory(memory_id)
    if not memory:
        return f"No active memory with ID #{memory_id}."

    store.delete_memory(memory_id)

    from jarvis.rails.audit import log_event
    log_event("MEMORY", "FORGET", details={"id": memory_id, "content": memory.content}, status="SUCCESS")

    return f"Forgotten (#{memory_id}): \"{memory.content}\""


# ---------------------------------------------------------------------------
# List — show all memories
# ---------------------------------------------------------------------------

def list_all(category: str | None = None) -> str:
    """Return a formatted list of all active memories.

    Args:
        category: Optional category filter.

    Returns:
        Formatted string listing all memories, or a "no memories" message.
    """
    store = get_store()
    memories = store.list_memories(category=category, limit=100)

    if not memories:
        if category:
            return f"No memories in category '{category}'."
        return "No memories stored yet. Use `/remember <text>` to save one."

    lines = []
    for m in memories:
        tag = f"[{m.category}]" if m.category != "general" else ""
        date = m.created_at[:10]  # Just the date portion
        lines.append(f"  #{m.id:3d}  {tag:14s} {m.content}  ({date})")

    header = f"Memories ({len(memories)} total)"
    if category:
        header += f" — category: {category}"

    return f"{header}\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

def save_conversation(turns: list[dict], started_at: str | None = None) -> None:
    """Save the current conversation session to the database.

    Args:
        turns: List of conversation turn dicts.
        started_at: Optional ISO timestamp for session start.
    """
    if not turns:
        return

    store = get_store()
    # Filter out empty turns.
    meaningful_turns = [t for t in turns if t.get("content") or t.get("tool_calls")]
    if meaningful_turns:
        store.save_session(meaningful_turns, started_at=started_at)
        log.info("Conversation saved (%d turns)", len(meaningful_turns))


def load_last_session() -> list[dict] | None:
    """Load the most recent conversation session.

    Returns:
        List of conversation turn dicts, or None if no sessions exist.
    """
    store = get_store()
    session = store.get_last_session()
    if session and session.turns:
        log.info("Loaded session #%d (%d turns)", session.id, len(session.turns))
        return session.turns
    return None


# ---------------------------------------------------------------------------
# Cross-session context — consumed by jarvis/prompts.py
# ---------------------------------------------------------------------------

def _summarize_session_turns(turns: list[dict], max_turns: int = 8) -> str:
    """Render a compact transcript snippet from stored session turns."""
    lines = []
    for turn in turns:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role == "tool" or not content:
            continue
        speaker = "User" if role == "user" else "Jarvis"
        if len(content) > 300:
            content = content[:297] + "..."
        lines.append(f"{speaker}: {content}")
    # Keep the last exchanges — the freshest part of the session.
    return "\n".join(lines[-max_turns:])


def get_cross_session_context(limit: int = 3) -> str:
    """Build a context block from recent stored conversation sessions.

    Args:
        limit: Number of recent sessions to include.

    Returns:
        Formatted string for the system prompt, or empty string if
        no sessions exist yet.
    """
    store = get_store()
    sessions = store.get_recent_sessions(limit=limit)
    if not sessions:
        return ""

    parts = ["=== Cross-Session Conversation Context (recent past chats) ==="]
    for session in sessions:
        snippet = _summarize_session_turns(session.turns)
        if not snippet:
            continue
        date = session.started_at[:10]
        parts.append(f"--- Session from {date} ---")
        parts.append(snippet)
        parts.append("")

    result = "\n".join(parts).strip()

    # Respect the same context budget as structured memories.
    max_chars = config.MEMORY_MAX_CONTEXT
    if len(result) > max_chars:
        result = result[:max_chars] + "\n[... older session context truncated]"
    return result


def get_all_memories(limit: int = 100) -> list[Memory]:
    """Return all active memories (most recent first)."""
    return get_store().list_memories(limit=limit)


def build_prompt(active_context: str = "", turn_count: int = 0) -> str:
    """Compose the full system prompt for one turn.

    Layers:
      1. The mandatory identity rules (config.SYSTEM_PROMPT).
      2. prompts.build_system_prompt() — guidelines, tool usage,
         long-term memories, and cross-session conversation context.

    Called per-turn by the web server so newly saved memories and
    recent session context are always current. Falls back to the
    identity block alone if the memory layer fails.
    """
    from jarvis.prompts import build_system_prompt

    parts = [config.SYSTEM_PROMPT.strip()]
    try:
        body = build_system_prompt(turn_count=turn_count, active_context=active_context)
        if body:
            parts.append(body)
    except Exception:
        log.exception("build_system_prompt failed — using identity block only")
    return "\n\n".join(parts)

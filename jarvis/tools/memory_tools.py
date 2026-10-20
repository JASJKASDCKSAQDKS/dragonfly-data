"""
Memory tools — let the assistant save, recall, and forget memories.

Tier 7A: These are assistant-facing tools (called by the model via
the tool loop) as opposed to the user-facing slash commands in main.py.
The assistant uses these to persist durable facts it learns during
conversation.
"""

from __future__ import annotations

from jarvis.tools.registry import tool


@tool(
    name="save_memory",
    description=(
        "Save a durable fact, user preference, correction, or project decision "
        "to long-term memory. Use this when the user teaches you something worth "
        "remembering across sessions. Do NOT save: transient task state, the current "
        "conversation itself, anything already in your core knowledge files, "
        "secrets, credentials, or other people's private data."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact or preference to remember. Be specific and include why it matters.",
            },
            "category": {
                "type": "string",
                "enum": ["fact", "preference", "goal", "note", "general"],
                "description": "Category of the memory. Use 'fact' for things about the user/business, 'preference' for how they want you to work, 'goal' for active projects/objectives, 'note' for general notes.",
            },
        },
        "required": ["content"],
    },
)
def save_memory(content: str, category: str = "general") -> str:
    """Save a memory with deduplication check."""
    from jarvis.memory.store import get_store

    content = content.strip()
    if not content:
        return "Nothing to save — empty content."

    # Normalize category
    valid_categories = {"general", "preference", "fact", "goal", "note"}
    category = category.lower().strip() if category else "general"
    if category not in valid_categories:
        category = "general"

    store = get_store()

    # Deduplication: check if a very similar memory already exists
    existing = store.search_memories(content, limit=5)
    for mem in existing:
        # Simple overlap check — if the existing memory's content is very
        # similar (shares most words), skip the save.
        existing_words = set(mem.content.lower().split())
        new_words = set(content.lower().split())
        if len(new_words) > 2:
            overlap = len(existing_words & new_words) / len(new_words)
            if overlap > 0.7:
                return (
                    f"A similar memory already exists (#{mem.id}): "
                    f'"{mem.content}" — skipped to avoid duplication.'
                )

    # Save the new memory
    memory = store.add_memory(content, category=category, source="assistant")

    try:
        from jarvis.rails.audit import log_event
        log_event(
            "MEMORY", "SAVE_MEMORY_TOOL",
            details={"id": memory.id, "content": content, "category": category},
            status="SUCCESS",
        )
    except Exception:
        pass

    return f'Remembered (#{memory.id}): "{content}" [{category}]'


@tool(
    name="recall_memory",
    description=(
        "Search your long-term memory for facts, preferences, or notes you've "
        "previously saved. Use this when you think you might have stored something "
        "relevant but it's not in your current context."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for — a keyword, topic, or question.",
            },
        },
        "required": ["query"],
    },
)
def recall_memory(query: str) -> str:
    """Search memories and return formatted results."""
    from jarvis.memory.store import get_store

    query = query.strip()
    if not query:
        return "No query provided."

    store = get_store()
    memories = store.search_memories(query, limit=10)

    if not memories:
        return f'No memories found matching "{query}".'

    lines = [f'Found {len(memories)} memory(ies) for "{query}":']
    for m in memories:
        tag = f" [{m.category}]" if m.category != "general" else ""
        date = m.created_at[:10]
        lines.append(f"  #{m.id}{tag}: {m.content}  ({date})")

    return "\n".join(lines)


@tool(
    name="forget_memory",
    description=(
        "Delete a specific memory by its ID. Use this when the user asks you to "
        "forget something, or when a previously stored fact is now wrong. "
        "This action requires confirmation through the safety gate."
    ),
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "The numeric ID of the memory to delete.",
            },
        },
        "required": ["memory_id"],
    },
)
def forget_memory(memory_id: int) -> str:
    """Soft-delete a memory by ID."""
    from jarvis.memory.store import get_store

    store = get_store()
    memory = store.get_memory(memory_id)
    if not memory:
        return f"No active memory with ID #{memory_id}."

    store.delete_memory(memory_id)

    try:
        from jarvis.rails.audit import log_event
        log_event(
            "MEMORY", "FORGET_MEMORY_TOOL",
            details={"id": memory_id, "content": memory.content},
            status="SUCCESS",
        )
    except Exception:
        pass

    return f'Forgotten (#{memory_id}): "{memory.content}"'

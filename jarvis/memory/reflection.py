"""
Reflection & Consolidation Engine (Tier 10).

Periodically reviews raw memories, identifies higher-level insights,
and promotes them to the synthesized mind layer.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from jarvis import config
from jarvis.memory.store import get_store, Memory
from jarvis.provider import call_with_tools

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reflection Prompt
# ---------------------------------------------------------------------------

REFLECTION_PROMPT = """You are Jarvis's reflection engine. Your job is to review a set of raw memories and synthesize higher-level insights.

## Input
You will receive a list of memories, each with an ID (e.g., #123), content, category, and creation date.

## Your Task
Identify 0-5 higher-level insights from these memories. Look for:
- **Recurring patterns** (themes that appear across multiple memories)
- **User preferences** (consistent likes/dislikes, working styles)
- **Contradictions** (conflicting facts or preferences)
- **Project directions** (goals, decisions, architectural choices)
- **Emerging goals** (implicit intentions not yet stated explicitly)

## Output Format
Return a JSON array of objects. Each object must have:
- `content`: string — the insight statement (concise, one sentence if possible)
- `category`: string — "insight" (always)
- `importance`: number — 0.1 to 1.0 (higher = more fundamental/core belief)
- `evidence_ids`: array of integers — the #IDs of memories this insight is based on
- `source`: string — "reflection" (always)

Example:
```json
[
  {
    "content": "User prefers functional programming patterns over OOP for data processing tasks.",
    "category": "insight",
    "importance": 0.85,
    "evidence_ids": [12, 15, 23],
    "source": "reflection"
  },
  {
    "content": "Project uses SQLite for local persistence; user explicitly chose this over PostgreSQL.",
    "category": "insight",
    "importance": 0.7,
    "evidence_ids": [5, 8],
    "source": "reflection"
  }
]
```

## Guidelines
- Be specific and actionable — avoid vague generalizations
- Only create insights supported by multiple memories (or one very significant memory)
- Assign importance honestly: 0.9-1.0 = core beliefs/identity, 0.7-0.8 = strong patterns, 0.5-0.6 = weak patterns, <0.5 = speculative
- Cite evidence_ids precisely — they must match the #IDs in the input
- Return empty array [] if no meaningful insights found
- Do NOT include commentary, markdown, or explanations — ONLY the JSON array
"""


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _format_memories_for_prompt(memories: list[Memory]) -> str:
    """Format memories into a readable list for the reflection prompt."""
    if not memories:
        return "No memories to reflect on."

    lines = []
    for m in memories:
        date = m.created_at[:10]  # Just the date
        tag = f"[{m.category}]" if m.category != "general" else ""
        lines.append(f"#{m.id} {tag} {m.content} ({date})")

    return "\n".join(lines)


def _parse_json_response(response_text: str) -> list[dict[str, Any]]:
    """Parse JSON from model response, handling common formatting issues."""
    text = response_text.strip()

    # Try direct JSON parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    code_block_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find JSON array in the text
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    log.warning("Failed to parse JSON from reflection response: %s", text[:200])
    return []


def _deduplicate_insights(new_insights: list[dict], existing_insights: list[Memory]) -> list[dict]:
    """Remove new insights that are too similar to existing ones (>70% overlap)."""
    if not existing_insights:
        return new_insights

    existing_contents = [m.content.lower() for m in existing_insights]
    filtered = []

    for insight in new_insights:
        new_content = insight.get("content", "").lower()
        is_duplicate = False

        for existing in existing_contents:
            # Simple word overlap check
            new_words = set(new_content.split())
            existing_words = set(existing.split())

            if not new_words:
                continue

            overlap = len(new_words & existing_words) / len(new_words)
            if overlap > 0.7:
                is_duplicate = True
                log.debug("Skipping duplicate insight (%.0f%% overlap): %s", overlap * 100, insight.get("content", "")[:50])
                break

        if not is_duplicate:
            filtered.append(insight)

    return filtered


# ---------------------------------------------------------------------------
# Main Reflection Function
# ---------------------------------------------------------------------------

async def reflect_and_consolidate() -> int:
    """Run one reflection cycle and return count of new insights created."""
    store = get_store()

    # Get unconsolidated memories
    unconsolidated = store.get_unconsolidated_memories(limit=50)

    if not unconsolidated:
        log.debug("No unconsolidated memories to reflect on")
        return 0

    log.info("Reflecting on %d unconsolidated memories", len(unconsolidated))

    # Format memories for the prompt
    memories_text = _format_memories_for_prompt(unconsolidated)

    # Build the conversation for the model
    messages = [
        {"role": "user", "content": REFLECTION_PROMPT},
        {"role": "user", "content": f"Memories to reflect on:\n\n{memories_text}"},
    ]

    # Call the model
    try:
        response = await call_with_tools(
            messages=messages,
            system_prompt="You are a reflection engine. Output only valid JSON.",
            tools=None,
        )

        if response.has_tool_calls:
            log.warning("Model returned tool calls instead of JSON during reflection")
            return 0

        # Parse the JSON response
        insights = _parse_json_response(response.text)

        if not insights:
            log.debug("No insights generated from reflection")
            return 0

        log.info("Generated %d raw insights from reflection", len(insights))

        # Get existing insights for deduplication
        existing_insights = store.list_memories(category="insight", limit=100)

        # Deduplicate
        unique_insights = _deduplicate_insights(insights, existing_insights)

        if not unique_insights:
            log.debug("All insights were duplicates of existing ones")
            # Still mark memories as consolidated even if no new insights
            source_ids = [m.id for m in unconsolidated]
            store.mark_memories_consolidated(source_ids)
            return 0

        # Add each insight to the store
        created_count = 0
        for insight in unique_insights:
            try:
                content = insight.get("content", "").strip()
                if not content:
                    continue

                importance = float(insight.get("importance", 0.8))
                importance = max(0.1, min(1.0, importance))  # Clamp to 0.1-1.0

                evidence_ids = insight.get("evidence_ids", [])
                if not isinstance(evidence_ids, list):
                    evidence_ids = []

                store.add_insight(
                    content=content,
                    category="insight",
                    importance=importance,
                    evidence_ids=evidence_ids,
                    source="reflection",
                )
                created_count += 1

            except Exception as e:
                log.warning("Failed to add insight: %s", e)
                continue

        # Mark source memories as consolidated
        source_ids = [m.id for m in unconsolidated]
        store.mark_memories_consolidated(source_ids)

        log.info("Reflection complete: created %d new insights", created_count)
        return created_count

    except Exception as e:
        log.error("Reflection failed: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Sync wrapper for heartbeat
# ---------------------------------------------------------------------------

def run_reflection_sync() -> int:
    """Synchronous wrapper for running reflection from a non-async context.

    Raises RuntimeError if called from inside a running event loop —
    schedule ``reflect_and_consolidate()`` as a task in that case instead.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to drive our own.
        return asyncio.run(reflect_and_consolidate())
    raise RuntimeError(
        "run_reflection_sync() cannot be called from a running event loop; "
        "await reflect_and_consolidate() directly instead."
    )
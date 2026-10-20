"""
Automatic memory extractor — Tier 7B.

When a session ends, this module reads the transcript and extracts
durable facts worth remembering. It uses a model call with a focused
extraction prompt, deduplicates against existing memories, and stores
the survivors.

Skips sessions that are too short (< 4 user messages) or look like
testing/idle chatter.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from jarvis import config
from jarvis.memory.store import get_store

log = logging.getLogger(__name__)

# Minimum user messages required before extraction runs.
MIN_USER_MESSAGES = 4

EXTRACTION_PROMPT = """You are a memory extraction system. Read the conversation transcript below and extract ONLY durable, useful facts worth remembering across future sessions.

Rules:
- Extract facts the user taught the assistant, corrections they made, preferences they stated, decisions on projects, and important personal/business information.
- DO NOT extract: greetings, small talk, transient task details (like "run this command"), testing/debugging chatter, or anything that only matters in this conversation.
- DO NOT extract secrets, credentials, API keys, passwords, or other people's private data.
- Each fact should be a single, clear sentence that would make sense on its own.
- Include WHY it matters or HOW to apply it when relevant.
- If the conversation is just testing, debugging, or idle chatter with no durable facts, return an empty list.

Return a JSON array of objects, each with:
- "content": the fact to remember (string)
- "category": one of "fact", "preference", "goal", "note" (string)

Return ONLY the JSON array, no other text. If nothing is worth saving, return [].

TRANSCRIPT:
{transcript}"""


def _format_transcript(turns: list[dict]) -> str:
    """Format conversation turns into a readable transcript."""
    lines = []
    for turn in turns:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        if role == "tool" or not content:
            continue
        speaker = "User" if role == "user" else "Assistant"
        # Truncate very long messages
        if len(content) > 500:
            content = content[:497] + "..."
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def _count_user_messages(turns: list[dict]) -> int:
    """Count the number of user messages in the transcript."""
    return sum(1 for t in turns if t.get("role") == "user" and t.get("content"))


async def extract_memories(turns: list[dict]) -> list[dict]:
    """Extract durable memories from a conversation transcript.

    Args:
        turns: List of conversation turn dicts.

    Returns:
        List of extracted memory dicts with 'content' and 'category' keys.
        Empty list if nothing worth saving, or on error.
    """
    # Skip short or empty conversations.
    user_count = _count_user_messages(turns)
    if user_count < MIN_USER_MESSAGES:
        log.debug("Skipping extraction: only %d user messages (need %d)", user_count, MIN_USER_MESSAGES)
        return []

    transcript = _format_transcript(turns)
    if not transcript.strip():
        return []

    # Build the extraction prompt
    prompt = EXTRACTION_PROMPT.format(transcript=transcript)

    # Use the configured provider for extraction
    try:
        if config.MODEL_PROVIDER == "gemini":
            return await _extract_gemini(prompt)
        else:
            return await _extract_ollama(prompt)
    except Exception as exc:
        log.warning("Memory extraction failed: %s", exc)
        return []


async def _extract_gemini(prompt: str) -> list[dict]:
    """Run extraction via Gemini."""
    from google import genai
    from google.genai import types

    if not config.GEMINI_API_KEY:
        log.debug("No Gemini API key — skipping extraction")
        return []

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = await client.aio.models.generate_content(
        model=config.MODEL_NAME or "gemini-3.6-flash",
        contents=[types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=1024,
        ),
    )
    return _parse_extraction_response(response.text or "")


async def _extract_ollama(prompt: str) -> list[dict]:
    """Run extraction via Ollama."""
    import httpx

    model = config.OLLAMA_MODEL or "qwen2.5:0.5b"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.OLLAMA_HOST}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=60.0,
        )
        if resp.status_code != 200:
            log.warning("Ollama extraction returned %d", resp.status_code)
            return []
        result = resp.json()
        text = result.get("message", {}).get("content", "")
        return _parse_extraction_response(text)


def _parse_extraction_response(text: str) -> list[dict]:
    """Parse the model's JSON response into a list of memory dicts."""
    text = text.strip()

    # Try to find JSON array in the response
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        log.debug("No JSON array found in extraction response")
        return []

    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        log.debug("JSON parse error in extraction response: %s", exc)
        return []

    if not isinstance(data, list):
        return []

    # Validate each entry
    valid = []
    for item in data:
        if isinstance(item, dict) and "content" in item:
            content = str(item["content"]).strip()
            category = str(item.get("category", "general")).strip().lower()
            if content and category in {"fact", "preference", "goal", "note", "general"}:
                valid.append({"content": content, "category": category})

    return valid


async def extract_and_store(turns: list[dict]) -> int:
    """Extract memories from a transcript and store them, with deduplication.

    Args:
        turns: List of conversation turn dicts.

    Returns:
        Number of new memories stored.
    """
    extracted = await extract_memories(turns)
    if not extracted:
        return 0

    store = get_store()
    stored_count = 0

    for item in extracted:
        content = item["content"]
        category = item["category"]

        # Deduplication: check if a similar memory already exists
        existing = store.search_memories(content, limit=5)
        is_duplicate = False
        for mem in existing:
            existing_words = set(mem.content.lower().split())
            new_words = set(content.lower().split())
            if len(new_words) > 2:
                overlap = len(existing_words & new_words) / len(new_words)
                if overlap > 0.7:
                    log.debug("Skipping duplicate memory: %s", content[:50])
                    is_duplicate = True
                    break

        if not is_duplicate:
            store.add_memory(content, category=category, source="extractor")
            stored_count += 1
            log.info("Extractor saved: %s [%s]", content[:60], category)

    if stored_count:
        try:
            from jarvis.rails.audit import log_event
            log_event(
                "MEMORY", "AUTO_EXTRACT",
                details={"extracted": len(extracted), "stored": stored_count},
                status="SUCCESS",
            )
        except Exception:
            pass

    log.info("Extraction complete: %d extracted, %d stored (after dedup)", len(extracted), stored_count)
    return stored_count

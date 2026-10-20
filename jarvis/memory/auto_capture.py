"""
Auto-capture — deterministic fact extraction from user messages.

Small local models can't be relied on to call the save-memory tool on their
own, and they often fail to ground on long pasted conversation logs. This
module closes the gap: every user message is scanned for explicit
self-statements ("my name is …", "my favorite … is …", …) and matching
facts are saved as structured memories — which the system prompt injects
on every future turn, so the model can't miss them.

Facts are written to the SQLite memory store (what the prompt builder
reads) and mirrored to the ai_memory MariaDB database (durable backup).
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# (pattern, fact template). {1}/{2} refer to capture groups, cleaned up.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bmy name is\s+([\w][\w .'-]{1,38}?)(?:\s*[,.!;]|$|\s+and\b)", re.I),
     "User's name is {1}"),
    (re.compile(r"\bmy dream is\s+(?:to\s+)?(.{3,80}?)(?:\s*[,.!;]|$)", re.I),
     "User's dream: {1}"),
    (re.compile(r"\bmy favou?rite\s+([\w ]{2,30}?)\s+is\s+([\w][\w .'-]{0,38}?)(?:\s*[,.!;]|$|\s+and\b)", re.I),
     "User's favorite {1} is {2}"),
    (re.compile(r"\bmy lucky number is\s+(\d{1,10})", re.I),
     "User's lucky number is {1}"),
    (re.compile(r"\bmy (\w{2,20}) is (?:called|named)\s+([\w][\w .'-]{0,28}?)(?:\s*[,.!;]|$)", re.I),
     "User's {1} is named {2}"),
    (re.compile(r"\bi live in\s+([\w][\w .'-]{1,38}?)(?:\s*[,.!;]|$)", re.I),
     "User lives in {1}"),
    (re.compile(r"\bi work as\s+(?:a\s+|an\s+)?([\w][\w .'-]{1,38}?)(?:\s*[,.!;]|$)", re.I),
     "User works as {1}"),
    (re.compile(r"\bi am\s+(?:a\s+|an\s+)?(\d{1,3})\s+years?\s+old\b", re.I),
     "User is {1} years old"),
    (re.compile(r"\bremember that\s+(.{3,120}?)(?:\s*$)", re.I),
     "{1}"),
]

# Words that indicate the match ran into the rest of the sentence — trim there.
_TRAILERS = re.compile(r"\s+(?:and|but|so|because|which|who|that)\s+.*$", re.I)


def _clean(fragment: str) -> str:
    fragment = _TRAILERS.sub("", fragment)
    return fragment.strip().strip(".,!;").strip()


def _already_known(store, fact: str) -> bool:
    try:
        hits = store.search_memories(fact, limit=5)
        low = fact.lower()
        return any(low in m.content.lower() or m.content.lower() in low for m in hits)
    except Exception:
        return False


def extract_facts(text: str) -> list[str]:
    """Pull durable-fact statements out of a user message (no DB writes)."""
    facts = []
    for pattern, template in _PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            fact = template
            for i, group in enumerate(m.groups(), start=1):
                fact = fact.replace(f"{{{i}}}", _clean(group or ""))
            if "{1" not in fact and "{2" not in fact and len(fact) >= 5:
                facts.append(fact)
        except Exception:
            continue
    return facts


def capture_user_facts(text: str, source: str = "auto") -> list[str]:
    """Save any durable facts found in a user message.

    Returns the list of newly saved facts (empty if none/new/already known).
    Never raises — memory capture must not break chat.
    """
    try:
        facts = extract_facts(text)
        if not facts:
            return []

        from jarvis.memory import manager as memory_manager
        from jarvis.memory.store import get_store
        from jarvis.memory import ai_memory

        store = get_store()
        saved = []
        for fact in facts:
            if _already_known(store, fact):
                continue
            memory_manager.remember(fact, category="fact")
            ai_memory.save_fact(fact, category="fact", source=source)
            saved.append(fact)
        if saved:
            log.info("Auto-captured facts: %s", saved)
        return saved
    except Exception:
        log.exception("capture_user_facts failed")
        return []

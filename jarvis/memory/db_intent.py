"""
Detect "create a new database for X" requests in chat messages.

Small local models can't be trusted to call the create_database tool from
casual phrasing, so the web server checks for this intent deterministically
(like auto_capture does for facts) and executes it directly. Anything
ambiguous returns None and falls through to normal chat.
"""

from __future__ import annotations

import re

# "want a new database for X", "create database for X", "make me a db called X"
_CREATE_DB_RE = re.compile(
    r"(?:want|need|create|make|add|set\s*up|get|open|start|build)\s+"
    r"(?:me\s+)?(?:a\s+)?(?:new\s+|brand[\s-]*new\s+)?(?:database|data\s*base|db)\b"
    r"(?:\s+(?:for|called|named)\s+(.+))?",
    re.IGNORECASE,
)

_NAME_MARKER_RE = re.compile(
    r"\b(?:called|cald|named)\s+([a-z][a-z0-9_]*)\b",
    re.IGNORECASE,
)

# Questions and hypotheticals are not creation requests.
_QUESTION_RE = re.compile(
    r"^\s*(?:what|whats|what's|who|whom|whose|why|how|when|where|which|"
    r"is|are|do|does|did|can|could|should|would|will|may|might|shall)\b",
    re.IGNORECASE,
)


def detect_new_database_request(text: str) -> str | None:
    """Return the raw bar/database name if this is a creation request, else None."""
    t = (text or "").strip()
    if not t or _QUESTION_RE.match(t):
        return None
    m = _CREATE_DB_RE.search(t)
    if not m:
        return None
    raw = (m.group(1) or "").strip().strip(" .,!?'\"")
    marked_name = _NAME_MARKER_RE.search(raw)
    if marked_name:
        raw = marked_name.group(1)
    else:
        # "create a database for a bar" should use the last meaningful
        # word as the database name, not the business-type phrase.
        raw = re.sub(
            r"^(?:a|an)\s+(?:bar|market|shop|store|restaurant|business)\s+",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()
    # "create a database" with no name → caller uses a default label.
    return raw or "new_bar"

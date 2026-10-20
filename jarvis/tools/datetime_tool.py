"""
Tool: current_datetime — returns the current date, time, and timezone.

A simple grounding tool so the model always has accurate time awareness,
even if the system prompt's timestamp has gone stale mid-session.
"""

from datetime import datetime, timezone

from jarvis.tools.registry import tool


@tool(
    name="current_datetime",
    description=(
        "Return the current local date and time with timezone. "
        "Use this when the user asks what time or date it is, or when "
        "you need an accurate timestamp."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def current_datetime() -> str:
    """Return a human-readable current datetime string."""
    now = datetime.now().astimezone()
    utc_now = datetime.now(timezone.utc)
    return (
        f"Local: {now.strftime('%A, %B %d, %Y at %I:%M:%S %p %Z')}\n"
        f"UTC:   {utc_now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )

"""
Tools: write_file, edit_file — safe filesystem write/edit access.

These tools let Jarvis modify files on disk. They require user confirmation
via the safety gate before making changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from jarvis import config
from jarvis.tools.registry import tool


def _truncate(text: str, max_chars: int | None = None) -> str:
    """Truncate text to *max_chars* and append a notice if clipped."""
    limit = max_chars or config.TOOL_MAX_OUTPUT
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated at {limit} characters]"


def _resolve_path(path: str) -> Path:
    """Resolve a path, expanding ~ and making it absolute."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = target.resolve()
    return target


@tool(
    name="write_file",
    description=(
        "Write content to a file, creating it or overwriting it if it exists. "
        "Specify the absolute or relative path and the content to write. "
        "Parent directories will be created automatically if they don't exist. "
        "Requires user confirmation before making changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
        },
        "required": ["path", "content"],
    },
)
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed."""
    target = _resolve_path(path)

    # Check if file exists
    existed = target.exists()
    action = "Overwrote" if existed else "Created"

    try:
        # Create parent directories if they don't exist
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        target.write_text(content, encoding="utf-8")

        size = target.stat().st_size
        return f"{action} file: {target.resolve()} ({size} bytes written)"
    except PermissionError:
        return f"[Error] Permission denied: {path}"
    except OSError as e:
        return f"[Error] Failed to write file: {e}"


@tool(
    name="edit_file",
    description=(
        "Edit a file by finding and replacing a specific string. "
        "Useful for making targeted changes to existing files. "
        "The old_string must match exactly (including whitespace and indentation). "
        "Requires user confirmation before making changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace.",
            },
            "new_string": {
                "type": "string",
                "description": "The string to replace it with.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
)
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Edit a file by replacing old_string with new_string."""
    target = _resolve_path(path)

    if not target.exists():
        return f"[Error] File not found: {path}"
    if not target.is_file():
        return f"[Error] Not a file: {path}"

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return f"[Error] Permission denied reading: {path}"
    except OSError as e:
        return f"[Error] Failed to read file: {e}"

    if old_string not in content:
        return f"[Error] String not found in file. The old_string must match exactly including whitespace and indentation."

    # Count occurrences to warn if multiple matches
    count = content.count(old_string)
    if count > 1:
        return f"[Error] String found {count} times in file. Please provide more context to make the match unique."

    # Perform the replacement
    new_content = content.replace(old_string, new_string)

    try:
        target.write_text(new_content, encoding="utf-8")
        size = target.stat().st_size
        return f"Edited file: {target.resolve()} ({size} bytes). Replaced 1 occurrence."
    except PermissionError:
        return f"[Error] Permission denied writing: {path}"
    except OSError as e:
        return f"[Error] Failed to write file: {e}"
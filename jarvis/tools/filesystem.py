"""
Tools: read_file, list_directory — safe, read-only filesystem access.

These tools let Jarvis inspect files and directory structures without
modifying anything.  Output is truncated to stay within context limits.
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


@tool(
    name="read_file",
    description=(
        "Read the contents of a file on disk and return it as text. "
        "Useful for reviewing code, config files, documentation, etc. "
        "Specify the absolute or relative path. Output is truncated for "
        "very large files."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read.",
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum number of lines to return (default 200).",
            },
        },
        "required": ["path"],
    },
)
def read_file(path: str, max_lines: int = 200) -> str:
    """Read a file and return its contents, truncated by lines and chars."""
    target = Path(path).expanduser()
    if not target.exists():
        return f"[Error] File not found: {path}"
    if not target.is_file():
        return f"[Error] Not a file: {path}"
    try:
        text = target.read_text(errors="replace")
    except PermissionError:
        return f"[Error] Permission denied: {path}"

    lines = text.splitlines(keepends=True)
    if len(lines) > max_lines:
        text = "".join(lines[:max_lines])
        text += f"\n[... showing first {max_lines} of {len(lines)} lines]"

    return _truncate(text)


@tool(
    name="list_directory",
    description=(
        "List the files and subdirectories in a directory. "
        "Returns names, types (file/dir), and sizes. "
        "Useful for exploring project structure."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the directory to list.",
            },
        },
        "required": ["path"],
    },
)
def list_directory(path: str = ".") -> str:
    """List directory contents with type and size information."""
    target = Path(path).expanduser()
    if not target.exists():
        return f"[Error] Directory not found: {path}"
    if not target.is_dir():
        return f"[Error] Not a directory: {path}"

    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return f"[Error] Permission denied: {path}"

    lines: list[str] = [f"Contents of {target.resolve()}:\n"]

    for entry in entries:
        if entry.is_dir():
            # Count immediate children for dirs.
            try:
                child_count = len(list(entry.iterdir()))
            except PermissionError:
                child_count = -1
            suffix = f"  ({child_count} items)" if child_count >= 0 else "  (no access)"
            lines.append(f"  📁 {entry.name}/{suffix}")
        else:
            size = _format_size(entry.stat().st_size)
            lines.append(f"  📄 {entry.name}  ({size})")

    if len(entries) == 0:
        lines.append("  (empty directory)")

    return _truncate("\n".join(lines))


def _format_size(size_bytes: int) -> str:
    """Return a human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}" if unit == "B" else f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

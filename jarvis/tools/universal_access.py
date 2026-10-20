"""
Tools: find_files, open_path_by_name, list_my_capabilities — universal file access.

These tools provide flexible file discovery and access across the project.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Optional

from jarvis import config
from jarvis.tools.registry import registry, tool


def _truncate(text: str, max_chars: Optional[int] = None) -> str:
    """Truncate text to *max_chars* and append a notice if clipped."""
    limit = max_chars or config.TOOL_MAX_OUTPUT
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated at {limit} characters]"


def _resolve_root(root: Optional[str]) -> Path:
    """Resolve the search root directory."""
    if root:
        target = Path(root).expanduser()
        if not target.is_absolute():
            target = target.resolve()
    else:
        target = config.PROJECT_ROOT
    return target


@tool(
    name="find_files",
    description=(
        "Find files matching a glob pattern within the project. "
        "Uses standard glob syntax (*, **, ?, [...]). "
        "Returns relative paths from the search root, one per line. "
        "Searches from PROJECT_ROOT by default, or a custom root if provided."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g., '**/*.py', 'tools/*.py', '**/test_*.py').",
            },
            "root": {
                "type": "string",
                "description": "Optional custom root directory to search from (default: project root).",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 100).",
            },
        },
        "required": ["pattern"],
    },
)
def find_files(pattern: str, root: Optional[str] = None, max_results: int = 100) -> str:
    """Find files matching a glob pattern."""
    search_root = _resolve_root(root)

    if not search_root.exists():
        return f"[Error] Search root not found: {search_root}"
    if not search_root.is_dir():
        return f"[Error] Search root is not a directory: {search_root}"

    try:
        # Use rglob for recursive patterns, glob for non-recursive
        if "**" in pattern:
            matches = list(search_root.rglob(pattern.replace("**/", "")))
        else:
            matches = list(search_root.glob(pattern))

        # Filter to files only and sort
        files = sorted(
            (m for m in matches if m.is_file()),
            key=lambda p: str(p.relative_to(search_root)).lower()
        )

        if not files:
            return f"No files found matching '{pattern}' in {search_root}"

        # Limit results
        limited = files[:max_results]
        lines = [str(f.relative_to(search_root)) for f in limited]

        result = "\n".join(lines)
        if len(files) > max_results:
            result += f"\n\n[... {len(files) - max_results} more files, showing first {max_results}]"

        return _truncate(result)

    except Exception as e:
        return f"[Error] Search failed: {e}"


@tool(
    name="open_path_by_name",
    description=(
        "Fuzzy-find and read a file by partial name or path. "
        "Searches recursively from PROJECT_ROOT for files whose name or path "
        "contains the given string (case-insensitive substring match). "
        "Returns the first match's contents. If multiple matches exist, "
        "lists them and asks to be more specific."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Partial file name or path to search for (e.g., 'config', 'tools/editor', 'test').",
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum lines to return (default 200).",
            },
        },
        "required": ["name"],
    },
)
def open_path_by_name(name: str, max_lines: int = 200) -> str:
    """Fuzzy find and read a file by partial name/path."""
    search_root = config.PROJECT_ROOT
    name_lower = name.lower()

    try:
        # Find all files containing the name in their path
        all_files = list(search_root.rglob("*"))
        matches = [
            f for f in all_files
            if f.is_file() and name_lower in str(f.relative_to(search_root)).lower()
        ]

        if not matches:
            return f"[Error] No file found matching '{name}' in {search_root}"

        # If exactly one match, read and return it
        if len(matches) == 1:
            target = matches[0]
            try:
                text = target.read_text(errors="replace")
            except PermissionError:
                return f"[Error] Permission denied: {target}"

            lines = text.splitlines(keepends=True)
            if len(lines) > max_lines:
                text = "".join(lines[:max_lines])
                text += f"\n[... showing first {max_lines} of {len(lines)} lines]"

            rel_path = target.relative_to(search_root)
            return _truncate(f"=== {rel_path} ===\n{text}")

        # Multiple matches - list them
        lines = [f"Multiple files match '{name}' (showing first 20):"]
        for m in matches[:20]:
            rel = m.relative_to(search_root)
            lines.append(f"  {rel}")
        if len(matches) > 20:
            lines.append(f"  ... and {len(matches) - 20} more")
        lines.append("\nPlease be more specific.")

        return _truncate("\n".join(lines))

    except Exception as e:
        return f"[Error] Search failed: {e}"


@tool(
    name="list_my_capabilities",
    description=(
        "List all available tools and their descriptions. "
        "Returns a dictionary mapping tool names to their descriptions."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def list_my_capabilities() -> dict:
    """List all registered tools with their descriptions."""
    return {name: defn.description for name, defn in registry._tools.items()}
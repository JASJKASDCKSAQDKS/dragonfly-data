"""
Tool: run_shell_command — execute a shell command and return output.

Safety measures:
  - Denylist blocks destructive commands (rm, sudo, mkfs, etc.).
  - Configurable timeout (default 30 s).
  - Output truncation to stay within context limits.
  - stderr is captured alongside stdout.
"""

from __future__ import annotations

import asyncio

from jarvis import config
from jarvis.tools.registry import tool


def _command_segments(command: str) -> list[str]:
    """Split a command into segments on ; && || | so compound commands
    can't hide a destructive piece after the first word."""
    import re

    segments = re.split(r"&&|\|\||[;|]", command)
    return [seg.strip() for seg in segments if seg.strip()]


def _is_blocked(command: str) -> str | None:
    """Return a reason string if the command is blocked, else None.

    Every segment of a compound command is scanned, and path/env prefixes
    are stripped (./rm, /bin/rm, FOO=1 rm all still match)."""
    for segment in _command_segments(command):
        words = [w.strip("\"'").rsplit("/", 1)[-1] for w in segment.split()]
        for prefix in config.SHELL_DENYLIST:
            if " " in prefix:
                # Multi-token pattern (e.g. "> /dev") — match against the raw segment.
                if prefix in segment:
                    return f"Command blocked: '{prefix}' is on the denylist."
                continue
            if any(word == prefix for word in words):
                return f"Command blocked: '{prefix}' is on the denylist."

    return None


def _truncate(text: str) -> str:
    limit = config.TOOL_MAX_OUTPUT
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... truncated at {limit} characters]"


@tool(
    name="run_shell_command",
    description=(
        "Execute a shell command on the local machine and return its output "
        "(stdout + stderr combined). Useful for running scripts, checking "
        "versions, searching files with grep, git operations, etc. "
        "Destructive commands (rm, sudo, etc.) are blocked for safety."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for the command (default 30).",
            },
        },
        "required": ["command"],
    },
)
async def run_shell_command(command: str, timeout: int | None = None) -> str:
    """Run a shell command and return combined stdout+stderr."""
    # Safety check.
    blocked = _is_blocked(command)
    if blocked:
        return f"[Blocked] {blocked}"

    timeout = timeout or config.TOOL_TIMEOUT

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace").strip()

        if not output:
            output = "(no output)"

        header = f"$ {command}\n[exit code: {proc.returncode}]\n\n"
        return _truncate(header + output)

    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return f"[Error] Command timed out after {timeout}s: {command}"
    except Exception as exc:
        return f"[Error] Failed to run command: {exc}"

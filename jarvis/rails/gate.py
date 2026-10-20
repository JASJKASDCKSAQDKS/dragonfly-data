"""
Confirmation Gate (Tier 6 Safety Rails).

Implements the "Never-Without-Asking" safety posture.
Jarvis MUST stop and request explicit user confirmation before:
1. Sending a message (email, chat, SMS, outbound comms).
2. Spending money (purchases, paid API calls).
3. Deleting data (file deletion, database records, memory entries).
4. Changing a setting — including modifying files or Jarvis's own config.

Confirmations are per-action and do not generalize.

Interactive (console) mode prompts on stdin. In web-server mode a
pending confirmation is registered (jarvis.rails.pending) and the
dashboard's safety modal resolves it via POST /api/confirmation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

from jarvis import config
from jarvis.rails.audit import log_event


# Categories requiring explicit confirmation
CATEGORY_MESSAGE = "SEND_MESSAGE"
CATEGORY_SPEND = "SPEND_MONEY"
CATEGORY_DELETE = "DELETE_DATA"
CATEGORY_SETTING = "CHANGE_SETTING"

# Tokens that mark a shell command as destructive. Checked against every
# segment of a compound command (split on ; && || |) so wrappers like
# "cd /tmp;rm x" cannot sneak past the gate.
DESTRUCTIVE_SHELL_PATTERNS = [
    "rm", "rmdir", "mv", "truncate", "drop", "delete",
    "mkfs", "dd", "shutdown", "reboot", "chmod", "chown", "sudo",
]

# Tools that always require explicit approval (writes, edits, deletions,
# settings changes) — mirrors AGENT.md's Never-Without-Asking list.
GATED_TOOLS = {
    "write_file": "File write modifies data on disk",
    "edit_file": "File edit modifies data on disk",
    "forget_memory": "Deleting a stored memory is a destructive data change",
}

# Set by the web server so request_confirmation knows which mode to use.
web_mode: bool = False


def _shell_command_segments(command: str) -> list[str]:
    """Split a shell command into individual segments on ; && || |."""
    import re

    segments = re.split(r"&&|\|\||[;|]", command)
    return [seg.strip() for seg in segments if seg.strip()]


def _shell_tokens(command: str) -> list[str]:
    """Return every whitespace token across all segments of a command."""
    tokens: list[str] = []
    for segment in _shell_command_segments(command):
        # Strip a leading env-var prefix or path so "./rm", "/bin/rm"
        # and "FOO=1 rm" still match the bare token.
        for token in segment.split():
            tokens.append(token.strip("\"'").rsplit("/", 1)[-1])
    return tokens


def requires_confirmation(
    action_type: str,
    action_name: str,
    args: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Check whether an action requires explicit user confirmation.

    Returns:
        (requires_gate, reasoning_description)
    """
    args = args or {}

    # Category checks
    if action_type == CATEGORY_DELETE or action_name in ("forget", "delete_file", "remove"):
        return True, f"Destructive operation: deleting data ('{action_name}')"

    if action_type == CATEGORY_MESSAGE or action_name in ("send_email", "send_chat", "send_sms"):
        return True, f"Outbound communication: sending message ('{action_name}')"

    if action_type == CATEGORY_SPEND:
        return True, f"Financial operation: spending money ('{action_name}')"

    if action_type == CATEGORY_SETTING or action_name in ("change_config", "update_setting"):
        return True, f"Configuration modification: changing setting ('{action_name}')"

    # Always-gated tools (file writes/edits, memory deletion)
    if action_name in GATED_TOOLS:
        return True, f"{GATED_TOOLS[action_name]} ('{action_name}')"

    # Shell command check — inspect every token of every segment so
    # compound commands can't hide a destructive piece after ; && or ||
    if action_name == "run_shell_command":
        cmd = str(args.get("command", ""))
        for token in _shell_tokens(cmd):
            if token.lower() in DESTRUCTIVE_SHELL_PATTERNS:
                return True, f"Destructive shell command contains '{token}': {cmd}"
            if token == ">":
                return True, f"Shell command redirects output ('>'): {cmd}"

    return False, ""


async def request_confirmation(
    action_name: str,
    details: Dict[str, Any],
    reasoning: str,
    auto_approve: bool = False,
) -> bool:
    """Request explicit user confirmation for an action.

    Console mode prompts y/N on stdin. Web mode registers a pending
    request that the dashboard resolves via POST /api/confirmation;
    it times out (deny) after JARVIS_TURN_TIMEOUT seconds.
    """
    log_event(
        event_type="CONFIRMATION_REQUEST",
        action=action_name,
        details=details,
        reasoning=reasoning,
        status="PENDING",
    )

    if auto_approve:
        log_event(
            event_type="CONFIRMATION_RESULT",
            action=action_name,
            details=details,
            reasoning="Auto-approved in automated mode",
            status="APPROVED",
        )
        return True

    if web_mode:
        return await _request_confirmation_web(action_name, details, reasoning)

    return await _request_confirmation_console(action_name, details, reasoning)


async def _request_confirmation_web(
    action_name: str,
    details: Dict[str, Any],
    reasoning: str,
) -> bool:
    """Web mode — create a pending request and await the dashboard's answer."""
    from jarvis.rails import pending

    timeout = float(getattr(config, "TURN_TIMEOUT", 120) or 120)
    req_id = pending.create_pending(action_name, details, reasoning, timeout=timeout)
    log_event(
        event_type="CONFIRMATION_PENDING_UI",
        action=action_name,
        details={"request_id": req_id, **(details or {})},
        reasoning="Waiting for dashboard approval",
        status="PENDING",
    )

    approved = await pending.wait_for_resolution(req_id, timeout=timeout)

    status = "APPROVED" if approved else "DENIED"
    log_event(
        event_type="CONFIRMATION_RESULT",
        action=action_name,
        details={"request_id": req_id, **(details or {})},
        reasoning=reasoning,
        status=status,
    )
    return approved


async def _request_confirmation_console(
    action_name: str,
    details: Dict[str, Any],
    reasoning: str,
) -> bool:
    """Console mode — interactive y/N prompt (unchanged behavior)."""
    print()
    print("\033[93m\033[1m⚠️  [SAFETY GATE] Confirmation Required\033[0m")
    print(f"   Reason: \033[2m{reasoning}\033[0m")
    print(f"   Action: \033[96m{action_name}\033[0m with args: {details}")

    def prompt() -> bool:
        try:
            ans = input("\033[93m   Proceed with this action? [y/N]: \033[0m").strip().lower()
            return ans in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False

    loop = asyncio.get_running_loop()
    approved = await loop.run_in_executor(None, prompt)

    status = "APPROVED" if approved else "DENIED"
    log_event(
        event_type="CONFIRMATION_RESULT",
        action=action_name,
        details=details,
        reasoning=reasoning,
        status=status,
    )

    if not approved:
        print(f"\033[91m  ❌ Action '{action_name}' cancelled by user.\033[0m\n")
    else:
        print("\033[92m  ✅ Action approved.\033[0m\n")

    return approved

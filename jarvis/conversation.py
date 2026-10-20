"""
Conversation history manager.

Keeps the running list of turns (user and assistant messages) in memory.
This is the short-term memory of the assistant — it lasts for one session.
Long-term memory across restarts comes in Tier 4.

Window bounding (Fix 4a): once the turn list exceeds MAX_CONVERSATION_TURNS,
the oldest turns are silently trimmed from the front so context can't grow
without limit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from jarvis import config

log = logging.getLogger(__name__)


@dataclass
class Conversation:
    """An in-memory conversation: a list of user/assistant turns."""

    _turns: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Private — window bounding
    # ------------------------------------------------------------------

    def _bound(self) -> None:
        """Trim the oldest turns if the window exceeds the configured limit."""
        max_turns = config.MAX_CONVERSATION_TURNS
        if max_turns > 0 and len(self._turns) > max_turns:
            overflow = len(self._turns) - max_turns
            self._turns = self._turns[overflow:]
            log.debug(
                "Conversation window bounded: trimmed %d oldest turns (now %d)",
                overflow, len(self._turns),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_user_turn(self, text: str) -> None:
        """Append a user message to the history."""
        self._turns.append({"role": "user", "content": text})
        self._bound()

    def add_assistant_turn(self, text: str) -> None:
        """Append an assistant reply to the history."""
        self._turns.append({"role": "assistant", "content": text})
        self._bound()

    def add_tool_call_turn(self, tool_calls: list[dict]) -> None:
        """Append an assistant message that contains tool call requests.

        The *tool_calls* list comes directly from the Ollama response and
        is stored as-is so that subsequent tool-result messages can be
        matched by the provider.
        """
        self._turns.append({
            "role": "assistant",
            "content": "",
            "tool_calls": tool_calls,
        })
        self._bound()

    def add_tool_result(self, content: str) -> None:
        """Append a tool-result message to the history.

        Ollama expects ``role: "tool"`` with the tool output as content.
        """
        self._turns.append({"role": "tool", "content": content})
        self._bound()

    def get_history(self) -> list[dict]:
        """Return the full conversation history for the provider."""
        return list(self._turns)

    def turn_count(self) -> int:
        """Return the number of turns so far."""
        return len(self._turns)

    def clear(self) -> None:
        """Reset the conversation (useful for '/clear' commands)."""
        self._turns.clear()


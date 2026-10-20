"""
Tool registry — the backbone of Jarvis's tool system.

Provides:
  - ``@tool`` decorator to register a function as a callable tool.
  - ``ToolRegistry`` that stores definitions and dispatches execution.

Tool-call format reference (what ``get_ollama_tools()`` returns):
    {
        "type": "function",
        "function": {
            "name": "...",
            "description": "...",
            "parameters": { ...JSON Schema... }
        }
    }
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    """Metadata for a single registered tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema for the function's parameters
    fn: Callable      # the actual callable


# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Stores tool definitions and executes them by name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # -- Registration -------------------------------------------------------

    def register(self, defn: ToolDefinition) -> None:
        if defn.name in self._tools:
            raise ValueError(f"Duplicate tool name: {defn.name!r}")
        self._tools[defn.name] = defn
        log.debug("Registered tool: %s", defn.name)

    # -- Querying -----------------------------------------------------------

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def get_ollama_tools(self) -> list[dict]:
        """Return tool definitions in the Ollama-compatible format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": defn.name,
                    "description": defn.description,
                    "parameters": defn.parameters,
                },
            }
            for defn in self._tools.values()
        ]

    # -- Execution ----------------------------------------------------------

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool by name and return its string result.

        If the tool function is async it is awaited; otherwise it is
        called synchronously.  The return value is always coerced to str.
        """
        defn = self._tools.get(name)
        if defn is None:
            return f"[Error] Unknown tool: {name}"

        try:
            if inspect.iscoroutinefunction(defn.fn):
                result = await defn.fn(**arguments)
            else:
                result = defn.fn(**arguments)
            return str(result)
        except Exception as exc:
            log.exception("Tool %s failed", name)
            return f"[Error] Tool '{name}' failed: {exc}"


# Global singleton — every @tool writes into this.
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------

def tool(
    name: str,
    description: str,
    parameters: dict,
) -> Callable:
    """Decorator that registers a function as a Jarvis tool.

    Usage::

        @tool(
            name="current_datetime",
            description="Return the current date and time.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
        )
        def current_datetime() -> str:
            ...

    Args:
        name: Unique tool name the model will reference.
        description: Human-readable description (shown to the model).
        parameters: JSON Schema dict describing the function's arguments.
    """

    def decorator(fn: Callable) -> Callable:
        registry.register(
            ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                fn=fn,
            )
        )
        return fn

    return decorator
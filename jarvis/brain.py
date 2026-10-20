"""
The brain — the single agent entry point.

Every way into the assistant (text REPL, voice adapter, heartbeat) calls
process_turn(). This function takes user input, runs it through the
provider, and yields streamed response chunks. There is deliberately only
one path through the agent logic.

Tier 2 addition: the **tool loop**.  After the model responds, we check
whether it wants to call any tools.  If so we execute them, feed the
results back, and re-call the model — looping until it produces a plain
text answer (or we hit the safety cap of MAX_TOOL_ROUNDS).

Supports tool sets: "client" (read-only analytics) and "developer" (full tools).
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Callable, Literal

from jarvis.conversation import Conversation
from jarvis.provider import ProviderError, call_with_tools, stream_response
from jarvis.rails import (
    log_event,
    request_confirmation,
    requires_confirmation,
    wrap_external_data,
)
from jarvis.tools import registry
from jarvis.tools.sets import get_tool_set

log = logging.getLogger(__name__)

# Maximum consecutive tool-call rounds before we force a text reply.
MAX_TOOL_ROUNDS = 10


async def process_turn(
    user_input: str,
    conversation: Conversation,
    system_prompt: str,
    tool_set: Literal["client", "developer"] = "developer",
    on_tool_call: Callable[[str, dict], None] | None = None,
) -> AsyncGenerator[str, None]:
    """Run one turn of conversation and yield the reply as it streams.

    1. Records the user's message in the conversation history.
    2. Enters the **tool loop**: calls the model with tool definitions,
       executes any requested tools, and feeds results back — repeating
       until the model returns a plain text answer.
    3. Streams the final text reply chunk by chunk.
    4. Records the full assistant reply in the history once complete.

    Args:
        user_input: The text the user typed (or that was transcribed).
        conversation: The running conversation state.
        system_prompt: The current system prompt.
        tool_set: Which tool set to use ("client" or "developer").
        on_tool_call: Optional callback fired each time a tool is
                      invoked.  Receives ``(tool_name, args_dict)``.

    Yields:
        str: Incremental text chunks of the assistant's reply.
    """
    conversation.add_user_turn(user_input)

    tools = get_tool_set(tool_set)

    # -- Tool loop ----------------------------------------------------------
    for _round in range(MAX_TOOL_ROUNDS):
        try:
            resp = await call_with_tools(
                messages=conversation.get_history(),
                system_prompt=system_prompt,
                tools=tools or None,
            )
        except ProviderError as exc:
            # Backend down/unreachable — degrade gracefully instead of
            # crashing the caller (chat endpoint / websocket handler).
            msg = f"I can't reach the model backend right now. ({exc})"
            log.error("Provider failure during tool loop: %s", exc)
            conversation.add_assistant_turn(msg)
            yield msg
            return

        if not resp.has_tool_calls:
            # Model gave a text answer — we might already have the full
            # text from the non-streaming call.  If so, yield it and
            # record it.
            if resp.text:
                conversation.add_assistant_turn(resp.text)
                yield resp.text
                return
            # Edge case: empty response.
            break

        # Record the assistant's tool-call message in history.
        conversation.add_tool_call_turn(resp.tool_calls)

        # Execute every requested tool.
        for tc in resp.tool_calls:
            fn_info = tc.get("function", {})
            tool_name = fn_info.get("name", "unknown")
            tool_args = fn_info.get("arguments", {})

            log.info("Tool call: %s(%s)", tool_name, tool_args)

            if on_tool_call:
                on_tool_call(tool_name, tool_args)

            # Tier 6: Safety Gate check & Audit log
            needs_gate, reason = requires_confirmation("TOOL", tool_name, tool_args)
            if needs_gate:
                approved = await request_confirmation(tool_name, tool_args, reason)
                if not approved:
                    result = f"Error: Tool '{tool_name}' execution denied by user."
                    log_event("TOOL_CALL", tool_name, tool_args, reasoning=reason, status="DENIED")
                    conversation.add_tool_result(result)
                    continue

            result = await registry.execute(tool_name, tool_args)

            # Audit AFTER execution so the recorded status reflects reality.
            executed_status = (
                "FAILED" if result.startswith("[Error]") or result.startswith("[Blocked]")
                else "SUCCESS"
            )
            log_event(
                "TOOL_CALL", tool_name, tool_args,
                reasoning="Tool executed via tool loop",
                status=executed_status,
            )

            # Tier 6: Wrap external data safely to prevent prompt injection
            if tool_name in ("run_shell_command", "read_file", "list_dir"):
                result = wrap_external_data(result, source=tool_name)

            conversation.add_tool_result(result)

    # -- Final streaming reply after tools (or if no tools were called) -----
    full_reply: list[str] = []

    try:
        async for chunk in stream_response(
            messages=conversation.get_history(),
            system_prompt=system_prompt,
        ):
            full_reply.append(chunk)
            yield chunk
    except ProviderError as exc:
        msg = f"I can't reach the model backend right now. ({exc})"
        log.error("Provider failure during streaming reply: %s", exc)
        full_reply.append(msg)
        yield msg

    # Record the complete reply so future turns see it in context.
    conversation.add_assistant_turn("".join(full_reply))


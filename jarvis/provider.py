"""
Provider seam — supports multiple model backends.

Exposes two async functions:
  - ``stream_response()`` — stream a text reply from the model.
  - ``call_with_tools()`` — non-streaming call that may return tool-call
    requests *or* a final text answer.

Everything else in the codebase calls these functions and never touches
the SDK directly.  Swapping to a different model provider means editing
this file alone.

Supported providers: Google Gemini (cloud) and Ollama (local).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from google import genai
from google.genai import types
import httpx

from jarvis import config


def _normalize_ollama_host(host: str) -> str:
    """Normalize an Ollama host URL.

    Strips trailing slashes and a trailing ``/api`` suffix (a common
    misconfiguration from pointing at the OpenAI-compatible endpoint)
    so ``/api/chat`` and ``/api/tags`` always append correctly.
    """
    cleaned = (host or "").strip().rstrip("/")
    if cleaned.endswith("/api"):
        cleaned = cleaned[: -len("/api")]
    return cleaned.rstrip("/")


def _ollama_base_url() -> str:
    """Return the normalized Ollama base URL from config."""
    return _normalize_ollama_host(config.OLLAMA_HOST)


def _resolve_model(model_name: str) -> str:
    """Return model name directly, ensuring non-empty string."""
    name = (model_name or "").strip()
    if name:
        return name
    if config.MODEL_PROVIDER == "gemini":
        return "gemini-2.5-flash"
    return config.OLLAMA_MODEL or "qwen2.5:0.5b"


class ProviderError(Exception):
    """Raised when the model provider fails in a way the caller should handle."""


def _get_client() -> genai.Client | None:
    """Get the Gemini client when that provider is active."""
    if config.MODEL_PROVIDER == "gemini":
        if not config.GEMINI_API_KEY:
            raise ProviderError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and add it to your .env file."
            )
        return genai.Client(api_key=config.GEMINI_API_KEY)
    return None


def _ollama_timeout() -> httpx.Timeout:
    """HTTP timeout for Ollama calls — long read window for local CPU inference."""
    seconds = float(getattr(config, "TURN_TIMEOUT", 120) or 120)
    # Local models can sit quiet while generating; keep connect/write tight,
    # but allow a long read window (at least 3 minutes).
    read = max(seconds, 180.0)
    return httpx.Timeout(connect=10.0, read=read, write=30.0, pool=10.0)


# ---------------------------------------------------------------------------
# Ollama helpers — keep history in native OpenAI/Ollama message shape
# ---------------------------------------------------------------------------

def _history_to_ollama(messages: list[dict], system_prompt: str) -> list[dict]:
    """Convert Jarvis history into Ollama /api/chat messages."""
    out: list[dict[str, Any]] = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg.get("role")
        if role == "user":
            out.append({"role": "user", "content": msg.get("content", "") or ""})
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                normalized = []
                for tc in tool_calls:
                    fn = tc.get("function", tc)
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"raw": args}
                    normalized.append({
                        "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": args if isinstance(args, dict) else {},
                        },
                    })
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": normalized,
                }
                out.append(entry)
            else:
                out.append({
                    "role": "assistant",
                    "content": msg.get("content", "") or "",
                })
        elif role == "tool":
            out.append({"role": "tool", "content": msg.get("content", "") or ""})
    return out


def _tools_to_ollama(tools: list[dict] | None) -> list[dict] | None:
    """Pass through OpenAI-style tool defs (already what the registry returns)."""
    if not tools:
        return None
    return tools


async def list_available_models() -> list[str]:
    """Fetch available model names that support text generation."""
    if config.MODEL_PROVIDER == "gemini":
        try:
            client = _get_client()
            if client is None:
                return ["gemini-2.5-flash", "gemini-2.0-flash"]
            names = []
            pager = await client.aio.models.list()
            async for m in pager:
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" in actions:
                    names.append((m.name or "").replace("models/", ""))
            return names or ["gemini-2.5-flash", "gemini-2.0-flash"]
        except Exception:
            return ["gemini-2.5-flash", "gemini-2.0-flash"]

    # Ollama
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_ollama_base_url()}/api/tags",
                timeout=_ollama_timeout(),
            )
            if resp.status_code == 200:
                data = resp.json()
                models = [model["name"] for model in data.get("models", [])]
                return models if models else [config.OLLAMA_MODEL or "qwen2.5:0.5b"]
            return [config.OLLAMA_MODEL or "qwen2.5:0.5b"]
    except Exception:
        return [config.OLLAMA_MODEL or "qwen2.5:0.5b"]


@dataclass
class ModelResponse:
    """Result of a single model call that may contain tool calls."""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------
# History conversion: Jarvis's internal message format -> Gemini Content list
# ---------------------------------------------------------------------------

def _history_to_contents(messages: list[dict]) -> list[types.Content]:
    """Convert Jarvis's internal message history into provider Content objects."""
    contents: list[types.Content] = []
    pending_call_names: list[str] = []

    for msg in messages:
        role = msg.get("role")

        if role == "user":
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=msg.get("content", ""))],
            ))

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                parts = []
                pending_call_names = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {}) or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"raw": args}
                    parts.append(types.Part.from_function_call(name=name, args=args))
                    pending_call_names.append(name)
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=msg.get("content", ""))],
                ))

        elif role == "tool":
            # Pair this result with the next pending function-call name, in order —
            # Jarvis's history format doesn't store which call a result belongs to,
            # so we track it positionally the same way the tool loop in brain.py
            # produces them (one result per call, same order).
            name = pending_call_names.pop(0) if pending_call_names else "unknown_tool"
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=name,
                    response={"result": msg.get("content", "")},
                )],
            ))

    return contents


def _tools_to_provider(tools: list[dict] | None) -> list[types.Tool] | None:
    """Convert Jarvis's OpenAI/Ollama-style tool defs into Provider Tool objects."""
    if not tools:
        return None
    declarations = []
    for t in tools:
        fn = t.get("function", t)
        declarations.append(types.FunctionDeclaration(
            name=fn.get("name", ""),
            description=fn.get("description", ""),
            parameters_json_schema=fn.get("parameters", {"type": "object", "properties": {}}),
        ))
    return [types.Tool(function_declarations=declarations)]


# ---------------------------------------------------------------------------
# Non-streaming call (used during the tool loop)
# ---------------------------------------------------------------------------

async def call_with_tools(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict] | None = None,
) -> ModelResponse:
    """Send a conversation to the configured model provider and return the full response.

    Same contract as the old Ollama version: returns a ModelResponse with
    either ``text`` or ``tool_calls`` populated, in the exact shape
    brain.py already expects (``{"function": {"name": ..., "arguments": ...}}``).
    """
    if config.MODEL_PROVIDER == "gemini":
        client = _get_client()
        if client is None:
            return ModelResponse(text="Error: Gemini client not initialized")
        model_name = _resolve_model(config.MODEL_NAME)
        contents = _history_to_contents(messages)
        gemini_tools = _tools_to_provider(tools)

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=config.TEMPERATURE,
            max_output_tokens=config.MAX_TOKENS,
            tools=gemini_tools,
            # Jarvis runs its OWN tool loop in brain.py (with the safety gate and
            # audit log in between calls) — disable the SDK's automatic loop so
            # every tool call passes through that gate.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=gen_config,
            )
        except Exception as exc:
            raise ProviderError(f"Gemini error: {exc}") from exc

        fcs = response.function_calls or []
        if fcs:
            tool_calls = [
                {"function": {"name": fc.name, "arguments": dict(fc.args or {})}}
                for fc in fcs
            ]
            return ModelResponse(tool_calls=tool_calls)

        return ModelResponse(text=response.text or "")

    # ---- Ollama ----
    model_name = _resolve_model(config.OLLAMA_MODEL)
    ollama_messages = _history_to_ollama(messages, system_prompt)
    ollama_data: dict[str, Any] = {
        "model": model_name,
        "messages": ollama_messages,
        "stream": False,
        "options": {
            "temperature": config.TEMPERATURE,
            "num_predict": config.MAX_TOKENS,
            "num_ctx": getattr(config, "NUM_CTX", 8192),
        },
    }
    ollama_tools = _tools_to_ollama(tools)
    if ollama_tools:
        ollama_data["tools"] = ollama_tools

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_ollama_base_url()}/api/chat",
                json=ollama_data,
                timeout=_ollama_timeout(),
            )

            if resp.status_code != 200:
                raise ProviderError(f"Ollama error: {resp.status_code} - {resp.text}")

            result = resp.json()
            message = result.get("message", {}) or {}
            message_content = message.get("content", "") or ""

            tool_calls: list[dict] = []
            for tc in message.get("tool_calls") or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                tool_calls.append({
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": args if isinstance(args, dict) else {},
                    }
                })

            if tool_calls:
                return ModelResponse(tool_calls=tool_calls)
            return ModelResponse(text=message_content)

    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Ollama error: {type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# Streaming call (used for the final text reply)
# ---------------------------------------------------------------------------

async def stream_response(
    messages: list[dict],
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """Send a conversation to the configured model provider and yield reply text as it streams."""
    if config.MODEL_PROVIDER == "gemini":
        client = _get_client()
        if client is None:
            yield "Error: Gemini client not initialized"
            return
        model_name = _resolve_model(config.MODEL_NAME)
        contents = _history_to_contents(messages)

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=config.TEMPERATURE,
            max_output_tokens=config.MAX_TOKENS,
        )

        try:
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=gen_config,
            )
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise ProviderError(f"Gemini error: {exc}") from exc
        return

    # ---- Ollama ----
    model_name = _resolve_model(config.OLLAMA_MODEL)
    ollama_messages = _history_to_ollama(messages, system_prompt)
    ollama_data = {
        "model": model_name,
        "messages": ollama_messages,
        "stream": True,
        "options": {
            "temperature": config.TEMPERATURE,
            "num_predict": config.MAX_TOKENS,
            "num_ctx": getattr(config, "NUM_CTX", 8192),
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{_ollama_base_url()}/api/chat",
                json=ollama_data,
                timeout=_ollama_timeout(),
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield f"Error: Ollama returned status {resp.status_code}: {body.decode(errors='replace')}"
                    return

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = data.get("message") or {}
                    content = message.get("content")
                    if content:
                        yield content
                    if data.get("done", False):
                        break
    except Exception as exc:
        yield f"Error: {exc}"

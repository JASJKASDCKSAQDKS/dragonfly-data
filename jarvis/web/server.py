"""
Jarvis web server — FastAPI dashboard + API.

Multi-tenant business intelligence platform for bars and shops.
All HTTP/WebSocket surfaces for the dashboard live here;
``launch_app.py`` imports this module and runs it with uvicorn.

Architecture:
  - Authentication: JWT access/refresh tokens, Argon2, TOTP MFA (developers)
  - Tenant isolation: tenant_id derived from verified token only
  - Database: per-tenant read-only MariaDB users, admin user for provisioning only
  - AI: allowlisted read-only tools for clients, full tools for developers
  - Analytics: tenant-scoped read-only endpoints for KPIs/charts
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from jarvis import config
from jarvis.brain import process_turn
from jarvis.conversation import Conversation
from jarvis.config import SYSTEM_PROMPT
from jarvis.voice import stt, tts
from jarvis.memory import manager as memory_manager
from jarvis.memory import ai_memory, auto_capture, db_intent
from jarvis.memory.store import get_store
from jarvis.tools import db_tools
from jarvis.heartbeat import manager as heartbeat_manager
from jarvis.heartbeat.killswitch import is_killswitch_active, toggle_killswitch
from jarvis.heartbeat.quiet import set_quiet_hours, get_quiet_hours, flush_missed_notices
from jarvis.rails import gate as safety_gate
from jarvis.rails.audit import get_recent_logs, log_event
from jarvis.rails import pending as pending_gate
from jarvis.web import dbadmin
from jarvis.auth.routes import router as auth_router
from jarvis.auth.client_routes import router as clients_router
from jarvis.tenants.routes import router as tenants_router
from jarvis.analytics.routes import router as analytics_router
from jarvis.assistant.routes import router as assistant_router
from jarvis.assistant.developer_service import get_developer_assistant_service, get_developer_conversation
from jarvis.auth.dependencies import get_current_user, require_developer, require_client, get_current_tenant
from jarvis.auth.models import User, Tenant, Role

log = logging.getLogger(__name__)

# Assistant replies that (wrongly) deny having memory — filtered out of
# history preloads because small models imitate their own past denials.
_MEMORY_DENIAL_RE = re.compile(
    r"haven't shared|not shared|don't have (?:access to )?(?:past|any) "
    r"(?:conversation|memor)|could you please (?:clarify|provide)|"
    r"bit of confusion|don't remember|do not remember|don't recall",
    re.IGNORECASE,
)

# Enable web-mode confirmations (pending store + dashboard modal)
# instead of stdin prompts.
safety_gate.web_mode = True


# ---------------------------------------------------------------------------
# App lifespan (starts the heartbeat so reminders actually fire)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(
        heartbeat_manager.heartbeat_loop(on_notice=_on_notice, tick_interval_seconds=5)
    )
    log.info("Heartbeat loop started (tick=5s)")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        log.info("Heartbeat loop stopped")


async def _on_notice(notice: str) -> None:
    """Queue proactive notices so the dashboard can pick them up."""
    from jarvis.heartbeat.quiet import queue_missed_notice
    queue_missed_notice(notice)
    log_event("HEARTBEAT", "SURFACE_NOTICE", details={"notice": notice}, status="DELIVERED")


async def _log_turn_to_ai_memory(user_text: str, reply: str) -> None:
    """Persist one exchange to the ai_memory MariaDB log (never breaks chat)."""
    try:
        await asyncio.to_thread(ai_memory.log_message, "user", user_text)
        await asyncio.to_thread(ai_memory.log_message, "assistant", reply)
    except Exception:
        log.warning("ai_memory turn logging failed", exc_info=True)


# Persistent developer conversation — restored from ai_memory on first use so
# the assistant remembers across turns and across restarts.
_developer_conversation: Conversation | None = None


def _get_developer_conversation() -> Conversation:
    """Return the developer's ongoing conversation, preloaded from ai_memory.

    Preloading the recent transcript as real dialogue history is what stops
    the assistant from "forgetting" between messages.
    """
    global _developer_conversation
    if _developer_conversation is None:
        conv = Conversation()
        try:
            for turn in ai_memory.recent_turns(limit=20):
                if turn["role"] == "user":
                    conv.add_user_turn(turn["content"])
                elif turn["role"] == "assistant":
                    conv.add_assistant_turn(turn["content"])
        except Exception:
            log.warning("could not preload ai_memory history", exc_info=True)
        _developer_conversation = conv
    return _developer_conversation


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add baseline browser protections without changing API response bodies."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'",
    )
    return response

# Include all routers
app.include_router(dbadmin.router)
app.include_router(auth_router)
app.include_router(clients_router)
app.include_router(tenants_router)
app.include_router(analytics_router)
app.include_router(assistant_router)


@app.get("/api/health/live", include_in_schema=True, tags=["health"])
async def liveness_endpoint():
    """Process liveness probe that does not expose application data."""
    return {"status": "ok"}


@app.get("/api/health/ready", include_in_schema=True, tags=["health"])
async def readiness_endpoint():
    """Readiness probe for the local application process."""
    return {"status": "ready", "model_provider": config.MODEL_PROVIDER}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str


class TTSRequest(BaseModel):
    text: str


class MemoryRequest(BaseModel):
    text: str
    category: str = "general"


class QuietRequest(BaseModel):
    start: int
    end: int


class ReminderRequest(BaseModel):
    text: str
    delay: str


class ConfirmationRequest(BaseModel):
    request_id: int
    approved: bool


class ModelRequest(BaseModel):
    model: str


async def _create_database_from_chat(text: str) -> str | None:
    """Execute unambiguous database requests before the model can hallucinate success."""
    name = db_intent.detect_new_database_request(text)
    if name is None:
        return None
    return await asyncio.to_thread(db_tools.create_database_impl, name)


# ---------------------------------------------------------------------------
# Core chat (legacy - kept for backward compatibility, requires auth)
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, user: User = Depends(require_developer)):
    """Legacy chat endpoint - delegates to assistant module for tenant-scoped chat."""
    # For developers, allow global chat (backward compatibility)
    if user.role == Role.DEVELOPER:
        try:
            database_result = await _create_database_from_chat(req.message)
            if database_result is not None:
                await _log_turn_to_ai_memory(req.message, database_result)
                return JSONResponse({"status": "success", "reply": database_result})

            # Persistent conversation, preloaded from long-term memory.
            conv = _get_developer_conversation()
            system_prompt = memory_manager.build_prompt(turn_count=conv.turn_count())

            full_response: list[str] = []
            async for chunk in process_turn(
                user_input=req.message,
                conversation=conv,
                system_prompt=system_prompt,
            ):
                full_response.append(chunk)

            reply = "".join(full_response)
            await _log_turn_to_ai_memory(req.message, reply)
            return JSONResponse({"status": "success", "reply": reply})
        except Exception as e:
            logging.exception("Chat endpoint crash")
            return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
    
    # For clients, delegate to assistant module (tenant-scoped)
    # This endpoint is kept for backward compatibility
    # New clients should use /api/assistant/chat
    return JSONResponse(
        status_code=400,
        content={"status": "error", "message": "Use /api/assistant/chat for tenant-scoped chat"}
    )


# ---------------------------------------------------------------------------
# Voice (legacy - kept for backward compatibility, requires auth)
# ---------------------------------------------------------------------------

@app.post("/api/voice/stt")
async def stt_endpoint(file: UploadFile = File(...), user: User = Depends(require_developer)):
    try:
        audio_bytes = await file.read()
        text = await stt.transcribe(audio_bytes)
        return JSONResponse({"status": "success", "text": text})
    except stt.STTError as e:
        return JSONResponse(status_code=503, content={"status": "error", "message": str(e)})
    except Exception as e:
        logging.exception("STT endpoint crash")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.post("/api/voice/tts")
async def tts_endpoint(req: TTSRequest, user: User = Depends(require_developer)):
    """Stream TTS audio.

    The first chunk is probed before committing to the streaming
    response, so API-level failures (missing key permissions, bad voice
    id, quota) surface as a 503 JSON body with a human-readable reason
    instead of a silent empty 200 audio stream.
    """
    try:
        reason = tts.tts_disabled_reason()
        if reason:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": f"Voice reply unavailable: {reason}"},
            )

        agen = tts.stream_audio_bytes(req.text)
        first_chunk: bytes | None = None
        try:
            first_chunk = await agen.__anext__()
        except StopAsyncIteration:
            # Empty/blank text — nothing to synthesize; keep the audio
            # content type so the client's player path stays uniform.
            return StreamingResponse(iter(()), media_type="audio/pcm")
        except tts.TTSError as exc:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": f"Voice reply unavailable: {exc}"},
            )

        async def _stream() -> AsyncGenerator[bytes, None]:
            try:
                yield first_chunk
                async for chunk in agen:
                    yield chunk
            except tts.TTSError as exc:
                log.warning("TTS stream failed mid-stream: %s", exc)
            except Exception:
                log.exception("TTS stream crashed mid-stream")
            finally:
                await agen.aclose()

        return StreamingResponse(_stream(), media_type="audio/pcm")
    except Exception as e:
        logging.exception("TTS endpoint crash")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# System status & management (developer only)
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def status_endpoint(user: User = Depends(require_developer)):
    store = get_store()
    return JSONResponse({
        "memory_count": len(store.list_memories()),
        "killswitch_active": is_killswitch_active(),
        "model": config.get_model_name(),
    })


@app.get("/api/models")
async def models_endpoint(user: User = Depends(require_developer)):
    from jarvis.provider import list_available_models
    models = await list_available_models()
    return JSONResponse({"models": models, "current": config.get_model_name()})


@app.post("/api/model")
async def set_model_endpoint(req: ModelRequest, user: User = Depends(require_developer)):
    from jarvis.config import set_model_name
    new_model = set_model_name(req.model)
    return JSONResponse({"status": "success", "model": new_model})


@app.post("/api/killswitch")
async def killswitch_endpoint(user: User = Depends(require_developer)):
    new_state = toggle_killswitch()
    return JSONResponse({"status": "success", "active": new_state})


@app.get("/api/quiet")
async def get_quiet_endpoint(user: User = Depends(require_developer)):
    start, end = get_quiet_hours()
    return JSONResponse({"status": "success", "start": start, "end": end})


@app.post("/api/quiet")
async def quiet_endpoint(req: QuietRequest, user: User = Depends(require_developer)):
    if not (0 <= req.start <= 23 and 0 <= req.end <= 23):
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Hours must be 0-23."},
        )
    set_quiet_hours(req.start, req.end)
    log_event(
        "SETTING", "SET_QUIET_HOURS",
        details={"start": req.start, "end": req.end},
        reasoning="Quiet hours updated from dashboard",
        status="SUCCESS",
    )
    start, end = get_quiet_hours()
    return JSONResponse({"status": "success", "start": start, "end": end})


@app.post("/api/reminders")
async def reminders_endpoint(req: ReminderRequest, user: User = Depends(require_developer)):
    msg = heartbeat_manager.add_reminder(req.text, req.delay)
    return JSONResponse({"status": "success", "message": msg})


@app.get("/api/reminders")
async def list_reminders_endpoint(user: User = Depends(require_developer)):
    return JSONResponse(heartbeat_manager.list_pending_reminders())


@app.get("/api/audit")
async def audit_endpoint(limit: int = 30, user: User = Depends(require_developer)):
    logs = get_recent_logs(limit)
    return JSONResponse({"logs": logs})


@app.get("/api/notices")
async def notices_endpoint(user: User = Depends(require_developer)):
    """Return and clear pending missed notices (quiet-hours backlog)."""
    notices = flush_missed_notices()
    return JSONResponse({"status": "success", "notices": notices})


# ---------------------------------------------------------------------------
# Safety gate — pending confirmations from the dashboard modal (developer only)
# ---------------------------------------------------------------------------

@app.get("/api/confirmation/pending")
async def confirmation_pending_endpoint(user: User = Depends(require_developer)):
    return JSONResponse({"status": "success", "requests": pending_gate.list_pending()})


@app.post("/api/confirmation")
async def confirmation_endpoint(req: ConfirmationRequest, user: User = Depends(require_developer)):
    resolved = pending_gate.resolve(req.request_id, req.approved)
    if not resolved:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "No open confirmation with that id."},
        )
    return JSONResponse({"status": "success", "request_id": req.request_id, "approved": req.approved})


# ---------------------------------------------------------------------------
# Memory (developer only for global memory; clients use per-tenant memory via assistant)
# ---------------------------------------------------------------------------

@app.get("/api/memories")
async def list_memories_endpoint(user: User = Depends(require_developer)):
    store = get_store()
    memories = store.list_memories()
    res = [
        {"id": m.id, "category": m.category, "content": m.content, "created_at": m.created_at}
        for m in memories
    ]
    return JSONResponse(res)


@app.post("/api/memories")
async def add_memory_endpoint(req: MemoryRequest, user: User = Depends(require_developer)):
    result = memory_manager.remember(req.text, req.category)
    return JSONResponse({"status": "success", "message": result})


@app.delete("/api/memories/{mem_id}")
async def delete_memory_endpoint(mem_id: int, user: User = Depends(require_developer)):
    result = memory_manager.forget(mem_id)
    return JSONResponse({"status": "success", "message": result})


@app.post("/api/conversation/clear")
async def clear_conversation_endpoint(user: User = Depends(require_developer)):
    """Reset the developer's in-memory chat (stored long-term memories kept)."""
    global _developer_conversation
    _developer_conversation = None
    return JSONResponse({"status": "success", "message": "Conversation cleared."})


# ---------------------------------------------------------------------------
# WebSocket — live streaming chat (legacy - kept for backward compatibility)
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_chat(websocket: WebSocket):
    """Legacy WebSocket endpoint - requires token in query params for auth."""
    # Extract token from query params
    query_params = dict(websocket.query_params)
    token = query_params.get("token")
    
    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return
    
    # Verify token
    from jarvis.auth.service import get_auth_service
    auth_service = get_auth_service()
    try:
        user, tenant = auth_service.verify_access_token(token)
    except ValueError as e:
        await websocket.close(code=4001, reason=str(e))
        return
    
    await websocket.accept()
    log.info(f"WebSocket client connected: {user.email} (tenant: {tenant.name if tenant else 'developer'})")
    
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "chat":
                await websocket.send_json({"type": "error", "content": "Unknown message type."})
                continue

            text = (data.get("text") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "content": "Empty message."})
                continue

            # For developers, keep one ongoing conversation restored from memory.
            if user.role == Role.DEVELOPER:
                database_result = await _create_database_from_chat(text)
                if database_result is not None:
                    await websocket.send_json({"type": "turn_start"})
                    await websocket.send_json({"type": "chunk", "content": database_result})
                    await websocket.send_json({"type": "turn_end"})
                    await _log_turn_to_ai_memory(text, database_result)
                    continue

                conv = _get_developer_conversation()
                system_prompt = memory_manager.build_prompt(turn_count=conv.turn_count())

                await websocket.send_json({"type": "turn_start"})
                full_reply: list[str] = []
                try:
                    async for chunk in process_turn(
                        user_input=text,
                        conversation=conv,
                        system_prompt=system_prompt,
                    ):
                        full_reply.append(chunk)
                        await websocket.send_json({"type": "chunk", "content": chunk})
                    await websocket.send_json({"type": "turn_end"})
                    await _log_turn_to_ai_memory(text, "".join(full_reply))
                except Exception as exc:
                    log.exception("WebSocket turn failed")
                    await websocket.send_json({"type": "error", "content": str(exc)})
            else:
                # For clients, delegate to assistant module (tenant-scoped)
                await websocket.send_json({
                    "type": "error", 
                    "content": "Use /api/assistant/ws for tenant-scoped chat"
                })
    except WebSocketDisconnect:
        log.info("WebSocket client disconnected")
    except Exception:
        log.exception("WebSocket handler crashed")


# ---------------------------------------------------------------------------
# Pages — login gate + dashboard shell
# ---------------------------------------------------------------------------

static_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
LOGIN_PAGE = os.path.join(static_path, "login.html")
APP_PAGE = os.path.join(static_path, "index.html")
CLIENT_PAGE = os.path.join(static_path, "client.html")
DEVELOPER_PAGE = os.path.join(static_path, "developer.html")
DEMO_PAGE = os.path.join(static_path, "demo.html")


@app.get("/")
@app.get("/login")
async def login_page():
    """Serve the login page. This is the entry point for the app.

    Authentication is client-side (JWT in localStorage); the login page
    redirects straight to the dashboard when a valid session already exists.
    """
    return FileResponse(LOGIN_PAGE)


@app.get("/app")
async def app_page():
    """Serve the dashboard. Its client-side guard redirects to /login when
    there is no valid token."""
    return FileResponse(APP_PAGE)


@app.get("/client")
async def client_page():
    """Serve the owner portal; its client-side guard requires a client token."""
    return FileResponse(CLIENT_PAGE)


@app.get("/developer")
async def developer_page():
    """Serve the developer console; its API calls enforce developer access."""
    return FileResponse(DEVELOPER_PAGE)


@app.get("/demo")
async def demo_page():
    """Serve an unauthenticated fictional-data preview, never a tenant dashboard."""
    return FileResponse(DEMO_PAGE)


if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


# ---------------------------------------------------------------------------
# Launcher entry point
# ---------------------------------------------------------------------------

async def launch_browser() -> None:
    await asyncio.sleep(1.5)
    import webbrowser
    webbrowser.open("http://localhost:8000")


def run() -> None:
    """Run the dashboard server (called by launch_app.py)."""
    import threading

    thread = threading.Thread(target=lambda: asyncio.run(launch_browser()), daemon=True)
    thread.start()
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
Assistant API routes (client-scoped).

Endpoints for the tenant-scoped AI assistant with text and voice support.
All endpoints require client authentication and operate only on the
authenticated user's tenant data.

Endpoints:
- POST /api/assistant/chat - Streaming chat with allowlisted tools
- GET /api/assistant/history - Get conversation history
- GET /api/assistant/sessions - List recent sessions
- DELETE /api/assistant/sessions/{session_id} - Delete a session
- POST /api/assistant/voice/stt - Speech to text
- POST /api/assistant/voice/tts - Text to speech
- GET /api/assistant/ws - WebSocket for streaming chat
"""

from __future__ import annotations

import json
import secrets
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, WebSocket, WebSocketDisconnect, status, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from jarvis.auth.dependencies import require_client, get_current_tenant
from jarvis.auth.models import Tenant, User
from jarvis.assistant.service import get_assistant_service
from jarvis.voice import stt, tts

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


# =========================================================================
# Request/Response Models
# =========================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class SessionResponse(BaseModel):
    session_id: str
    created_at: str
    turn_count: int


class HistoryResponse(BaseModel):
    session_id: str
    turns: list[dict]


# =========================================================================
# Chat Endpoints
# =========================================================================

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_client),
):
    """Streaming chat with the AI assistant using allowlisted tools."""
    assistant = get_assistant_service(tenant, user.id)
    
    # Generate session ID if not provided
    session_id = request.session_id or f"session_{secrets.token_urlsafe(18)}"
    
    async def stream_response():
        full_reply = []
        async for chunk in assistant.chat(request.message, session_id):
            full_reply.append(chunk)
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        
        # Send completion
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
    
    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": session_id,
        },
    )


@router.post("/chat/simple", response_model=ChatResponse)
async def chat_simple_endpoint(
    request: ChatRequest,
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_client),
):
    """Simple non-streaming chat for testing."""
    assistant = get_assistant_service(tenant, user.id)
    
    session_id = request.session_id or f"session_{secrets.token_urlsafe(18)}"
    reply = await assistant.chat_simple(request.message, session_id)
    
    return ChatResponse(session_id=session_id, reply=reply)


# =========================================================================
# Conversation History Endpoints
# =========================================================================

@router.get("/history", response_model=HistoryResponse)
async def get_history(
    session_id: str = Query(..., description="Session ID"),
    limit: int = Query(50, ge=1, le=200),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_client),
):
    """Get conversation history for a session."""
    assistant = get_assistant_service(tenant, user.id)
    history = assistant.get_conversation_history(session_id, limit)
    
    turns = []
    for turn in history:
        turns.append({
            "id": turn.id,
            "role": turn.role,
            "content": turn.content,
            "tool_calls": turn.tool_calls,
            "tool_results": turn.tool_results,
            "created_at": turn.created_at,
        })
    
    return HistoryResponse(session_id=session_id, turns=turns)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    limit: int = Query(10, ge=1, le=50),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_client),
):
    """List recent conversation sessions."""
    assistant = get_assistant_service(tenant, user.id)
    session_ids = assistant.get_recent_sessions(limit)
    
    sessions = []
    for sid in session_ids:
        history = assistant.get_conversation_history(sid, limit=1)
        if history:
            sessions.append(SessionResponse(
                session_id=sid,
                created_at=history[0].created_at,
                turn_count=len(assistant.get_conversation_history(sid, limit=200)),
            ))
    
    return sessions


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_client),
):
    """Delete a conversation session."""
    assistant = get_assistant_service(tenant, user.id)
    deleted = assistant.delete_session(session_id)
    
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    
    return {"status": "success", "message": f"Deleted {deleted} turns"}


@router.delete("/sessions")
async def clear_all_sessions(
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_client),
):
    """Clear all conversation sessions for this tenant."""
    assistant = get_assistant_service(tenant, user.id)
    deleted = assistant.clear_all_sessions()
    
    return {"status": "success", "message": f"Cleared {deleted} turns"}


# =========================================================================
# Voice Endpoints
# =========================================================================

@router.post("/voice/stt")
async def assistant_stt_endpoint(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_client),
):
    """Speech to text for assistant."""
    try:
        audio_bytes = await file.read()
        text = await stt.transcribe(audio_bytes)
        return {"status": "success", "text": text}
    except stt.STTError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        log.exception("Assistant STT endpoint crash")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voice/tts")
async def assistant_tts_endpoint(
    text: str = Query(..., min_length=1, max_length=5000),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Text to speech for assistant."""
    try:
        reason = tts.tts_disabled_reason()
        if reason:
            raise HTTPException(status_code=503, detail=f"Voice reply unavailable: {reason}")
        
        agen = tts.stream_audio_bytes(text)
        first_chunk: bytes | None = None
        try:
            first_chunk = await agen.__anext__()
        except StopAsyncIteration:
            return StreamingResponse(iter(()), media_type="audio/pcm")
        except tts.TTSError as exc:
            raise HTTPException(status_code=503, detail=f"Voice reply unavailable: {exc}")
        
        async def _stream():
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
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Assistant TTS endpoint crash")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# WebSocket Endpoint
# =========================================================================

@router.websocket("/ws")
async def assistant_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Legacy JWT access token"),
):
    """WebSocket for streaming chat with the AI assistant."""
    # Verify token
    from jarvis.auth.service import get_auth_service
    auth_service = get_auth_service()
    
    try:
        from jarvis import config
        session_token = websocket.cookies.get(config.AUTH_COOKIE_NAME) or token
        if not session_token:
            raise ValueError("Authentication required")
        user, tenant = auth_service.verify_access_token(session_token)
    except ValueError as e:
        await websocket.close(code=4001, reason=str(e))
        return
    
    # Ensure user is a client with this tenant
    if user.role != "client" or not tenant:
        await websocket.close(code=4003, reason="Client access required")
        return
    
    await websocket.accept()
    log.info(f"Assistant WebSocket connected: {user.email} (tenant: {tenant.name})")
    
    assistant = get_assistant_service(tenant, user.id)
    
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
            
            session_id = data.get("session_id") or f"ws_{secrets.token_urlsafe(18)}"
            
            await websocket.send_json({"type": "turn_start", "session_id": session_id})
            
            try:
                async for chunk in assistant.chat(text, session_id):
                    await websocket.send_json({"type": "chunk", "content": chunk})
                await websocket.send_json({"type": "turn_end", "session_id": session_id})
            except Exception as exc:
                log.exception("Assistant WebSocket turn failed")
                await websocket.send_json({"type": "error", "content": str(exc)})
                
    except WebSocketDisconnect:
        log.info("Assistant WebSocket client disconnected")
    except Exception:
        log.exception("Assistant WebSocket handler crashed")
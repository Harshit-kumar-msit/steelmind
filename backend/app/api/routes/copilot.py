"""
Module: api/routes/copilot.py
Purpose: Chat endpoints for the AI Maintenance Copilot.
         Supports SSE streaming (/chat/stream) and WebSocket (/ws/{session_id}).
         Persists full conversation history to PostgreSQL ChatSession.
         Gap 1: injects logbook context into every LLM call.
         Gap 3: reads user role and passes to orchestrator for role-based prompts.
"""
import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from loguru import logger

from app.db.session import get_db
from app.db.models import Equipment, Alert, AlertStatus, ChatSession, User
from app.db.schemas import ChatRequest
from app.ai.llm.orchestrator import get_orchestrator, EquipmentContext
from app.core.config import settings

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _load_logbook_context(equipment_id: str, db: AsyncSession) -> str:
    """Gap 1: Fetch last 5 log entries for LLM context injection."""
    if not equipment_id:
        return ""
    from app.db.logbook_model import MaintenanceLog
    from sqlalchemy import desc
    result = await db.execute(
        select(MaintenanceLog)
        .where(MaintenanceLog.equipment_id == equipment_id)
        .order_by(desc(MaintenanceLog.created_at))
        .limit(5)
    )
    logs = list(reversed(result.scalars().all()))
    if not logs:
        return ""
    lines = [f"RECENT FLOOR OBSERVATIONS — {equipment_id}:"]
    for log in logs:
        ts = log.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"  [{ts}] {log.logged_by} ({log.log_type}): {log.notes}")
    return "\n".join(lines)


async def _load_equipment_context(equipment_id: str, db: AsyncSession) -> EquipmentContext:
    """Build EquipmentContext from DB + latest health metrics."""
    if not equipment_id:
        return EquipmentContext()

    result = await db.execute(
        select(Equipment).where(Equipment.equipment_id == equipment_id)
    )
    eq = result.scalar_one_or_none()
    if not eq:
        return EquipmentContext(equipment_id=equipment_id)

    alert_result = await db.execute(
        select(Alert).where(
            Alert.equipment_id == equipment_id,
            Alert.status == AlertStatus.OPEN,
        )
    )
    open_alerts = alert_result.scalars().all()

    return EquipmentContext(
        equipment_id=eq.equipment_id,
        equipment_name=eq.name,
        equipment_type=eq.equipment_type,
        criticality=eq.criticality,
        anomaly_score=eq.current_anomaly_score or 0.0,
        severity=(
            "critical" if (eq.current_anomaly_score or 0) >= settings.anomaly_critical_threshold
            else "warning" if (eq.current_anomaly_score or 0) >= settings.anomaly_warning_threshold
            else "normal"
        ),
        rul_days=eq.current_rul_days or 999.0,
        priority_score=eq.current_priority_score or 0.0,
        active_alerts_count=len(open_alerts),
        last_maintenance_date=eq.last_maintenance_date.isoformat() if eq.last_maintenance_date else None,
    )


async def _get_or_create_session(
    session_id: str, user_id: str, equipment_id: str, db: AsyncSession
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(ChatSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        session = ChatSession(
            session_id=session_id,
            user_id=user_id,
            equipment_id=equipment_id,
            messages=[],
        )
        db.add(session)
        await db.flush()
    return session


def _trim_history(messages: list[dict], max_turns: int = 10) -> list[dict]:
    limit = max_turns * 2
    return messages[-limit:] if len(messages) > limit else messages


async def _get_user_role(user_id: str, db: AsyncSession) -> str:
    """Gap 3: look up user role for role-based prompt selection."""
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    return user.role if user else "engineer"


# ─── Standard Chat ────────────────────────────────────────────────────────────

@router.post("/chat", response_model=dict)
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Non-streaming chat. Returns full JSON response."""
    session   = await _get_or_create_session(body.session_id, body.user_id, body.equipment_id, db)
    ctx       = await _load_equipment_context(body.equipment_id, db)
    logbook   = await _load_logbook_context(body.equipment_id, db)
    user_role = await _get_user_role(body.user_id, db)
    orch      = get_orchestrator()
    history   = [{"role": m["role"], "content": m["content"]} for m in _trim_history(session.messages)]

    response = await orch.respond(
        message=body.message,
        context=ctx,
        conversation_history=history,
        db=db,
        user_name=body.user_id,
        user_role=user_role,
        logbook_context=logbook,
    )

    now = datetime.utcnow().isoformat()
    session.messages = [
        *session.messages,
        {"role": "user",      "content": body.message,  "timestamp": now, "citations": [], "actions": []},
        {"role": "assistant", "content": response.text,  "timestamp": now,
         "citations": response.citations,
         "actions": [{"action_type": a.action_type, "label": a.label, "payload": a.payload}
                     for a in response.actions]},
    ]
    await db.commit()

    return {
        "session_id":  body.session_id,
        "response":    response.text,
        "citations":   response.citations,
        "actions":     [{"action_type": a.action_type, "label": a.label, "payload": a.payload}
                        for a in response.actions],
        "intent":      response.intent,
        "chunks_used": response.chunks_used,
        "model":       response.model_used,
    }


# ─── Streaming Chat (SSE) ─────────────────────────────────────────────────────

@router.get("/chat/stream")
async def chat_stream(
    session_id:   str,
    message:      str,
    equipment_id: str = "",
    user_id:      str = "engineer",
    db:           AsyncSession = Depends(get_db),
):
    """
    Server-Sent Events streaming chat.
    Frontend connects with EventSource; receives token-by-token response.
    Events: {type: token|citations|actions|done|error, ...}
    """
    session   = await _get_or_create_session(session_id, user_id, equipment_id, db)
    ctx       = await _load_equipment_context(equipment_id, db)
    logbook   = await _load_logbook_context(equipment_id, db)
    user_role = await _get_user_role(user_id, db)
    orch      = get_orchestrator()
    history   = [{"role": m["role"], "content": m["content"]} for m in _trim_history(session.messages)]

    full_text     = ""
    all_citations: list = []
    all_actions:   list = []

    async def event_generator():
        nonlocal full_text, all_citations, all_actions
        try:
            async for chunk in orch.stream_response(
                message=message,
                context=ctx,
                conversation_history=history,
                db=db,
                user_name=user_id,
                user_role=user_role,
                logbook_context=logbook,
            ):
                payload = json.loads(chunk.strip())
                if payload["type"] == "token":
                    full_text += payload["content"]
                elif payload["type"] == "citations":
                    all_citations = payload["data"]
                elif payload["type"] == "done" and payload.get("actions"):
                    all_actions = payload["actions"]
                yield f"data: {chunk}\n\n"

        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            now = datetime.utcnow().isoformat()
            session.messages = [
                *session.messages,
                {"role": "user",      "content": message,   "timestamp": now, "citations": [], "actions": []},
                {"role": "assistant", "content": full_text,  "timestamp": now,
                 "citations": all_citations, "actions": all_actions},
            ]
            try:
                await db.commit()
            except Exception as db_err:
                logger.error(f"Failed to persist chat session: {db_err}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ─── WebSocket Chat ───────────────────────────────────────────────────────────

@router.websocket("/ws/{session_id}")
async def websocket_chat(
    websocket:    WebSocket,
    session_id:   str,
    equipment_id: str = "",
    user_id:      str = "engineer",
    db:           AsyncSession = Depends(get_db),
):
    await websocket.accept()
    session = await _get_or_create_session(session_id, user_id, equipment_id, db)
    orch    = get_orchestrator()
    logger.info(f"WebSocket connected: session={session_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                user_message = data.get("message", "")
                eq_id        = data.get("equipment_id", equipment_id)
            except json.JSONDecodeError:
                user_message = raw
                eq_id        = equipment_id

            if not user_message.strip():
                continue

            ctx       = await _load_equipment_context(eq_id, db)
            logbook   = await _load_logbook_context(eq_id, db)
            user_role = await _get_user_role(user_id, db)
            history   = [{"role": m["role"], "content": m["content"]}
                         for m in _trim_history(session.messages)]

            full_text     = ""
            all_citations: list = []
            all_actions:   list = []

            async for chunk in orch.stream_response(
                message=user_message,
                context=ctx,
                conversation_history=history,
                db=db,
                user_name=user_id,
                user_role=user_role,
                logbook_context=logbook,
            ):
                payload = json.loads(chunk.strip())
                if payload["type"] == "token":
                    full_text += payload["content"]
                elif payload["type"] == "citations":
                    all_citations = payload["data"]
                elif payload["type"] == "actions":
                    all_actions = payload["data"]
                await websocket.send_text(chunk)

            now = datetime.utcnow().isoformat()
            session.messages = [
                *session.messages,
                {"role": "user",      "content": user_message, "timestamp": now, "citations": [], "actions": []},
                {"role": "assistant", "content": full_text,     "timestamp": now,
                 "citations": all_citations, "actions": all_actions},
            ]
            await db.commit()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        await websocket.close()


# ─── Session History ──────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/history")
async def get_chat_history(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatSession).where(ChatSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"session_id": session_id, "messages": []}
    return {
        "session_id":   session.session_id,
        "equipment_id": session.equipment_id,
        "messages":     session.messages,
        "created_at":   session.created_at.isoformat(),
    }


@router.delete("/sessions/{session_id}")
async def clear_session(session_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(ChatSession)
        .where(ChatSession.session_id == session_id)
        .values(messages=[])
    )
    await db.commit()
    return {"status": "cleared"}

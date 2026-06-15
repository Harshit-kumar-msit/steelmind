"""
Module: api/routes/logbook.py
Purpose: CRUD endpoints for the digital maintenance logbook.
         GET  /equipment/{id}/logs   — retrieve log history (last N entries)
         POST /equipment/{id}/logs   — add a new log entry
         GET  /equipment/{id}/logs/context — formatted string for LLM context injection
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from app.db.session import get_db
from app.db.models import Equipment
from app.db.logbook_model import MaintenanceLog

router = APIRouter()


class LogEntryCreate(BaseModel):
    logged_by:    str
    log_type:     str = "observation"
    notes:        str
    work_order_id:str = ""


@router.get("/equipment/{equipment_id}/logs")
async def get_logs(
    equipment_id: str,
    limit: int = Query(20, le=100),
    log_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return recent log entries for an equipment, newest first."""
    query = (
        select(MaintenanceLog)
        .where(MaintenanceLog.equipment_id == equipment_id)
        .order_by(desc(MaintenanceLog.created_at))
        .limit(limit)
    )
    if log_type:
        query = query.where(MaintenanceLog.log_type == log_type)

    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id":           str(log.id),
            "equipment_id": log.equipment_id,
            "logged_by":    log.logged_by,
            "log_type":     log.log_type,
            "notes":        log.notes,
            "work_order_id":log.work_order_id,
            "created_at":   log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.post("/equipment/{equipment_id}/logs", status_code=201)
async def add_log(
    equipment_id: str,
    body: LogEntryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new log entry. Called by UI button or Copilot ACTION:ADD_LOG."""
    # Verify equipment exists
    eq_result = await db.execute(
        select(Equipment).where(Equipment.equipment_id == equipment_id)
    )
    if not eq_result.scalar_one_or_none():
        raise HTTPException(404, f"Equipment {equipment_id} not found")

    log = MaintenanceLog(
        equipment_id=equipment_id,
        logged_by=body.logged_by,
        log_type=body.log_type,
        notes=body.notes,
        work_order_id=body.work_order_id,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return {"id": str(log.id), "status": "created", "created_at": log.created_at.isoformat()}


@router.get("/equipment/{equipment_id}/logs/context")
async def get_log_context(
    equipment_id: str,
    last_n: int = Query(5, le=20),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a formatted text block of the last N log entries.
    Injected directly into the Copilot system prompt so the LLM can
    reference floor observations when answering questions.

    Example output:
        RECENT MAINTENANCE LOG — EQ-BF-001 (last 5 entries):
        [2024-11-15 06:30] TECH-001 (observation): Oil looks darker than usual, slight burnt smell
        [2024-11-14 14:00] TECH-003 (inspection): Checked coupling alignment — within spec 0.03mm
        ...
    """
    result = await db.execute(
        select(MaintenanceLog)
        .where(MaintenanceLog.equipment_id == equipment_id)
        .order_by(desc(MaintenanceLog.created_at))
        .limit(last_n)
    )
    logs = list(reversed(result.scalars().all()))  # oldest first for readability

    if not logs:
        return {"context": f"No maintenance log entries found for {equipment_id}."}

    lines = [f"RECENT MAINTENANCE LOG — {equipment_id} (last {len(logs)} entries):"]
    for log in logs:
        ts = log.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"  [{ts}] {log.logged_by} ({log.log_type}): {log.notes}")

    return {"context": "\n".join(lines)}

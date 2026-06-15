"""
Module: api/routes/workorders.py
"""
import uuid
import random
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.db.session import get_db
from app.db.models import WorkOrder, WorkOrderStatus
from app.db.schemas import WorkOrderCreate

router = APIRouter()

WO_COUNTER = 4000  # Start WO codes from WO-YYYY-4000


def _next_wo_code() -> str:
    global WO_COUNTER
    WO_COUNTER += 1
    return f"WO-{datetime.utcnow().year}-{WO_COUNTER}"


@router.get("/")
async def list_work_orders(
    status:       Optional[str] = Query(None),
    priority:     Optional[str] = Query(None),
    equipment_id: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(WorkOrder)
    filters = []
    if status:        filters.append(WorkOrder.status      == status)
    if priority:      filters.append(WorkOrder.priority    == priority)
    if equipment_id:  filters.append(WorkOrder.equipment_id== equipment_id)
    if filters:       query = query.where(and_(*filters))
    query = query.order_by(WorkOrder.created_at.desc()).limit(limit)
    result = await db.execute(query)
    wos = result.scalars().all()
    return [
        {
            "id":             str(w.id),
            "wo_code":        w.wo_code,
            "equipment_id":   w.equipment_id,
            "wo_type":        w.wo_type,
            "priority":       w.priority,
            "status":         w.status,
            "title":          w.title,
            "description":    w.description,
            "tasks":          w.tasks,
            "estimated_hours":w.estimated_hours,
            "scheduled_date": w.scheduled_date.isoformat() if w.scheduled_date else None,
            "assigned_to":    w.assigned_to,
            "parts_required": w.parts_required,
            "ai_generated":   w.ai_generated,
            "created_at":     w.created_at.isoformat(),
        }
        for w in wos
    ]


@router.post("/", status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    wo = WorkOrder(
        wo_code=_next_wo_code(),
        equipment_id=body.equipment_id,
        wo_type=body.wo_type,
        priority=body.priority,
        status=WorkOrderStatus.OPEN,
        title=body.title,
        description=body.description,
        tasks=body.tasks,
        estimated_hours=body.estimated_hours,
        scheduled_date=body.scheduled_date,
        assigned_to=body.assigned_to,
        parts_required=body.parts_required,
        trigger_alert_id=body.trigger_alert_id,
        ai_generated=body.ai_generated,
        created_by=body.assigned_to[0] if body.assigned_to else "system",
    )
    db.add(wo)
    await db.commit()
    await db.refresh(wo)
    return {"wo_code": wo.wo_code, "id": str(wo.id), "status": "created"}


@router.patch("/{wo_code}/status")
async def update_wo_status(
    wo_code: str,
    status: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(WorkOrder).where(WorkOrder.wo_code == wo_code))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(404, "Work order not found")
    wo.status = status
    if status == "in_progress": wo.started_at   = datetime.utcnow()
    if status == "completed":   wo.completed_at = datetime.utcnow()
    await db.commit()
    return {"status": "updated", "wo_code": wo_code, "new_status": status}

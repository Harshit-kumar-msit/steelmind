"""
Module: api/routes/alerts.py
"""
from datetime import datetime
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from app.db.session import get_db
from app.db.models import Alert, AlertStatus, AlertSeverity
from app.db.schemas import AlertAcknowledge

router = APIRouter()


@router.get("/")
async def list_alerts(
    status:    Optional[str] = Query(None),
    severity:  Optional[str] = Query(None),
    equipment_id: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = select(Alert)
    filters = []
    if status:        filters.append(Alert.status   == status)
    if severity:      filters.append(Alert.severity == severity)
    if equipment_id:  filters.append(Alert.equipment_id == equipment_id)
    if filters:       query = query.where(and_(*filters))
    query = query.order_by(Alert.created_at.desc()).limit(limit)
    result = await db.execute(query)
    alerts = result.scalars().all()
    return [
        {
            "id":            str(a.id),
            "alert_code":    a.alert_code,
            "equipment_id":  a.equipment_id,
            "severity":      a.severity,
            "status":        a.status,
            "alert_type":    a.alert_type,
            "title":         a.title,
            "description":   a.description,
            "anomaly_score": a.anomaly_score,
            "rul_days":      a.rul_days,
            "created_at":    a.created_at.isoformat(),
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        }
        for a in alerts
    ]


@router.patch("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    body: AlertAcknowledge,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Alert).where(Alert.alert_code == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status          = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by = body.acknowledged_by
    alert.acknowledged_at = datetime.utcnow()
    await db.commit()
    return {"status": "acknowledged", "alert_code": alert_id}


@router.patch("/{alert_id}/resolve")
async def resolve_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.alert_code == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status     = AlertStatus.RESOLVED
    alert.resolved_at= datetime.utcnow()
    await db.commit()
    return {"status": "resolved"}

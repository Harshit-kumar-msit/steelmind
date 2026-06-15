"""
Module: api/routes/equipment.py
Purpose: Equipment registry CRUD + health summary endpoints.
         These are the most-queried endpoints — every dashboard load hits them.
Inputs:  Query params for filtering, equipment_id path param, JSON body for create/update
Outputs: Equipment list, individual equipment health detail, plant-wide summary
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from loguru import logger

from app.db.session import get_db
from app.db.models import Equipment, HealthSnapshot, Alert, AlertStatus
from app.db.schemas import EquipmentResponse, EquipmentCreate, EquipmentHealthDetail
from app.ai.anomaly.detector import get_detector
from app.ai.prediction.rul_estimator import get_estimator
from app.ai.decision.scoring import get_decision_engine, SparePartsContext, ProductionContext
from app.services.influx_service import get_influx_service

router = APIRouter()


@router.get("/", response_model=list[dict])
async def list_equipment(
    area: Optional[str]        = Query(None, description="Filter by plant area code"),
    criticality: Optional[str] = Query(None, description="Filter by criticality A/B/C"),
    status: Optional[str]      = Query(None, description="Filter by status"),
    limit: int                 = Query(50, le=200),
    db: AsyncSession           = Depends(get_db),
):
    """
    List all equipment with their current health metrics.
    This is the primary data source for the Equipment Health dashboard page.
    Returns equipment sorted by priority_score descending (highest risk first).
    """
    query = select(Equipment).where(Equipment.is_active == True)
    if area:
        query = query.where(Equipment.plant_area_code == area)
    if criticality:
        query = query.where(Equipment.criticality == criticality)
    if status:
        query = query.where(Equipment.status == status)

    query = query.order_by(Equipment.current_priority_score.desc().nullslast()).limit(limit)
    result = await db.execute(query)
    equipment_list = result.scalars().all()

    return [
        {
            "equipment_id":        eq.equipment_id,
            "name":                eq.name,
            "plant_area_code":     eq.plant_area_code,
            "equipment_type":      eq.equipment_type,
            "criticality":         eq.criticality,
            "status":              eq.status,
            "rul_days":            eq.current_rul_days,
            "degradation_index":   eq.current_degradation_index,
            "anomaly_score":       eq.current_anomaly_score,
            "priority_score":      eq.current_priority_score,
            "last_health_update":  eq.last_health_update.isoformat() if eq.last_health_update else None,
            "maintenance_interval_days": eq.maintenance_interval_days,
            "last_maintenance_date":     eq.last_maintenance_date.isoformat() if eq.last_maintenance_date else None,
        }
        for eq in equipment_list
    ]


@router.get("/summary")
async def plant_summary(db: AsyncSession = Depends(get_db)):
    """
    Plant-wide health summary card data.
    Powers the 4 metric cards at the top of the dashboard.
    """
    result = await db.execute(
        select(Equipment).where(Equipment.is_active == True)
    )
    all_eq = result.scalars().all()

    total   = len(all_eq)
    healthy = sum(1 for e in all_eq if (e.current_priority_score or 0) < 40)
    warning = sum(1 for e in all_eq if 40 <= (e.current_priority_score or 0) < 60)
    urgent  = sum(1 for e in all_eq if 60 <= (e.current_priority_score or 0) < 80)
    critical= sum(1 for e in all_eq if (e.current_priority_score or 0) >= 80)

    # Get open alerts count
    alerts_result = await db.execute(
        select(Alert).where(Alert.status == AlertStatus.OPEN)
    )
    open_alerts = alerts_result.scalars().all()
    critical_alerts = sum(1 for a in open_alerts if a.severity == "critical")

    # Average RUL of critical equipment
    critical_eq = [e for e in all_eq if e.criticality == "A" and e.current_rul_days]
    avg_rul = sum(e.current_rul_days for e in critical_eq) / len(critical_eq) if critical_eq else 999

    return {
        "total_equipment":      total,
        "healthy":              healthy,
        "warning":              warning,
        "urgent":               urgent,
        "critical":             critical,
        "open_alerts":          len(open_alerts),
        "critical_alerts":      critical_alerts,
        "avg_rul_critical_days": round(avg_rul, 0),
        "last_updated":         datetime.utcnow().isoformat(),
    }


@router.get("/{equipment_id}", response_model=dict)
async def get_equipment_detail(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Full health detail for a single equipment.
    Powers the equipment detail modal/drawer in the UI.
    Includes sensor snapshot, AI scores, factor breakdown, and open alerts.
    """
    result = await db.execute(
        select(Equipment).where(Equipment.equipment_id == equipment_id)
    )
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=404, detail=f"Equipment {equipment_id} not found")

    # Get open alerts for this equipment
    alert_result = await db.execute(
        select(Alert).where(
            and_(Alert.equipment_id == equipment_id, Alert.status == AlertStatus.OPEN)
        )
    )
    open_alerts = alert_result.scalars().all()

    # Get last 10 health snapshots for sparkline
    snapshot_result = await db.execute(
        select(HealthSnapshot)
        .where(HealthSnapshot.equipment_id == equipment_id)
        .order_by(HealthSnapshot.snapshot_at.desc())
        .limit(24)
    )
    snapshots = snapshot_result.scalars().all()

    return {
        "equipment_id":           eq.equipment_id,
        "name":                   eq.name,
        "plant_area_code":        eq.plant_area_code,
        "equipment_type":         eq.equipment_type,
        "criticality":            eq.criticality,
        "status":                 eq.status,
        "manufacturer":           eq.manufacturer,
        "model_number":           eq.model_number,
        "rated_power_kw":         eq.rated_power_kw,
        "rated_speed_rpm":        eq.rated_speed_rpm,
        "install_date":           eq.install_date.isoformat() if eq.install_date else None,
        "last_maintenance_date":  eq.last_maintenance_date.isoformat() if eq.last_maintenance_date else None,
        "maintenance_interval_days": eq.maintenance_interval_days,
        # Health metrics
        "rul_days":               eq.current_rul_days,
        "degradation_index":      eq.current_degradation_index,
        "anomaly_score":          eq.current_anomaly_score,
        "priority_score":         eq.current_priority_score,
        "last_health_update":     eq.last_health_update.isoformat() if eq.last_health_update else None,
        "sensor_config":          eq.sensor_config,
        # Alerts
        "open_alerts":            [
            {
                "id":          str(a.id),
                "alert_code":  a.alert_code,
                "severity":    a.severity,
                "title":       a.title,
                "created_at":  a.created_at.isoformat(),
            }
            for a in open_alerts
        ],
        # Sparkline data (last 24 snapshots)
        "health_history":         [
            {
                "timestamp":         s.snapshot_at.isoformat(),
                "anomaly_score":     s.anomaly_score,
                "degradation_index": s.degradation_index,
                "rul_days":          s.rul_days,
                "priority_score":    s.priority_score,
            }
            for s in reversed(snapshots)
        ],
        "notes": eq.notes,
    }


@router.post("/", response_model=dict, status_code=201)
async def create_equipment(
    body: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new equipment in the system."""
    eq = Equipment(
        equipment_id=body.equipment_id,
        name=body.name,
        plant_area_code=body.plant_area_code,
        equipment_type=body.equipment_type,
        criticality=body.criticality,
        manufacturer=body.manufacturer,
        rated_power_kw=body.rated_power_kw,
        rated_speed_rpm=body.rated_speed_rpm,
        maintenance_interval_days=body.maintenance_interval_days,
        rul_days_baseline=body.rul_days_baseline,
        sensor_config=body.sensor_config,
    )
    db.add(eq)
    await db.commit()
    await db.refresh(eq)
    return {"equipment_id": eq.equipment_id, "status": "created"}


@router.post("/{equipment_id}/refresh-health")
async def refresh_equipment_health(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger health recalculation for an equipment.
    Pulls latest sensor data from InfluxDB, runs anomaly + RUL + priority scoring,
    and updates the equipment row and health_snapshots table.
    """
    result = await db.execute(
        select(Equipment).where(Equipment.equipment_id == equipment_id)
    )
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(status_code=404, detail="Equipment not found")

    # Pull last 60 minutes of sensor data
    influx = get_influx_service()
    df = await influx.query_equipment_sensors(equipment_id, hours=1)

    if df.empty:
        return {"status": "no_data", "message": "No sensor readings in last 1 hour"}

    latest = df.iloc[-1].to_dict()

    # Run anomaly detection
    detector = get_detector()
    anomaly_result = detector.score(
        equipment_id=equipment_id,
        equipment_type=eq.equipment_type,
        reading=latest,
        window_df=df,
    )

    # Run RUL estimation
    estimator = get_estimator()
    days_since_maint = 0
    if eq.last_maintenance_date:
        days_since_maint = (datetime.utcnow() - eq.last_maintenance_date).days

    rul_result = estimator.estimate(
        equipment_id=equipment_id,
        equipment_type=eq.equipment_type,
        df=df,
        baseline_rul_days=eq.rul_days_baseline,
        degradation_rate_k=eq.degradation_rate_k,
        last_maintenance_days_ago=days_since_maint,
    )

    # Run priority scoring
    engine = get_decision_engine()
    priority_result = engine.score(
        equipment_id=equipment_id,
        equipment_name=eq.name,
        criticality=eq.criticality,
        last_maintenance_date=eq.last_maintenance_date,
        maintenance_interval_days=eq.maintenance_interval_days,
        anomaly=anomaly_result,
        rul=rul_result,
        production=ProductionContext(downtime_cost_per_hour_usd=500_000),
    )

    # Update equipment row
    now = datetime.utcnow()
    await db.execute(
        update(Equipment)
        .where(Equipment.equipment_id == equipment_id)
        .values(
            current_rul_days=rul_result.rul_days,
            current_degradation_index=rul_result.degradation_index,
            current_anomaly_score=anomaly_result.anomaly_score,
            current_priority_score=priority_result.priority_score,
            status=_priority_to_status(priority_result.priority_score),
            last_health_update=now,
        )
    )

    # Save health snapshot
    snapshot = HealthSnapshot(
        equipment_id=equipment_id,
        snapshot_at=now,
        degradation_index=rul_result.degradation_index,
        rul_days=rul_result.rul_days,
        anomaly_score=anomaly_result.anomaly_score,
        priority_score=priority_result.priority_score,
        sensor_summary=latest,
        top_contributor=anomaly_result.top_contributor,
    )
    db.add(snapshot)
    await db.commit()

    return {
        "status":           "updated",
        "equipment_id":     equipment_id,
        "anomaly_score":    anomaly_result.anomaly_score,
        "rul_days":         rul_result.rul_days,
        "priority_score":   priority_result.priority_score,
        "recommended_action": priority_result.recommended_action,
    }


def _priority_to_status(score: float) -> str:
    if score >= 80: return "critical"
    if score >= 60: return "warning"
    if score >= 40: return "degraded"
    return "operational"

"""
Module: services/worker.py
Purpose: Background task loop. Every 30 seconds, pull latest sensor data
         for all active equipment, run anomaly detection + RUL + scoring,
         update PostgreSQL, and fire alerts if thresholds breached.
Inputs:  InfluxDB sensor data, PostgreSQL equipment records
Outputs: Updated equipment health metrics, new Alert rows, published Redis events
Production: Replace with Celery + Redis for reliable task processing.
            Add dead-letter queue for failed scoring tasks.
            Use APScheduler for precise interval control across worker instances.
"""
import asyncio
from datetime import datetime
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.db.models import Equipment, HealthSnapshot, Alert, AlertSeverity, AlertStatus
from app.ai.anomaly.detector import get_detector
from app.ai.prediction.rul_estimator import get_estimator
from app.ai.decision.scoring import get_decision_engine, ProductionContext
from app.services.influx_service import get_influx_service
from app.core.config import settings


SCAN_INTERVAL_SECONDS = 30
HEALTH_SNAPSHOT_INTERVAL = 20   # Every 20 scans (= every 10 minutes), save snapshot
FEEDBACK_JOB_INTERVAL = 2880    # Every 2880 scans (= every 24 hours at 30s intervals)


async def start_background_tasks():
    """Entry point called from lifespan."""
    logger.info("Background worker starting...")
    scan_count = 0
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await run_health_scan(db, save_snapshot=(scan_count % HEALTH_SNAPSHOT_INTERVAL == 0))
                # Run feedback improvement job daily
                if scan_count > 0 and scan_count % FEEDBACK_JOB_INTERVAL == 0:
                    from app.api.routes.feedback import run_feedback_improvement_job
                    await run_feedback_improvement_job(db)
            scan_count += 1
        except asyncio.CancelledError:
            logger.info("Background worker cancelled")
            break
        except Exception as e:
            logger.error(f"Background worker error: {e}")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


async def run_health_scan(db: AsyncSession, save_snapshot: bool = False):
    """
    Scan all active equipment:
    1. Pull latest sensor data from InfluxDB
    2. Run anomaly detection
    3. Run RUL estimation
    4. Compute priority score
    5. Update equipment table
    6. Fire alerts if needed
    7. Optionally save health snapshot
    """
    result = await db.execute(
        select(Equipment).where(Equipment.is_active == True)
    )
    equipment_list = result.scalars().all()

    influx   = get_influx_service()
    detector = get_detector()
    estimator= get_estimator()
    engine   = get_decision_engine()

    for eq in equipment_list:
        try:
            # ── Pull sensor data ──
            df = await influx.query_equipment_sensors(eq.equipment_id, hours=1)
            if df.empty:
                continue

            latest = df.iloc[-1].to_dict()

            # ── Anomaly detection ──
            anomaly = detector.score(
                equipment_id=eq.equipment_id,
                equipment_type=eq.equipment_type,
                reading=latest,
                window_df=df,
            )

            # ── RUL estimation ──
            days_since_maint = 0
            if eq.last_maintenance_date:
                days_since_maint = (datetime.utcnow() - eq.last_maintenance_date).days

            rul = estimator.estimate(
                equipment_id=eq.equipment_id,
                equipment_type=eq.equipment_type,
                df=df,
                baseline_rul_days=eq.rul_days_baseline,
                degradation_rate_k=eq.degradation_rate_k,
                last_maintenance_days_ago=days_since_maint,
            )

            # ── Priority scoring ──
            priority = engine.score(
                equipment_id=eq.equipment_id,
                equipment_name=eq.name,
                criticality=eq.criticality,
                last_maintenance_date=eq.last_maintenance_date,
                maintenance_interval_days=eq.maintenance_interval_days,
                anomaly=anomaly,
                rul=rul,
                production=ProductionContext(downtime_cost_per_hour_usd=500_000),
            )

            # ── Update equipment row ──
            new_status = _score_to_status(priority.priority_score)
            now = datetime.utcnow()
            await db.execute(
                update(Equipment)
                .where(Equipment.equipment_id == eq.equipment_id)
                .values(
                    current_anomaly_score=anomaly.anomaly_score,
                    current_degradation_index=rul.degradation_index,
                    current_rul_days=rul.rul_days,
                    current_priority_score=priority.priority_score,
                    status=new_status,
                    last_health_update=now,
                )
            )

            # ── Save health snapshot (periodic) ──
            if save_snapshot:
                snapshot = HealthSnapshot(
                    equipment_id=eq.equipment_id,
                    snapshot_at=now,
                    degradation_index=rul.degradation_index,
                    rul_days=rul.rul_days,
                    anomaly_score=anomaly.anomaly_score,
                    priority_score=priority.priority_score,
                    sensor_summary={k: round(float(v), 3) for k, v in latest.items()
                                    if isinstance(v, (int, float))},
                    top_contributor=anomaly.top_contributor,
                )
                db.add(snapshot)

            # ── Fire alerts if thresholds breached ──
            await _check_and_fire_alerts(db, eq, anomaly, rul)

        except Exception as e:
            logger.error(f"Health scan failed for {eq.equipment_id}: {e}")
            continue

    await db.commit()
    logger.debug(f"Health scan complete | {len(equipment_list)} equipment processed")


async def _check_and_fire_alerts(db, eq, anomaly, rul):
    """
    Create Alert rows when thresholds are breached.
    Deduplicates: does not create a new alert if an open alert of the same type
    already exists for this equipment.
    """
    # Check existing open alerts for this equipment
    existing = await db.execute(
        select(Alert).where(
            Alert.equipment_id == eq.equipment_id,
            Alert.status == AlertStatus.OPEN,
        )
    )
    open_alert_types = {a.alert_type for a in existing.scalars().all()}

    alerts_to_create = []

    # ── Anomaly alert ──
    if anomaly.is_anomaly and "anomaly" not in open_alert_types:
        severity = (AlertSeverity.CRITICAL if anomaly.severity == "critical"
                    else AlertSeverity.WARNING)
        alerts_to_create.append(Alert(
            alert_code=f"ALT-{eq.equipment_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            equipment_id=eq.equipment_id,
            severity=severity,
            status=AlertStatus.OPEN,
            alert_type="anomaly",
            title=f"Anomaly detected on {eq.name}",
            description=(
                f"Anomaly score {anomaly.anomaly_score:.0f}/100 — "
                f"primary contributor: {anomaly.top_contributor}. "
                f"Severity: {anomaly.severity.upper()}."
            ),
            sensor_name=anomaly.top_contributor,
            sensor_value=anomaly.sensor_values.get(anomaly.top_contributor),
            anomaly_score=anomaly.anomaly_score,
            rul_days=rul.rul_days,
            raw_context={
                "contributions": anomaly.contributions,
                "z_scores":      anomaly.z_scores,
                "sensor_values": anomaly.sensor_values,
            },
        ))

    # ── RUL alert ──
    if rul.rul_days < settings.rul_critical_days and "rul_critical" not in open_alert_types:
        alerts_to_create.append(Alert(
            alert_code=f"RUL-{eq.equipment_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            equipment_id=eq.equipment_id,
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.OPEN,
            alert_type="rul_critical",
            title=f"Critical RUL: {eq.name} — {rul.rul_days:.0f} days remaining",
            description=(
                f"Estimated Remaining Useful Life is {rul.rul_days:.0f} days "
                f"(below {settings.rul_critical_days}-day critical threshold). "
                f"Degradation index: {rul.degradation_index:.0f}/100. "
                f"Schedule emergency maintenance immediately."
            ),
            rul_days=rul.rul_days,
            anomaly_score=anomaly.anomaly_score,
        ))
    elif rul.rul_days < settings.rul_warning_days and "rul_warning" not in open_alert_types:
        alerts_to_create.append(Alert(
            alert_code=f"RULW-{eq.equipment_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            equipment_id=eq.equipment_id,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.OPEN,
            alert_type="rul_warning",
            title=f"RUL Warning: {eq.name} — {rul.rul_days:.0f} days remaining",
            description=(
                f"Estimated RUL is {rul.rul_days:.0f} days (below {settings.rul_warning_days}-day warning). "
                f"Plan maintenance within the next {int(rul.rul_days * 0.7)} days."
            ),
            rul_days=rul.rul_days,
            anomaly_score=anomaly.anomaly_score,
        ))

    for alert in alerts_to_create:
        db.add(alert)
        logger.warning(f"🚨 Alert created: {alert.alert_code} | {alert.title}")


def _score_to_status(score: float) -> str:
    if score >= 80: return "critical"
    if score >= 60: return "warning"
    if score >= 40: return "degraded"
    return "operational"

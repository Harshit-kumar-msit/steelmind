"""
Module: api/routes/anomaly.py
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import Equipment
from app.ai.anomaly.detector import get_detector
from app.services.influx_service import get_influx_service

router = APIRouter()


@router.get("/{equipment_id}/score")
async def get_anomaly_score(equipment_id: str, db: AsyncSession = Depends(get_db)):
    """Run live anomaly scoring for an equipment using latest sensor data."""
    result = await db.execute(select(Equipment).where(Equipment.equipment_id == equipment_id))
    eq = result.scalar_one_or_none()
    if not eq:
        raise HTTPException(404, "Equipment not found")

    influx = get_influx_service()
    df = await influx.query_equipment_sensors(equipment_id, hours=1)
    if df.empty:
        return {"equipment_id": equipment_id, "anomaly_score": 0, "status": "no_data"}

    detector = get_detector()
    r = detector.score(equipment_id, eq.equipment_type, df.iloc[-1].to_dict(), df)
    return {
        "equipment_id":   equipment_id,
        "anomaly_score":  r.anomaly_score,
        "is_anomaly":     r.is_anomaly,
        "severity":       r.severity,
        "top_contributor":r.top_contributor,
        "contributions":  r.contributions,
        "z_scores":       r.z_scores,
        "sensor_values":  r.sensor_values,
    }


@router.post("/train/{equipment_type}")
async def train_model(equipment_type: str, db: AsyncSession = Depends(get_db)):
    """
    Trigger model retraining for an equipment type.
    Pulls 30 days of InfluxDB data and retrains Isolation Forest.
    """
    from sqlalchemy import and_
    result = await db.execute(
        select(Equipment).where(Equipment.equipment_type == equipment_type, Equipment.is_active == True)
    )
    equipment_list = result.scalars().all()
    if not equipment_list:
        raise HTTPException(404, f"No active equipment of type {equipment_type}")

    influx   = get_influx_service()
    detector = get_detector()

    import pandas as pd
    all_dfs = []
    for eq in equipment_list[:5]:  # Limit to 5 machines for training
        df = await influx.query_equipment_sensors(eq.equipment_id, hours=720)
        if not df.empty:
            all_dfs.append(df)

    if not all_dfs:
        raise HTTPException(422, "No sensor data available for training")

    combined = pd.concat(all_dfs, ignore_index=True)
    result_summary = detector.train(equipment_type, combined)
    return {"status": "trained", **result_summary}

"""
Module: api/routes/sensors.py
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from app.services.influx_service import get_influx_service

router = APIRouter()


@router.get("/{equipment_id}/history")
async def get_sensor_history(
    equipment_id: str,
    field:  str = Query(...,  description="Sensor field name, e.g. vibration_rms_mm_s"),
    hours:  int = Query(24,   description="Hours of history to return", le=720),
    bucket: int = Query(10,   description="Aggregation bucket in minutes"),
):
    """
    Return time-series data for a single sensor field.
    Used by the SensorTimeSeries chart component.
    Returns: [{time, value}]
    """
    influx = get_influx_service()
    records = await influx.query_field(equipment_id, field, hours=hours, bucket_minutes=bucket)
    if records is None:
        raise HTTPException(503, "InfluxDB unavailable")
    return {
        "equipment_id": equipment_id,
        "field":        field,
        "hours":        hours,
        "records":      records,
    }


@router.get("/{equipment_id}/snapshot")
async def get_sensor_snapshot(equipment_id: str):
    """
    Return the most recent reading for all sensors of an equipment.
    Used by the Copilot context loader and the detail panel.
    """
    influx = get_influx_service()
    snapshot = await influx.get_latest_snapshot(equipment_id)
    return {"equipment_id": equipment_id, "snapshot": snapshot}


@router.get("/{equipment_id}/anomaly-chart")
async def get_anomaly_chart_data(
    equipment_id: str,
    hours: int = Query(72, le=720),
):
    """
    Return pre-computed anomaly scores over time for the anomaly chart.
    Each point: {time, anomaly_score, is_anomaly}.
    """
    influx = get_influx_service()
    records = await influx.query_field(
        equipment_id, "anomaly_score", hours=hours, bucket_minutes=30
    )
    return {"equipment_id": equipment_id, "anomaly_trend": records}

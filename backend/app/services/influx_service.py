"""
Module: services/influx_service.py
Purpose: All InfluxDB interactions — write sensor readings, query time-series,
         get latest snapshots. Isolates InfluxDB from the rest of the app.
Inputs:  equipment_id, field names, time range
Outputs: pandas DataFrames, dicts of latest readings, list of chart records
Production: Add connection pooling. Use InfluxDB tasks (server-side
            downsampling) for long-range queries to avoid client-side load.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from loguru import logger

from app.core.config import settings


class InfluxService:

    def __init__(self):
        self._client = InfluxDBClient(
            url=settings.influx_url,
            token=settings.influx_token,
            org=settings.influx_org,
        )
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self._query_api = self._client.query_api()
        self._bucket    = settings.influx_bucket
        self._org       = settings.influx_org

    def write_reading(self, equipment_id: str, reading: dict, timestamp: datetime = None):
        """
        Write a sensor reading to InfluxDB.
        reading: {sensor_name: value, ...}
        """
        from influxdb_client import Point
        ts = timestamp or datetime.utcnow()
        point = Point("sensor_reading").tag("equipment_id", equipment_id).time(ts)
        for field, value in reading.items():
            if isinstance(value, (int, float)) and field != "timestamp":
                point = point.field(field, float(value))
        try:
            self._write_api.write(bucket=self._bucket, record=point)
        except Exception as e:
            logger.error(f"InfluxDB write error: {e}")

    def write_dataframe(self, equipment_id: str, df: pd.DataFrame):
        """Bulk write a DataFrame to InfluxDB (for seeding synthetic data)."""
        from influxdb_client import Point
        points = []
        sensor_cols = [c for c in df.columns if c not in ("timestamp", "equipment_id")]
        for _, row in df.iterrows():
            ts = row.get("timestamp", datetime.utcnow())
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            point = Point("sensor_reading").tag("equipment_id", equipment_id).time(ts)
            for col in sensor_cols:
                val = row.get(col)
                if val is not None and pd.notna(val):
                    point = point.field(col, float(val))
            points.append(point)
        try:
            self._write_api.write(bucket=self._bucket, record=points)
            logger.info(f"Wrote {len(points)} points for {equipment_id}")
        except Exception as e:
            logger.error(f"InfluxDB bulk write error: {e}")

    async def query_equipment_sensors(
        self, equipment_id: str, hours: int = 1
    ) -> pd.DataFrame:
        """
        Query all sensor fields for an equipment over the last N hours.
        Returns a DataFrame with columns: timestamp, sensor1, sensor2, ...
        """
        flux_query = f"""
from(bucket: "{self._bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "sensor_reading")
  |> filter(fn: (r) => r.equipment_id == "{equipment_id}")
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
        try:
            loop = asyncio.get_event_loop()
            tables = await loop.run_in_executor(
                None, lambda: self._query_api.query_data_frame(flux_query, org=self._org)
            )
            if tables is None or (isinstance(tables, list) and len(tables) == 0):
                return pd.DataFrame()
            if isinstance(tables, list):
                df = pd.concat(tables, ignore_index=True)
            else:
                df = tables
            # Rename _time to timestamp
            if "_time" in df.columns:
                df = df.rename(columns={"_time": "timestamp"})
            # Drop InfluxDB internal columns
            drop_cols = [c for c in df.columns if c.startswith("_") or c in ("result", "table")]
            df = df.drop(columns=drop_cols, errors="ignore")
            return df
        except Exception as e:
            logger.error(f"InfluxDB query error for {equipment_id}: {e}")
            return pd.DataFrame()

    async def query_field(
        self, equipment_id: str, field: str, hours: int = 24, bucket_minutes: int = 10
    ) -> list[dict]:
        """
        Query a single field with time-bucketed mean aggregation.
        Returns [{time, value}] — suitable for charting.
        """
        flux_query = f"""
from(bucket: "{self._bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "sensor_reading")
  |> filter(fn: (r) => r.equipment_id == "{equipment_id}")
  |> filter(fn: (r) => r._field == "{field}")
  |> aggregateWindow(every: {bucket_minutes}m, fn: mean, createEmpty: false)
  |> sort(columns: ["_time"])
"""
        try:
            loop = asyncio.get_event_loop()
            tables = await loop.run_in_executor(
                None, lambda: self._query_api.query(flux_query, org=self._org)
            )
            records = []
            for table in tables:
                for record in table.records:
                    records.append({
                        "time":  record.get_time().isoformat(),
                        "value": round(record.get_value(), 4) if record.get_value() else None,
                    })
            return records
        except Exception as e:
            logger.error(f"InfluxDB field query error: {e}")
            return []

    async def get_latest_snapshot(self, equipment_id: str) -> dict:
        """Get the most recent value of all sensor fields."""
        flux_query = f"""
from(bucket: "{self._bucket}")
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "sensor_reading")
  |> filter(fn: (r) => r.equipment_id == "{equipment_id}")
  |> last()
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
"""
        try:
            loop = asyncio.get_event_loop()
            tables = await loop.run_in_executor(
                None, lambda: self._query_api.query_data_frame(flux_query, org=self._org)
            )
            if tables is None or (isinstance(tables, list) and not tables):
                return {}
            df = tables[0] if isinstance(tables, list) else tables
            drop_cols = [c for c in df.columns if c.startswith("_") or c in ("result","table","equipment_id")]
            df = df.drop(columns=drop_cols, errors="ignore")
            if df.empty:
                return {}
            return {k: round(float(v), 3) for k, v in df.iloc[-1].to_dict().items() if v is not None}
        except Exception as e:
            logger.error(f"InfluxDB snapshot error: {e}")
            return {}


_influx_instance: Optional[InfluxService] = None


def get_influx_service() -> InfluxService:
    global _influx_instance
    if _influx_instance is None:
        _influx_instance = InfluxService()
    return _influx_instance

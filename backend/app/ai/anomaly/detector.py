"""
Module: ai/anomaly/detector.py
Purpose: Detect sensor anomalies using Isolation Forest (primary) and Z-score
         (secondary/explainability). Runs on 1-hour rolling windows per equipment.
         Returns anomaly score 0-100, severity level, and per-sensor contributions.
Inputs:  DataFrame of recent sensor readings for one equipment
Outputs: AnomalyResult with score, severity, top contributor, contributions map
Implementation Steps:
  1. Load or train Isolation Forest per equipment_type
  2. Pull last N readings from InfluxDB
  3. Compute rolling statistics (mean, std) for z-score
  4. Predict anomaly score from Isolation Forest
  5. Map raw IF score (-0.5 to 0.5) to 0-100 scale
  6. Compute per-sensor z-scores as contribution weights
  7. Persist AnomalyResult to PostgreSQL + publish to Redis pub/sub
Production: Retrain models weekly on last 30 days of real sensor data.
            Keep baseline stats per shift (day/night) since steel plant
            equipment behaves differently at shift changes.
            Add CUSUM detector as a second opinion on trending anomalies.
"""
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
from loguru import logger

from app.core.config import settings


# ─── Sensor Configuration Per Equipment Type ──────────────────────────────────

EQUIPMENT_SENSOR_CONFIG = {
    "centrifugal_compressor": {
        "features": ["vibration_rms_mm_s", "bearing_temp_c", "lube_pressure_bar", "motor_current_a"],
        "weights":  [0.35,                  0.30,             0.20,                 0.15],
        "normal":   {"vibration_rms_mm_s": 2.8, "bearing_temp_c": 72, "lube_pressure_bar": 4.2, "motor_current_a": 38},
        "warning":  {"vibration_rms_mm_s": 4.5, "bearing_temp_c": 80, "lube_pressure_bar": 3.5, "motor_current_a": 44},
        "critical": {"vibration_rms_mm_s": 7.1, "bearing_temp_c": 95, "lube_pressure_bar": 3.0, "motor_current_a": 50},
    },
    "rolling_mill_drive": {
        "features": ["vibration_rms_mm_s", "bearing_temp_c", "motor_current_a", "speed_rpm"],
        "weights":  [0.30,                  0.35,             0.20,               0.15],
        "normal":   {"vibration_rms_mm_s": 3.2, "bearing_temp_c": 78, "motor_current_a": 120, "speed_rpm": 750},
        "warning":  {"vibration_rms_mm_s": 5.0, "bearing_temp_c": 88, "motor_current_a": 140, "speed_rpm": 800},
        "critical": {"vibration_rms_mm_s": 7.5, "bearing_temp_c": 100,"motor_current_a": 160, "speed_rpm": 850},
    },
    "hydraulic_system": {
        "features": ["lube_pressure_bar", "outlet_temp_c", "motor_current_a", "vibration_rms_mm_s"],
        "weights":  [0.40,                0.30,             0.20,               0.10],
        "normal":   {"lube_pressure_bar": 180, "outlet_temp_c": 45, "motor_current_a": 22, "vibration_rms_mm_s": 1.5},
        "warning":  {"lube_pressure_bar": 160, "outlet_temp_c": 55, "motor_current_a": 28, "vibration_rms_mm_s": 3.0},
        "critical": {"lube_pressure_bar": 140, "outlet_temp_c": 65, "motor_current_a": 35, "vibration_rms_mm_s": 5.0},
    },
    "default": {
        "features": ["vibration_rms_mm_s", "bearing_temp_c", "motor_current_a"],
        "weights":  [0.40,                  0.35,             0.25],
        "normal":   {"vibration_rms_mm_s": 3.0, "bearing_temp_c": 75, "motor_current_a": 40},
        "warning":  {"vibration_rms_mm_s": 5.0, "bearing_temp_c": 85, "motor_current_a": 48},
        "critical": {"vibration_rms_mm_s": 7.5, "bearing_temp_c": 98, "motor_current_a": 56},
    },
}


@dataclass
class AnomalyResult:
    equipment_id: str
    equipment_type: str
    timestamp: datetime
    anomaly_score: float          # 0-100
    is_anomaly: bool
    severity: str                 # normal | warning | critical
    top_contributor: str
    contributions: dict[str, float]
    raw_if_score: float = 0.0
    z_scores: dict[str, float] = field(default_factory=dict)
    sensor_values: dict[str, float] = field(default_factory=dict)
    baseline_means: dict[str, float] = field(default_factory=dict)
    model_trained_on: int = 0     # number of samples model was trained on


class AnomalyDetector:
    """
    Per-equipment anomaly detector.
    Trains one Isolation Forest model per equipment_type (shared across
    similar equipment). Falls back to pure Z-score if insufficient data.

    Model storage: backend/app/ai/anomaly/models/{equipment_type}_if.joblib
                   backend/app/ai/anomaly/models/{equipment_type}_scaler.joblib

    Usage:
        detector = AnomalyDetector()
        detector.train(equipment_type="centrifugal_compressor", df=historical_df)
        result = detector.score(equipment_id="EQ-BF-001",
                                equipment_type="centrifugal_compressor",
                                reading={"vibration_rms_mm_s": 6.8, ...})
    """

    MODEL_DIR = Path(__file__).parent / "models"

    def __init__(self):
        self.MODEL_DIR.mkdir(exist_ok=True)
        self._models: dict[str, IsolationForest] = {}
        self._scalers: dict[str, StandardScaler] = {}
        self._training_counts: dict[str, int] = {}
        self._load_all_models()

    # ─── Training ─────────────────────────────────────────────────────────────

    def train(
        self,
        equipment_type: str,
        df: pd.DataFrame,
        contamination: float = 0.05,
    ) -> dict:
        """
        Train Isolation Forest on historical sensor data.
        Expects df to contain the sensor columns for the given equipment_type.
        Only uses 'normal' period data for training (contamination=0.05 handles
        the small fraction of anomalies that may sneak into training data).

        Args:
            equipment_type: Key into EQUIPMENT_SENSOR_CONFIG
            df:             DataFrame with sensor columns
            contamination:  Expected fraction of anomalies in training data

        Returns:
            dict with training summary
        """
        config = EQUIPMENT_SENSOR_CONFIG.get(equipment_type, EQUIPMENT_SENSOR_CONFIG["default"])
        features = [f for f in config["features"] if f in df.columns]

        if len(features) < 2:
            raise ValueError(f"Not enough sensor columns in df. Expected: {config['features']}, got: {list(df.columns)}")

        X = df[features].dropna()
        if len(X) < 100:
            logger.warning(f"Only {len(X)} samples for training {equipment_type} — results may be unreliable")

        # Scale features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Train Isolation Forest
        model = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_scaled)

        # Persist
        joblib.dump(model,  self.MODEL_DIR / f"{equipment_type}_if.joblib")
        joblib.dump(scaler, self.MODEL_DIR / f"{equipment_type}_scaler.joblib")

        self._models[equipment_type]  = model
        self._scalers[equipment_type] = scaler
        self._training_counts[equipment_type] = len(X)

        logger.info(f"Trained IF model: equipment_type={equipment_type} | samples={len(X)}")
        return {
            "equipment_type": equipment_type,
            "samples": len(X),
            "features": features,
            "contamination": contamination,
        }

    # ─── Scoring ──────────────────────────────────────────────────────────────

    def score(
        self,
        equipment_id: str,
        equipment_type: str,
        reading: dict,
        window_df: Optional[pd.DataFrame] = None,
    ) -> AnomalyResult:
        """
        Score a single sensor reading.

        Args:
            equipment_id:   Equipment identifier (for result labelling)
            equipment_type: Used to select the right model and config
            reading:        Dict of sensor_name → value for the current timestamp
            window_df:      Optional recent window for z-score baselines

        Returns:
            AnomalyResult with full explainability breakdown
        """
        config = EQUIPMENT_SENSOR_CONFIG.get(equipment_type, EQUIPMENT_SENSOR_CONFIG["default"])
        features = config["features"]
        weights = config["weights"]
        timestamp = datetime.utcnow()

        # Extract available features from reading
        sensor_values = {}
        for f in features:
            val = reading.get(f)
            if val is not None:
                sensor_values[f] = float(val)

        if not sensor_values:
            return self._zero_result(equipment_id, equipment_type, timestamp)

        # ── Method 1: Isolation Forest score ──
        if_score_normalized, raw_if_score = self._isolation_forest_score(
            equipment_type, sensor_values, features
        )

        # ── Method 2: Z-score contributions ──
        z_scores, contributions = self._zscore_contributions(
            sensor_values, features, weights, config, window_df
        )

        # ── Combine: IF provides the global score, z-scores provide per-sensor explanation ──
        # If IF model is not available, fall back to z-score only
        if if_score_normalized is not None:
            # Blend: 70% IF model, 30% z-score aggregate
            zscore_agg = sum(contributions[f] for f in contributions)
            anomaly_score = round(0.70 * if_score_normalized + 0.30 * min(zscore_agg * 10, 100), 1)
        else:
            # Pure z-score fallback
            anomaly_score = round(min(sum(contributions[f] for f in contributions) * 10, 100), 1)

        anomaly_score = max(0.0, min(100.0, anomaly_score))
        is_anomaly = anomaly_score >= settings.anomaly_warning_threshold

        # ── Severity ──
        if anomaly_score >= settings.anomaly_critical_threshold:
            severity = "critical"
        elif anomaly_score >= settings.anomaly_warning_threshold:
            severity = "warning"
        else:
            severity = "normal"

        # ── Top contributor ──
        top_contributor = max(contributions, key=contributions.get) if contributions else "unknown"

        # ── Baseline means from config ──
        baseline_means = config["normal"]

        return AnomalyResult(
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            timestamp=timestamp,
            anomaly_score=anomaly_score,
            is_anomaly=is_anomaly,
            severity=severity,
            top_contributor=top_contributor,
            contributions=contributions,
            raw_if_score=raw_if_score or 0.0,
            z_scores=z_scores,
            sensor_values=sensor_values,
            baseline_means={k: v for k, v in baseline_means.items() if k in sensor_values},
            model_trained_on=self._training_counts.get(equipment_type, 0),
        )

    def score_window(
        self,
        equipment_id: str,
        equipment_type: str,
        df: pd.DataFrame,
    ) -> list[AnomalyResult]:
        """Score every row in a DataFrame — for batch analysis or chart generation."""
        results = []
        for _, row in df.iterrows():
            reading = row.to_dict()
            result = self.score(equipment_id, equipment_type, reading, df)
            results.append(result)
        return results

    # ─── Private ──────────────────────────────────────────────────────────────

    def _isolation_forest_score(
        self, equipment_type: str, sensor_values: dict, features: list
    ) -> tuple[Optional[float], Optional[float]]:
        """Returns (normalized_score 0-100, raw_score)."""
        model  = self._models.get(equipment_type)
        scaler = self._scalers.get(equipment_type)
        if model is None or scaler is None:
            return None, None

        try:
            # Build feature vector in correct order
            x = np.array([[sensor_values.get(f, 0.0) for f in features]])
            x_scaled = scaler.transform(x)
            raw_score = model.score_samples(x_scaled)[0]
            # raw_score is in range [-0.5, 0.5] roughly
            # More negative = more anomalous
            # Map: -0.5 → 100 (critical), +0.5 → 0 (normal)
            normalized = float(np.clip((raw_score + 0.5) / (-1.0) * 100 + 50, 0, 100))
            # Simpler: anomaly_score = 50 - raw_score * 100 (capped 0-100)
            normalized = float(np.clip(50.0 - raw_score * 100, 0, 100))
            return normalized, raw_score
        except Exception as e:
            logger.error(f"IF scoring error: {e}")
            return None, None

    def _zscore_contributions(
        self,
        sensor_values: dict,
        features: list,
        weights: list,
        config: dict,
        window_df: Optional[pd.DataFrame],
    ) -> tuple[dict, dict]:
        """
        Compute per-sensor z-scores and weighted contributions.
        Uses window_df baselines if available, else config normal values.
        """
        z_scores = {}
        contributions = {}

        for feat, weight in zip(features, weights):
            if feat not in sensor_values:
                continue
            val = sensor_values[feat]

            # Baseline: use window statistics if available
            if window_df is not None and feat in window_df.columns and len(window_df) > 10:
                mean = float(window_df[feat].mean())
                std  = float(window_df[feat].std())
                if std < 1e-9:
                    std = abs(mean) * 0.1 or 1.0
            else:
                # Fall back to config normals — use 10% of normal as std estimate
                mean = config["normal"].get(feat, val)
                std  = abs(mean) * 0.10 or 1.0

            z = abs((val - mean) / std)
            z_scores[feat] = round(z, 3)

            # Contribution: weighted z-score, capped at 25 per sensor
            contributions[feat] = round(min(z * weight, 25.0), 3)

        return z_scores, contributions

    def _zero_result(self, equipment_id: str, equipment_type: str, ts: datetime) -> AnomalyResult:
        return AnomalyResult(
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            timestamp=ts,
            anomaly_score=0.0,
            is_anomaly=False,
            severity="normal",
            top_contributor="unknown",
            contributions={},
        )

    def _load_all_models(self):
        """Load all pre-trained models from disk on startup."""
        for path in self.MODEL_DIR.glob("*_if.joblib"):
            equipment_type = path.stem.replace("_if", "")
            try:
                self._models[equipment_type]  = joblib.load(path)
                scaler_path = self.MODEL_DIR / f"{equipment_type}_scaler.joblib"
                if scaler_path.exists():
                    self._scalers[equipment_type] = joblib.load(scaler_path)
                logger.info(f"Loaded anomaly model: {equipment_type}")
            except Exception as e:
                logger.error(f"Failed to load model {path}: {e}")


# ─── Singleton ────────────────────────────────────────────────────────────────
_detector_instance: Optional[AnomalyDetector] = None


def get_detector() -> AnomalyDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = AnomalyDetector()
    return _detector_instance

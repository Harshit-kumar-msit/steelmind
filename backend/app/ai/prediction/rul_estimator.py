"""
Module: ai/prediction/rul_estimator.py
Purpose: Estimate Remaining Useful Life (RUL) using a degradation index
         approach. Combines multi-sensor weighted scoring with exponential
         decay physics model and XGBoost for refinement.
Inputs:  Recent sensor DataFrame, equipment config, maintenance history
Outputs: RULResult with rul_days, rul_hours, degradation_index, confidence,
         per-sensor breakdown, and warning_level
Implementation Steps:
  1. Compute per-sensor health scores (0-100 scale, 0=healthy, 100=failed)
     using linear interpolation between normal and failure thresholds
  2. Compute weighted Degradation Index (DI) = Σ(score_i * weight_i)
  3. Estimate RUL using exponential decay:
     RUL = baseline_rul * exp(-k * DI/100)
  4. Refine with trend: fit linear regression on last 24h DI values
     → if DI increasing rapidly, reduce RUL estimate
  5. Apply confidence scoring based on data completeness
Production: Replace exponential decay with a physics-informed model for
            critical equipment (blast furnace blowers). Train XGBoost
            regression on historical failure events once 6 months of
            real data is available.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd
from scipy import stats
from loguru import logger

from app.ai.anomaly.detector import EQUIPMENT_SENSOR_CONFIG


@dataclass
class RULResult:
    equipment_id: str
    equipment_type: str
    computed_at: datetime
    degradation_index: float      # 0-100
    rul_days: float
    rul_hours: float
    confidence: str               # low | medium | high
    warning_level: str            # normal | warning | critical
    sensor_contributions: dict    # {sensor: {"score": x, "weight": y, "value": z, "threshold": t}}
    trend_slope: float = 0.0      # DI change per hour (positive = degrading)
    trend_days_to_failure: Optional[float] = None  # Linear extrapolation
    data_points_used: int = 0
    notes: list[str] = field(default_factory=list)


class RULEstimator:
    """
    Remaining Useful Life estimator.

    The degradation index (DI) maps each sensor to a 0-100 score:
    - 0 = reading at normal/healthy level
    - 100 = reading at failure threshold

    RUL = baseline_rul_days × exp(−k × DI/100)
    Where k is the equipment-specific degradation rate constant.

    This is a practical approximation. In reality, degradation is not
    purely exponential — it accelerates near failure. The exponential model
    is conservative (predicts shorter RUL than linear), which is the
    safe direction for maintenance planning.

    Usage:
        estimator = RULEstimator()
        result = estimator.estimate(
            equipment_id="EQ-BF-001",
            equipment_type="centrifugal_compressor",
            df=last_24h_readings,
            baseline_rul_days=180,
            degradation_rate_k=0.035,
        )
    """

    def estimate(
        self,
        equipment_id: str,
        equipment_type: str,
        df: pd.DataFrame,
        baseline_rul_days: int = 180,
        degradation_rate_k: float = 0.035,
        last_maintenance_days_ago: int = 0,
    ) -> RULResult:
        """
        Estimate RUL from a DataFrame of recent sensor readings.

        Args:
            equipment_id:           Equipment identifier
            equipment_type:         Type key into EQUIPMENT_SENSOR_CONFIG
            df:                     DataFrame with sensor columns; index or
                                    'timestamp' column for trend analysis
            baseline_rul_days:      Expected life from fresh/maintained state
            degradation_rate_k:     Decay constant; higher k = faster degradation
                                    Typical range: 0.02 (slow) to 0.08 (fast)
            last_maintenance_days_ago: Days since last PM; adds context

        Returns:
            RULResult with full breakdown
        """
        timestamp = datetime.utcnow()
        config = EQUIPMENT_SENSOR_CONFIG.get(equipment_type, EQUIPMENT_SENSOR_CONFIG["default"])
        features = config["features"]
        weights  = config["weights"]

        # ── Use the most recent reading for current DI ──
        if df.empty:
            return self._minimal_result(equipment_id, equipment_type, timestamp, baseline_rul_days)

        latest = df.iloc[-1].to_dict()
        n_readings = len(df)

        # ── Step 1: Per-sensor health scores ──
        sensor_contributions = {}
        weighted_scores = []

        for feat, weight in zip(features, weights):
            val = latest.get(feat)
            if val is None:
                continue
            val = float(val)

            normal   = config["normal"].get(feat)
            critical = config["critical"].get(feat)
            warning  = config["warning"].get(feat)

            if normal is None or critical is None:
                continue

            # Handle sensors where lower = worse (e.g. lube_pressure)
            # Detect inverted sensors: critical < normal
            inverted = critical < normal
            if inverted:
                normal, critical = critical, normal   # swap so critical > normal
                val_for_score = normal + critical - val  # invert the value
            else:
                val_for_score = val

            # Linear interpolation: 0 at normal, 100 at critical
            if critical == normal:
                health_score = 0.0
            else:
                health_score = np.clip(
                    100.0 * (val_for_score - normal) / (critical - normal),
                    0.0, 100.0
                )

            weighted_score = float(health_score * weight)
            weighted_scores.append(weighted_score)

            sensor_contributions[feat] = {
                "score":     round(health_score, 1),
                "weight":    weight,
                "weighted":  round(weighted_score, 1),
                "value":     round(val, 3),
                "normal":    config["normal"].get(feat),
                "warning":   config["warning"].get(feat),
                "critical":  config["critical"].get(feat),
                "status":    self._sensor_status(health_score),
            }

        # Degradation Index = sum of weighted scores
        degradation_index = round(min(sum(weighted_scores), 100.0), 1)

        # ── Step 2: RUL estimation via exponential decay ──
        # RUL(DI) = RUL_baseline * exp(-k * DI/100)
        # At DI=0 → RUL = baseline (fresh)
        # At DI=50 → RUL ≈ baseline * 0.17
        # At DI=80 → RUL ≈ baseline * 0.06
        rul_days_raw = baseline_rul_days * np.exp(-degradation_rate_k * degradation_index)

        # ── Step 3: Trend analysis (if enough data) ──
        trend_slope = 0.0
        trend_rul = None
        notes = []

        if n_readings >= 6:
            di_series = self._compute_di_series(df, features, weights, config)
            if len(di_series) >= 6:
                # Fit linear trend to last 24 readings (or all if fewer)
                y = di_series[-24:]
                x = np.arange(len(y))
                slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
                trend_slope = round(float(slope), 4)  # DI increase per time step

                # Linear extrapolation to DI=100 (failure)
                if slope > 0.001:
                    steps_to_failure = (100.0 - y[-1]) / slope
                    # Assume each row ≈ 1 minute
                    trend_rul = steps_to_failure / (24 * 60)  # convert to days
                    if trend_rul < rul_days_raw:
                        notes.append(
                            f"Trend analysis predicts failure sooner ({trend_rul:.1f}d) "
                            f"than decay model ({rul_days_raw:.1f}d). Use trend estimate."
                        )
                        rul_days_raw = min(rul_days_raw, trend_rul)

        # ── Step 4: Maintenance history adjustment ──
        if last_maintenance_days_ago > 0:
            # Maintenance resets some degradation — add partial credit
            maint_credit = min(last_maintenance_days_ago * 0.3, 15)
            rul_days_raw = min(rul_days_raw + maint_credit, baseline_rul_days)

        rul_days = round(max(0.0, rul_days_raw), 1)
        rul_hours = round(rul_days * 24, 0)

        # ── Step 5: Confidence and warning level ──
        confidence = self._confidence(n_readings, len(sensor_contributions))
        warning_level = self._warning_level(rul_days)

        if rul_days < settings.rul_critical_days:
            notes.append(f"⚠️ CRITICAL: RUL below {settings.rul_critical_days} days!")
        elif rul_days < settings.rul_warning_days:
            notes.append(f"⚠️ WARNING: RUL below {settings.rul_warning_days} days.")

        return RULResult(
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            computed_at=timestamp,
            degradation_index=degradation_index,
            rul_days=rul_days,
            rul_hours=rul_hours,
            confidence=confidence,
            warning_level=warning_level,
            sensor_contributions=sensor_contributions,
            trend_slope=trend_slope,
            trend_days_to_failure=round(trend_rul, 1) if trend_rul else None,
            data_points_used=n_readings,
            notes=notes,
        )

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _compute_di_series(
        self, df: pd.DataFrame, features: list, weights: list, config: dict
    ) -> np.ndarray:
        """Compute DI for each row in df (for trend analysis)."""
        di_values = []
        for _, row in df.iterrows():
            scores = []
            for feat, weight in zip(features, weights):
                val = row.get(feat)
                if val is None or pd.isna(val):
                    continue
                val = float(val)
                normal   = config["normal"].get(feat, val)
                critical = config["critical"].get(feat, val)
                inverted = critical < normal
                if inverted:
                    normal, critical = critical, normal
                    val = normal + critical - val
                if critical != normal:
                    score = np.clip(100.0 * (val - normal) / (critical - normal), 0, 100)
                else:
                    score = 0.0
                scores.append(score * weight)
            di_values.append(min(sum(scores), 100.0))
        return np.array(di_values)

    def _sensor_status(self, score: float) -> str:
        if score >= 80:   return "critical"
        if score >= 50:   return "warning"
        if score >= 20:   return "elevated"
        return "normal"

    def _confidence(self, n_readings: int, n_sensors: int) -> str:
        if n_readings >= 60 and n_sensors >= 3:   return "high"
        if n_readings >= 10 and n_sensors >= 2:   return "medium"
        return "low"

    def _warning_level(self, rul_days: float) -> str:
        if rul_days < settings.rul_critical_days:   return "critical"
        if rul_days < settings.rul_warning_days:    return "warning"
        return "normal"

    def _minimal_result(
        self, eq_id: str, eq_type: str, ts: datetime, baseline: int
    ) -> RULResult:
        return RULResult(
            equipment_id=eq_id,
            equipment_type=eq_type,
            computed_at=ts,
            degradation_index=0.0,
            rul_days=float(baseline),
            rul_hours=float(baseline * 24),
            confidence="low",
            warning_level="normal",
            sensor_contributions={},
            notes=["Insufficient sensor data for estimation"],
        )


# Singleton
_estimator_instance: Optional[RULEstimator] = None


def get_estimator() -> RULEstimator:
    global _estimator_instance
    if _estimator_instance is None:
        _estimator_instance = RULEstimator()
    return _estimator_instance

"""
Module: ai/decision/scoring.py
Purpose: Compute a 0-100 Priority Score for each equipment and generate
         actionable, explainable maintenance recommendations.
         This is the core business logic that turns sensor numbers into
         maintenance decisions.
Inputs:  Equipment record, AnomalyResult, RULResult, spare parts inventory,
         production context (downtime cost, shift schedule)
Outputs: PriorityScoreResult with score, action, urgency, factor breakdown,
         parts gap list, and human-readable explanation
Implementation Steps:
  1. Normalize 6 factors to 0-1 range
  2. Apply criticality-adjusted weights
  3. Sum → priority score 0-100
  4. Map score to urgency level and recommended action
  5. Check spare parts availability
  6. Generate human-readable explanation string
Production: Add shift-aware scoring (P1 during a running campaign differs
            from P1 during a planned outage). Integrate with SAP PM to
            auto-raise work orders for P1/P2 scores.
            Run scoring every 30 minutes per equipment; store in PostgreSQL.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
from loguru import logger

from app.ai.anomaly.detector import AnomalyResult
from app.ai.prediction.rul_estimator import RULResult
from app.core.config import settings


@dataclass
class SparePartsContext:
    """Inventory snapshot for parts required by this equipment."""
    parts_on_hand: dict[str, int]        # {part_id: qty_available}
    parts_required: list[str]            # part_ids needed for repair
    lead_times: dict[str, int]           # {part_id: lead_time_days}
    unit_costs: dict[str, float]         # {part_id: cost_usd}


@dataclass
class ProductionContext:
    """Production impact data for downtime cost calculation."""
    downtime_cost_per_hour_usd: float = 500_000    # Steel plant typical
    current_production_rate_pct: float = 100.0     # % of rated capacity
    planned_outage_within_days: Optional[int] = None  # None if no planned outage
    shift_type: str = "day"                         # day | night | weekend


@dataclass
class PriorityResult:
    equipment_id: str
    equipment_name: str
    computed_at: datetime
    priority_score: float              # 0-100
    urgency: str                       # routine | monitor | urgent | immediate
    recommended_action: str
    work_order_priority: str           # P1 | P2 | P3 | P4
    factor_breakdown: dict[str, dict]  # {factor: {raw, weighted, description}}
    total_score_contribution: dict[str, float]
    spare_parts_available: bool
    spare_parts_gap: list[str]
    max_lead_time_days: int
    estimated_repair_hours: float
    explanation: str
    next_review_hours: int             # When to re-evaluate
    metadata: dict = field(default_factory=dict)


class DecisionEngine:
    """
    Maintenance Decision Support Engine.

    Priority Score Formula:
    ─────────────────────────────────────────────────────────────────────────
    Score = Σ (factor_i × weight_i) × 100

    Factor         Weight  Description
    ─────────────────────────────────────────────────────────────────────────
    criticality    0.25    Equipment class A/B/C (A=1.0, B=0.7, C=0.4)
    anomaly        0.25    Normalized anomaly score from Isolation Forest
    rul_urgency    0.20    Inverse sigmoid on RUL days (peaks at <14 days)
    downtime_risk  0.15    Downtime cost / max expected cost
    maintenance_overdue 0.10  Days overdue / PM interval
    spare_penalty  0.05    1.0 if parts missing, 0.6 if parts available

    Criticality modifier: Score × criticality_multiplier
    A: ×1.15, B: ×1.00, C: ×0.85

    Usage:
        engine = DecisionEngine()
        result = engine.score(
            equipment=equipment_row,
            anomaly=anomaly_result,
            rul=rul_result,
            parts=parts_context,
            production=prod_context,
        )
    """

    WEIGHTS = {
        "criticality":          0.25,
        "anomaly":              0.25,
        "rul_urgency":          0.20,
        "downtime_risk":        0.15,
        "maintenance_overdue":  0.10,
        "spare_penalty":        0.05,
    }

    CRITICALITY_MAP = {"A": 1.0, "B": 0.7, "C": 0.4}
    CRITICALITY_MULTIPLIER = {"A": 1.15, "B": 1.00, "C": 0.85}

    MAX_DOWNTIME_COST_USD = 2_000_000   # Normalization ceiling

    def score(
        self,
        equipment_id: str,
        equipment_name: str,
        criticality: str,
        last_maintenance_date: Optional[datetime],
        maintenance_interval_days: int,
        anomaly: AnomalyResult,
        rul: RULResult,
        parts: Optional[SparePartsContext] = None,
        production: Optional[ProductionContext] = None,
        repair_hours_estimate: float = 4.0,
    ) -> PriorityResult:
        """
        Compute priority score with full factor breakdown.

        All factor scores are on 0-1 scale before weighting.
        """
        timestamp = datetime.utcnow()
        production = production or ProductionContext()

        # ── Factor 1: Equipment Criticality ──────────────────────────────────
        f_criticality = self.CRITICALITY_MAP.get(criticality, 0.5)
        crit_desc = f"Class {criticality} equipment ({'mission critical' if criticality=='A' else 'important' if criticality=='B' else 'minor impact'})"

        # ── Factor 2: Anomaly Score ───────────────────────────────────────────
        f_anomaly = anomaly.anomaly_score / 100.0
        anomaly_desc = (
            f"Anomaly score {anomaly.anomaly_score:.0f}/100 — "
            f"top contributor: {anomaly.top_contributor} "
            f"(severity: {anomaly.severity})"
        )

        # ── Factor 3: RUL Urgency (inverse sigmoid) ───────────────────────────
        # Sigmoid centered at 14 days: f = 1 / (1 + e^(0.15*(rul-14)))
        # At 0 days: f≈1.0, at 7 days: f≈0.75, at 14 days: f≈0.5, at 30 days: f≈0.12
        rul_days = rul.rul_days
        f_rul_urgency = 1.0 / (1.0 + np.exp(0.15 * (rul_days - 14.0)))
        f_rul_urgency = float(np.clip(f_rul_urgency, 0.0, 1.0))
        rul_desc = f"RUL: {rul_days:.0f} days — {rul.warning_level} — degradation index: {rul.degradation_index:.0f}/100"

        # ── Factor 4: Downtime Risk ────────────────────────────────────────────
        hourly_cost = production.downtime_cost_per_hour_usd
        # Scale by production rate (50% production → 50% of downtime cost)
        effective_cost = hourly_cost * (production.current_production_rate_pct / 100.0)
        # Normalize to max expected cost
        f_downtime = min(effective_cost / self.MAX_DOWNTIME_COST_USD, 1.0)
        downtime_desc = (
            f"Downtime cost: USD {effective_cost:,.0f}/hr "
            f"at {production.current_production_rate_pct:.0f}% production"
        )

        # ── Factor 5: Maintenance Overdue ─────────────────────────────────────
        if last_maintenance_date:
            days_since_maint = (timestamp - last_maintenance_date).days
        else:
            days_since_maint = maintenance_interval_days  # assume overdue if unknown
        f_overdue = min(days_since_maint / max(maintenance_interval_days, 1), 1.5)
        f_overdue = float(np.clip(f_overdue, 0.0, 1.0))
        overdue_desc = (
            f"{days_since_maint} days since last maintenance "
            f"(interval: {maintenance_interval_days} days)"
        )

        # ── Factor 6: Spare Parts Penalty ─────────────────────────────────────
        spare_parts_gap = []
        max_lead_time = 0

        if parts and parts.parts_required:
            for part_id in parts.parts_required:
                qty = parts.parts_on_hand.get(part_id, 0)
                if qty == 0:
                    spare_parts_gap.append(part_id)
                    lead = parts.lead_times.get(part_id, 14)
                    max_lead_time = max(max_lead_time, lead)
        # If parts are missing, increase urgency (1.0), else small reduction (0.6)
        f_spare = 1.0 if spare_parts_gap else 0.6
        spare_desc = (
            f"Missing parts: {spare_parts_gap}" if spare_parts_gap
            else "All required parts in stock"
        )

        # ── Weighted Sum ──────────────────────────────────────────────────────
        factor_contributions = {
            "criticality":          f_criticality * self.WEIGHTS["criticality"],
            "anomaly":              f_anomaly     * self.WEIGHTS["anomaly"],
            "rul_urgency":          f_rul_urgency * self.WEIGHTS["rul_urgency"],
            "downtime_risk":        f_downtime    * self.WEIGHTS["downtime_risk"],
            "maintenance_overdue":  f_overdue     * self.WEIGHTS["maintenance_overdue"],
            "spare_penalty":        f_spare       * self.WEIGHTS["spare_penalty"],
        }
        raw_score = sum(factor_contributions.values()) * 100

        # Apply criticality multiplier
        crit_mult = self.CRITICALITY_MULTIPLIER.get(criticality, 1.0)
        priority_score = round(float(np.clip(raw_score * crit_mult, 0, 100)), 1)

        # Planned outage discount: if maintenance already planned, reduce urgency
        if production.planned_outage_within_days is not None:
            days_to_outage = production.planned_outage_within_days
            if days_to_outage <= rul_days:
                priority_score = round(priority_score * 0.75, 1)

        # ── Urgency & Action Mapping ──────────────────────────────────────────
        urgency, action, wo_priority, review_hours = self._map_urgency(
            priority_score, rul_days, anomaly.severity
        )

        # ── Full Factor Breakdown ─────────────────────────────────────────────
        factor_breakdown = {
            "criticality": {
                "raw": round(f_criticality, 3),
                "weight": self.WEIGHTS["criticality"],
                "contribution": round(factor_contributions["criticality"] * 100, 1),
                "description": crit_desc,
            },
            "anomaly_score": {
                "raw": round(f_anomaly, 3),
                "weight": self.WEIGHTS["anomaly"],
                "contribution": round(factor_contributions["anomaly"] * 100, 1),
                "description": anomaly_desc,
            },
            "rul_urgency": {
                "raw": round(f_rul_urgency, 3),
                "weight": self.WEIGHTS["rul_urgency"],
                "contribution": round(factor_contributions["rul_urgency"] * 100, 1),
                "description": rul_desc,
            },
            "downtime_risk": {
                "raw": round(f_downtime, 3),
                "weight": self.WEIGHTS["downtime_risk"],
                "contribution": round(factor_contributions["downtime_risk"] * 100, 1),
                "description": downtime_desc,
            },
            "maintenance_overdue": {
                "raw": round(f_overdue, 3),
                "weight": self.WEIGHTS["maintenance_overdue"],
                "contribution": round(factor_contributions["maintenance_overdue"] * 100, 1),
                "description": overdue_desc,
            },
            "spare_penalty": {
                "raw": round(f_spare, 3),
                "weight": self.WEIGHTS["spare_penalty"],
                "contribution": round(factor_contributions["spare_penalty"] * 100, 1),
                "description": spare_desc,
            },
        }

        # ── Human-Readable Explanation ────────────────────────────────────────
        top_factors = sorted(
            factor_contributions.items(), key=lambda x: x[1], reverse=True
        )[:3]
        top_factor_names = [f[0].replace("_", " ") for f in top_factors]

        explanation = (
            f"Priority score {priority_score}/100 ({urgency.upper()}) driven by: "
            f"{top_factor_names[0]} ({factor_breakdown[top_factors[0][0]]['description'][:60]}...), "
            f"{top_factor_names[1] if len(top_factor_names) > 1 else ''}"
            f"{'.' if spare_parts_gap else '. All critical spare parts are in stock.'}"
        )
        if spare_parts_gap:
            explanation += f" ⚠️ Missing parts: {', '.join(spare_parts_gap)} — order immediately (lead time: {max_lead_time}d)."

        return PriorityResult(
            equipment_id=equipment_id,
            equipment_name=equipment_name,
            computed_at=timestamp,
            priority_score=priority_score,
            urgency=urgency,
            recommended_action=action,
            work_order_priority=wo_priority,
            factor_breakdown=factor_breakdown,
            total_score_contribution={k: round(v * 100, 1) for k, v in factor_contributions.items()},
            spare_parts_available=len(spare_parts_gap) == 0,
            spare_parts_gap=spare_parts_gap,
            max_lead_time_days=max_lead_time,
            estimated_repair_hours=repair_hours_estimate,
            explanation=explanation,
            next_review_hours=review_hours,
        )

    def _map_urgency(
        self, score: float, rul_days: float, anomaly_severity: str
    ) -> tuple[str, str, str, int]:
        """
        Map priority score to urgency level, recommended action, WO priority,
        and next review interval.

        Returns: (urgency, action, wo_priority, review_hours)
        """
        # Override: critical anomaly or very low RUL always triggers immediate
        if anomaly_severity == "critical" or rul_days < settings.rul_critical_days:
            return (
                "immediate",
                "IMMEDIATE ACTION: Notify shift supervisor. Schedule emergency inspection within 2 hours. "
                "Prepare for potential emergency shutdown. Do NOT defer.",
                "P1",
                4,
            )

        if score >= 80:
            return (
                "immediate",
                "Emergency maintenance required within 24 hours. "
                "Raise P1 work order, assign senior technician, check spare availability NOW.",
                "P1",
                6,
            )
        elif score >= 60:
            return (
                "urgent",
                "Schedule corrective maintenance within 7 days. "
                "Raise P2 work order. Increase monitoring frequency to every 4 hours.",
                "P2",
                12,
            )
        elif score >= 40:
            return (
                "monitor",
                "Include in next planned maintenance window. "
                "Raise P3 work order. Collect oil sample and vibration spectrum this week.",
                "P3",
                24,
            )
        else:
            return (
                "routine",
                "Continue routine monitoring. No immediate action required. "
                "Review at next scheduled PM.",
                "P4",
                48,
            )


# Singleton
_engine_instance: Optional[DecisionEngine] = None


def get_decision_engine() -> DecisionEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DecisionEngine()
    return _engine_instance

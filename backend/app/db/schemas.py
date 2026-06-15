"""
Module: db/schemas.py
Purpose: Pydantic v2 schemas for all API request/response shapes.
         Keeps ORM models separate from API contracts.
         All datetime fields are ISO 8601 strings at the API boundary.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# ─── Base ─────────────────────────────────────────────────────────────────────

class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: Optional[datetime] = None


# ─── Equipment ────────────────────────────────────────────────────────────────

class EquipmentBase(BaseModel):
    equipment_id: str
    name: str
    plant_area_code: str
    equipment_type: str
    criticality: str = "B"
    manufacturer: str = ""
    rated_power_kw: Optional[float] = None
    rated_speed_rpm: Optional[float] = None
    maintenance_interval_days: int = 90
    rul_days_baseline: int = 180

class EquipmentCreate(EquipmentBase):
    sensor_config: dict = {}

class EquipmentResponse(EquipmentBase, TimestampMixin):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    current_rul_days: Optional[float] = None
    current_degradation_index: Optional[float] = None
    current_anomaly_score: Optional[float] = None
    current_priority_score: Optional[float] = None
    last_health_update: Optional[datetime] = None

class EquipmentHealthDetail(BaseModel):
    equipment_id: str
    name: str
    status: str
    criticality: str
    rul_days: Optional[float]
    degradation_index: Optional[float]
    anomaly_score: Optional[float]
    priority_score: Optional[float]
    top_contributor: str = ""
    recommended_action: str = ""
    factor_breakdown: dict = {}
    sensor_snapshot: dict = {}
    last_updated: Optional[datetime]


# ─── Sensor ───────────────────────────────────────────────────────────────────

class SensorReading(BaseModel):
    equipment_id: str
    timestamp: datetime
    vibration_rms_mm_s: Optional[float] = None
    bearing_temp_c: Optional[float] = None
    lube_pressure_bar: Optional[float] = None
    motor_current_a: Optional[float] = None
    speed_rpm: Optional[float] = None
    outlet_temp_c: Optional[float] = None
    power_kw: Optional[float] = None
    extra_fields: dict = {}

class SensorHistory(BaseModel):
    equipment_id: str
    field: str
    start: datetime
    end: datetime
    values: list[dict]   # [{time, value}]


# ─── Anomaly ──────────────────────────────────────────────────────────────────

class AnomalyResult(BaseModel):
    equipment_id: str
    timestamp: datetime
    anomaly_score: float = Field(..., ge=0, le=100)
    is_anomaly: bool
    severity: str   # normal | warning | critical
    top_contributor: str
    contributions: dict[str, float]
    raw_if_score: float = 0.0

class AnomalyRunRequest(BaseModel):
    equipment_id: str
    window_hours: int = 1


# ─── RUL & Health ─────────────────────────────────────────────────────────────

class RULResult(BaseModel):
    equipment_id: str
    computed_at: datetime
    degradation_index: float
    rul_days: float
    rul_hours: float
    confidence: str   # low | medium | high
    sensor_contributions: dict[str, tuple[float, float]]   # {sensor: (score, weight)}
    warning_level: str   # normal | warning | critical

class PriorityScoreResult(BaseModel):
    equipment_id: str
    priority_score: float
    recommended_action: str
    urgency: str   # routine | monitor | urgent | immediate
    factor_breakdown: dict[str, float]
    explanation: str
    spare_parts_gap: list[str]   # parts needed but not in stock
    lead_time_days: int


# ─── Alerts ───────────────────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    alert_code: str
    equipment_id: str
    severity: str
    status: str
    alert_type: str
    title: str
    description: str
    anomaly_score: Optional[float]
    rul_days: Optional[float]
    created_at: datetime
    acknowledged_at: Optional[datetime] = None

class AlertAcknowledge(BaseModel):
    acknowledged_by: str
    notes: str = ""


# ─── Work Orders ──────────────────────────────────────────────────────────────

class WorkOrderCreate(BaseModel):
    equipment_id: str
    wo_type: str = "corrective"
    priority: str = "P3"
    title: str
    description: str = ""
    tasks: list[str] = []
    estimated_hours: float = 0
    scheduled_date: Optional[datetime] = None
    assigned_to: list[str] = []
    parts_required: list[dict] = []
    trigger_alert_id: Optional[str] = None
    ai_generated: bool = False

class WorkOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    wo_code: str
    equipment_id: str
    wo_type: str
    priority: str
    status: str
    title: str
    description: str
    tasks: list[str]
    estimated_hours: float
    scheduled_date: Optional[datetime]
    created_at: datetime


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str   # user | assistant | system
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    citations: list[dict] = []
    actions: list[dict] = []   # [{type, label, payload}]

class ChatRequest(BaseModel):
    session_id: str
    message: str
    equipment_id: str = ""   # equipment in focus (optional)
    user_id: str = "engineer"

class ChatResponse(BaseModel):
    session_id: str
    message: ChatMessage
    context_updated: bool = False


# ─── Reports ──────────────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    report_type: str   # weekly_summary | equipment_detail | rca | maintenance_plan
    equipment_ids: list[str] = []   # empty = all equipment
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    format: str = "pdf"   # pdf | excel | json

class ReportResponse(BaseModel):
    report_id: str
    status: str
    download_url: str = ""
    generated_at: Optional[datetime] = None


# ─── Spare Parts ──────────────────────────────────────────────────────────────

class SparePartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    part_id: str
    description: str
    quantity_on_hand: int
    reorder_point: int
    lead_time_days: int
    unit_cost_usd: float
    storage_location: str
    is_low_stock: bool = False

    @property
    def is_low_stock(self) -> bool:
        return self.quantity_on_hand <= self.reorder_point


# ─── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    full_name: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: str
    email: str
    full_name: str
    role: str
    department: str

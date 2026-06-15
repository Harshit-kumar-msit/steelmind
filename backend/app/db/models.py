"""
Module: db/models.py
Purpose: SQLAlchemy ORM models for all relational data.
         Time-series sensor data lives in InfluxDB (not here).
         This handles equipment registry, work orders, alerts, users, spare parts.
Inputs:  N/A (imported by alembic and CRUD layers)
Outputs: ORM classes mapped to PostgreSQL tables
Production: Add composite indexes on (equipment_id, created_at) for all
            time-windowed queries. Partition alerts and work_orders tables
            by month after 6 months of data.
"""
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text, ForeignKey,
    Enum as SAEnum, JSON, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import enum


class Base(DeclarativeBase):
    pass


# ─── Enums ────────────────────────────────────────────────────────────────────

class CriticalityLevel(str, enum.Enum):
    A = "A"   # Mission critical — plant stops without it
    B = "B"   # Important — significant production impact
    C = "C"   # Minor — low production impact

class EquipmentStatus(str, enum.Enum):
    OPERATIONAL = "operational"
    DEGRADED    = "degraded"
    WARNING     = "warning"
    CRITICAL    = "critical"
    OFFLINE     = "offline"
    MAINTENANCE = "maintenance"

class AlertSeverity(str, enum.Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"

class AlertStatus(str, enum.Enum):
    OPEN          = "open"
    ACKNOWLEDGED  = "acknowledged"
    RESOLVED      = "resolved"

class WorkOrderType(str, enum.Enum):
    PREVENTIVE  = "preventive"
    CORRECTIVE  = "corrective"
    PREDICTIVE  = "predictive"
    EMERGENCY   = "emergency"

class WorkOrderStatus(str, enum.Enum):
    DRAFT       = "draft"
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"

class WorkOrderPriority(str, enum.Enum):
    P1 = "P1"   # Emergency — act within 2 hours
    P2 = "P2"   # Urgent — act within 24 hours
    P3 = "P3"   # High — act within 7 days
    P4 = "P4"   # Routine — scheduled


# ─── Equipment ────────────────────────────────────────────────────────────────

class PlantArea(Base):
    __tablename__ = "plant_areas"

    id:          Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code:        Mapped[str]        = mapped_column(String(20), unique=True, nullable=False)
    name:        Mapped[str]        = mapped_column(String(100), nullable=False)
    description: Mapped[str]        = mapped_column(Text, default="")
    created_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())

    equipment: Mapped[list["Equipment"]] = relationship("Equipment", back_populates="plant_area_rel")


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (
        Index("ix_equipment_criticality", "criticality"),
        Index("ix_equipment_status", "status"),
        Index("ix_equipment_plant_area", "plant_area_code"),
    )

    id:                       Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id:             Mapped[str]                = mapped_column(String(30), unique=True, nullable=False, index=True)
    name:                     Mapped[str]                = mapped_column(String(200), nullable=False)
    plant_area_code:          Mapped[str]                = mapped_column(String(20), ForeignKey("plant_areas.code"))
    equipment_type:           Mapped[str]                = mapped_column(String(50))
    criticality:              Mapped[CriticalityLevel]   = mapped_column(SAEnum(CriticalityLevel), default=CriticalityLevel.B)
    status:                   Mapped[EquipmentStatus]    = mapped_column(SAEnum(EquipmentStatus), default=EquipmentStatus.OPERATIONAL)
    manufacturer:             Mapped[str]                = mapped_column(String(100), default="")
    model_number:             Mapped[str]                = mapped_column(String(100), default="")
    serial_number:            Mapped[str]                = mapped_column(String(100), default="")
    install_date:             Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rated_power_kw:           Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    rated_speed_rpm:          Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    maintenance_interval_days:Mapped[int]               = mapped_column(Integer, default=90)
    last_maintenance_date:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rul_days_baseline:        Mapped[int]                = mapped_column(Integer, default=180)
    sensor_config:            Mapped[dict]               = mapped_column(JSON, default=dict)   # normal/warning/critical ranges
    degradation_rate_k:       Mapped[float]              = mapped_column(Float, default=0.035)
    current_rul_days:         Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    current_degradation_index:Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    current_anomaly_score:    Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    current_priority_score:   Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    last_health_update:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tags:                     Mapped[list]               = mapped_column(JSON, default=list)
    notes:                    Mapped[str]                = mapped_column(Text, default="")
    is_active:                Mapped[bool]               = mapped_column(Boolean, default=True)
    created_at:               Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:               Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    plant_area_rel: Mapped["PlantArea"]        = relationship("PlantArea", back_populates="equipment")
    alerts:         Mapped[list["Alert"]]      = relationship("Alert", back_populates="equipment_rel")
    work_orders:    Mapped[list["WorkOrder"]]  = relationship("WorkOrder", back_populates="equipment_rel")
    health_history: Mapped[list["HealthSnapshot"]] = relationship("HealthSnapshot", back_populates="equipment_rel")


class HealthSnapshot(Base):
    """Hourly snapshots of computed health metrics per equipment."""
    __tablename__ = "health_snapshots"
    __table_args__ = (
        Index("ix_health_snapshots_eq_ts", "equipment_id", "snapshot_at"),
    )

    id:                Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id:      Mapped[str]       = mapped_column(String(30), ForeignKey("equipment.equipment_id"), index=True)
    snapshot_at:       Mapped[datetime]  = mapped_column(DateTime(timezone=True), index=True)
    degradation_index: Mapped[float]     = mapped_column(Float)
    rul_days:          Mapped[float]     = mapped_column(Float)
    anomaly_score:     Mapped[float]     = mapped_column(Float)
    priority_score:    Mapped[float]     = mapped_column(Float)
    sensor_summary:    Mapped[dict]      = mapped_column(JSON, default=dict)
    top_contributor:   Mapped[str]       = mapped_column(String(100), default="")

    equipment_rel: Mapped["Equipment"] = relationship("Equipment", back_populates="health_history")


# ─── Alerts ───────────────────────────────────────────────────────────────────

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_eq_status", "equipment_id", "status"),
        Index("ix_alerts_severity_status", "severity", "status"),
    )

    id:              Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_code:      Mapped[str]         = mapped_column(String(30), unique=True, index=True)
    equipment_id:    Mapped[str]         = mapped_column(String(30), ForeignKey("equipment.equipment_id"))
    severity:        Mapped[AlertSeverity]  = mapped_column(SAEnum(AlertSeverity))
    status:          Mapped[AlertStatus]    = mapped_column(SAEnum(AlertStatus), default=AlertStatus.OPEN)
    alert_type:      Mapped[str]         = mapped_column(String(50))   # anomaly | rul | threshold | system
    title:           Mapped[str]         = mapped_column(String(200))
    description:     Mapped[str]         = mapped_column(Text)
    sensor_name:     Mapped[str]         = mapped_column(String(100), default="")
    sensor_value:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    anomaly_score:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rul_days:        Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_context:     Mapped[dict]        = mapped_column(JSON, default=dict)
    acknowledged_by: Mapped[str]         = mapped_column(String(100), default="")
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:      Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:      Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    equipment_rel: Mapped["Equipment"] = relationship("Equipment", back_populates="alerts")


# ─── Work Orders ──────────────────────────────────────────────────────────────

class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        Index("ix_wo_equipment_status", "equipment_id", "status"),
        Index("ix_wo_priority_status", "priority", "status"),
    )

    id:               Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wo_code:          Mapped[str]               = mapped_column(String(30), unique=True, index=True)
    equipment_id:     Mapped[str]               = mapped_column(String(30), ForeignKey("equipment.equipment_id"))
    wo_type:          Mapped[WorkOrderType]     = mapped_column(SAEnum(WorkOrderType))
    priority:         Mapped[WorkOrderPriority] = mapped_column(SAEnum(WorkOrderPriority), default=WorkOrderPriority.P3)
    status:           Mapped[WorkOrderStatus]   = mapped_column(SAEnum(WorkOrderStatus), default=WorkOrderStatus.DRAFT)
    title:            Mapped[str]               = mapped_column(String(200))
    description:      Mapped[str]               = mapped_column(Text, default="")
    tasks:            Mapped[list]              = mapped_column(JSON, default=list)
    estimated_hours:  Mapped[float]             = mapped_column(Float, default=0)
    actual_hours:     Mapped[Optional[float]]   = mapped_column(Float, nullable=True)
    scheduled_date:   Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True), nullable=True)
    started_at:       Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True), nullable=True)
    completed_at:     Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to:      Mapped[list]              = mapped_column(JSON, default=list)   # list of technician IDs
    parts_required:   Mapped[list]              = mapped_column(JSON, default=list)   # [{part_id, qty}]
    parts_consumed:   Mapped[list]              = mapped_column(JSON, default=list)
    findings:         Mapped[str]               = mapped_column(Text, default="")
    trigger_alert_id: Mapped[Optional[str]]     = mapped_column(String(50), nullable=True)
    ai_generated:     Mapped[bool]              = mapped_column(Boolean, default=False)
    created_by:       Mapped[str]               = mapped_column(String(100), default="system")
    created_at:       Mapped[datetime]          = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:       Mapped[datetime]          = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    equipment_rel: Mapped["Equipment"] = relationship("Equipment", back_populates="work_orders")


# ─── Spare Parts ──────────────────────────────────────────────────────────────

class SparePart(Base):
    __tablename__ = "spare_parts"

    id:                     Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id:                Mapped[str]       = mapped_column(String(50), unique=True, index=True)
    description:            Mapped[str]       = mapped_column(String(300))
    manufacturer:           Mapped[str]       = mapped_column(String(100), default="")
    part_number:            Mapped[str]       = mapped_column(String(100), default="")
    equipment_compatibility:Mapped[list]      = mapped_column(JSON, default=list)
    quantity_on_hand:       Mapped[int]       = mapped_column(Integer, default=0)
    reorder_point:          Mapped[int]       = mapped_column(Integer, default=1)
    lead_time_days:         Mapped[int]       = mapped_column(Integer, default=14)
    unit_cost_usd:          Mapped[float]     = mapped_column(Float, default=0)
    storage_location:       Mapped[str]       = mapped_column(String(50), default="")
    supplier:               Mapped[str]       = mapped_column(String(200), default="")
    criticality:            Mapped[str]       = mapped_column(String(1), default="B")
    last_used_date:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:             Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Users / Technicians ──────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id:           Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:      Mapped[str]       = mapped_column(String(20), unique=True, index=True)
    email:        Mapped[str]       = mapped_column(String(200), unique=True, index=True)
    full_name:    Mapped[str]       = mapped_column(String(200))
    role:         Mapped[str]       = mapped_column(String(50), default="engineer")  # engineer | supervisor | manager | admin
    department:   Mapped[str]       = mapped_column(String(100), default="")
    plant_area:   Mapped[str]       = mapped_column(String(20), default="")
    hashed_password: Mapped[str]   = mapped_column(String(500))
    is_active:    Mapped[bool]      = mapped_column(Boolean, default=True)
    last_login:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Chat Conversations ───────────────────────────────────────────────────────

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id:           Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id:   Mapped[str]       = mapped_column(String(50), unique=True, index=True)
    user_id:      Mapped[str]       = mapped_column(String(20), ForeignKey("users.user_id"))
    equipment_id: Mapped[str]       = mapped_column(String(30), default="")   # equipment in focus
    title:        Mapped[str]       = mapped_column(String(200), default="New conversation")
    messages:     Mapped[list]      = mapped_column(JSON, default=list)   # [{role, content, timestamp, citations}]
    context:      Mapped[dict]      = mapped_column(JSON, default=dict)   # active equipment, last anomaly scores, etc.
    created_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─── Failure Events ───────────────────────────────────────────────────────────

class FailureEvent(Base):
    __tablename__ = "failure_events"

    id:            Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_code:    Mapped[str]       = mapped_column(String(30), unique=True, index=True)
    equipment_id:  Mapped[str]       = mapped_column(String(30), ForeignKey("equipment.equipment_id"))
    event_type:    Mapped[str]       = mapped_column(String(30))   # failure | near_miss | degradation
    failure_mode:  Mapped[str]       = mapped_column(String(100))
    detected_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True))
    failed_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause:    Mapped[str]       = mapped_column(String(200), default="")
    downtime_hours:Mapped[float]     = mapped_column(Float, default=0)
    downtime_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    repair_action: Mapped[str]       = mapped_column(String(200), default="")
    rca_notes:     Mapped[str]       = mapped_column(Text, default="")
    raw_data:      Mapped[dict]      = mapped_column(JSON, default=dict)
    created_at:    Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

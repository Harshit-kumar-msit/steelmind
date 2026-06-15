"""
Gap 1: Digital Maintenance Logbook
Module: app/db/logbook_model.py
Purpose: Persistent per-equipment digital log. Technicians write free-text
         observations from the UI or via Copilot ACTION:ADD_LOG directive.
         Recent log entries are injected into the Copilot context so the LLM
         can reference what engineers actually observed on the floor.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.models import Base


class MaintenanceLog(Base):
    __tablename__ = "maintenance_logs"

    id:           Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id: Mapped[str]       = mapped_column(String(30), ForeignKey("equipment.equipment_id"), index=True)
    logged_by:    Mapped[str]       = mapped_column(String(100))          # user_id or name
    log_type:     Mapped[str]       = mapped_column(String(40), default="observation")
    # log_type options:
    #   observation   — "oil looks dark, slight smell"
    #   inspection    — "checked alignment, within spec"
    #   repair        — "replaced bearing SKF-23248"
    #   measurement   — "vibration baseline 2.3 mm/s after PM"
    #   anomaly_note  — "unusual noise at startup, lasts ~10s"
    #   ai_generated  — log entry written by Copilot on behalf of engineer
    notes:        Mapped[str]       = mapped_column(Text)
    work_order_id:Mapped[str]       = mapped_column(String(30), default="")  # link to WO if applicable
    created_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

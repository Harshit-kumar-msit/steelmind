"""
Gap 2: Feedback-Driven Improvement Loop
Module: app/db/feedback_model.py + app/api/routes/feedback.py
Purpose: Capture thumbs up/down on Copilot responses. Store corrections.
         A weekly batch job reads low-rated responses, extracts patterns,
         and writes them into a feedback_examples.json file that is prepended
         to the Copilot system prompt as negative/positive few-shot examples.

Flow:
  Engineer rates response → POST /copilot/feedback
  → stored in copilot_feedback table
  → nightly job: aggregate poor responses → update prompts/feedback_examples.json
  → next Copilot call: feedback_examples.json injected into system prompt
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.models import Base


class CopilotFeedback(Base):
    __tablename__ = "copilot_feedback"

    id:              Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id:      Mapped[str]       = mapped_column(String(50), index=True)
    message_index:   Mapped[int]       = mapped_column(Integer, default=0)   # position in conversation
    equipment_id:    Mapped[str]       = mapped_column(String(30), default="")
    user_id:         Mapped[str]       = mapped_column(String(50))
    user_query:      Mapped[str]       = mapped_column(Text)                 # what the engineer asked
    ai_response:     Mapped[str]       = mapped_column(Text)                 # what Copilot said
    rating:          Mapped[int]       = mapped_column(Integer)              # 1 = thumbs up, -1 = thumbs down
    correction_text: Mapped[str]       = mapped_column(Text, default="")     # engineer's correction (optional)
    intent:          Mapped[str]       = mapped_column(String(40), default="") # classified intent
    was_helpful:     Mapped[bool]      = mapped_column(Boolean, default=True)
    created_at:      Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

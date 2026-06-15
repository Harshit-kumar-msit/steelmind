"""
Module: api/routes/feedback.py
Purpose: Feedback endpoints + nightly batch job that reads poor responses
         and updates the few-shot examples injected into the Copilot prompt.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from pydantic import BaseModel
from loguru import logger

from app.db.session import get_db
from app.db.feedback_model import CopilotFeedback
from app.ai.llm.client import groq_client

router = APIRouter()

FEEDBACK_EXAMPLES_PATH = Path(__file__).parent.parent.parent.parent / "data" / "feedback_examples.json"


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    session_id:      str
    message_index:   int = 0
    equipment_id:    str = ""
    user_id:         str
    user_query:      str
    ai_response:     str
    rating:          int          # 1 = helpful, -1 = not helpful
    correction_text: str = ""
    intent:          str = ""


# ── Submit feedback ───────────────────────────────────────────────────────────

@router.post("/copilot/feedback", status_code=201)
async def submit_feedback(
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Called when engineer clicks thumbs up/down on a Copilot message.
    Also accepts an optional correction_text when rating == -1.
    """
    fb = CopilotFeedback(
        session_id=body.session_id,
        message_index=body.message_index,
        equipment_id=body.equipment_id,
        user_id=body.user_id,
        user_query=body.user_query,
        ai_response=body.ai_response,
        rating=body.rating,
        correction_text=body.correction_text,
        intent=body.intent,
        was_helpful=(body.rating > 0),
    )
    db.add(fb)
    await db.commit()

    logger.info(
        f"Feedback received | session={body.session_id} "
        f"| rating={'👍' if body.rating > 0 else '👎'} "
        f"| equipment={body.equipment_id}"
    )
    return {"status": "recorded", "id": str(fb.id)}


# ── Feedback stats ────────────────────────────────────────────────────────────

@router.get("/copilot/feedback/stats")
async def feedback_stats(db: AsyncSession = Depends(get_db)):
    """Return aggregate feedback statistics — shown in the Reports page."""
    result = await db.execute(select(CopilotFeedback))
    all_fb = result.scalars().all()

    if not all_fb:
        return {"total": 0, "positive": 0, "negative": 0, "helpfulness_rate": 0}

    positive = sum(1 for f in all_fb if f.rating > 0)
    negative = len(all_fb) - positive
    with_correction = sum(1 for f in all_fb if f.correction_text.strip())

    return {
        "total":             len(all_fb),
        "positive":          positive,
        "negative":          negative,
        "with_correction":   with_correction,
        "helpfulness_rate":  round(positive / len(all_fb) * 100, 1),
        "by_intent":         _group_by_intent(all_fb),
    }


def _group_by_intent(feedback_list):
    groups = {}
    for f in feedback_list:
        intent = f.intent or "general"
        if intent not in groups:
            groups[intent] = {"total": 0, "positive": 0}
        groups[intent]["total"] += 1
        if f.rating > 0:
            groups[intent]["positive"] += 1
    return {k: {**v, "rate": round(v["positive"] / v["total"] * 100, 1)} for k, v in groups.items()}


# ── Batch improvement job ─────────────────────────────────────────────────────

async def run_feedback_improvement_job(db: AsyncSession):
    """
    Nightly batch job. Reads the last 7 days of negative feedback (rating == -1)
    that includes a correction_text. Uses the LLM to synthesize 3–5 few-shot
    examples from the real corrections. Writes them to feedback_examples.json.

    The Copilot system prompt reads feedback_examples.json on every call and
    prepends the examples — so the model learns from real engineer corrections
    without any fine-tuning.

    Called by: app/services/worker.py on a daily schedule.
    """
    week_ago = datetime.utcnow() - timedelta(days=7)
    result = await db.execute(
        select(CopilotFeedback)
        .where(
            CopilotFeedback.rating == -1,
            CopilotFeedback.correction_text != "",
            CopilotFeedback.created_at >= week_ago,
        )
        .limit(20)
    )
    poor_responses = result.scalars().all()

    if not poor_responses:
        logger.info("Feedback job: no negative feedback with corrections this week")
        return

    # Build a prompt asking the LLM to extract few-shot examples from corrections
    cases = []
    for fb in poor_responses:
        cases.append(
            f"QUESTION: {fb.user_query}\n"
            f"BAD RESPONSE: {fb.ai_response[:300]}\n"
            f"ENGINEER CORRECTION: {fb.correction_text}"
        )

    synthesis_prompt = f"""
You are improving an AI maintenance copilot by learning from engineer corrections.

Below are {len(cases)} cases where the AI gave a poor response and an engineer corrected it.
Extract 3-5 concise few-shot examples in JSON format that teach the AI what NOT to do
and what the correct response pattern should be.

Cases:
{'---'.join(cases)}

Respond ONLY with valid JSON — an array of objects with keys:
"query", "bad_pattern", "good_pattern", "lesson"
"""

    try:
        raw = await groq_client.complete(
            messages=[{"role": "user", "content": synthesis_prompt}],
            model=groq_client.fast_model,
            json_mode=True,
            max_tokens=1000,
        )
        examples = json.loads(raw)
        if isinstance(examples, list):
            FEEDBACK_EXAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
            FEEDBACK_EXAMPLES_PATH.write_text(json.dumps(examples, indent=2))
            logger.info(f"Feedback job: wrote {len(examples)} few-shot examples to {FEEDBACK_EXAMPLES_PATH}")
    except Exception as e:
        logger.error(f"Feedback improvement job failed: {e}")


def load_feedback_examples() -> str:
    """
    Load few-shot examples from feedback_examples.json.
    Called by build_copilot_prompt() to inject learned corrections.
    Returns empty string if no examples file exists yet.
    """
    if not FEEDBACK_EXAMPLES_PATH.exists():
        return ""

    try:
        examples = json.loads(FEEDBACK_EXAMPLES_PATH.read_text())
        if not examples:
            return ""
        lines = ["LEARNED CORRECTIONS FROM ENGINEER FEEDBACK (avoid these patterns):"]
        for ex in examples[:5]:   # cap at 5 to keep prompt concise
            lines.append(f"- Lesson: {ex.get('lesson', '')}")
            lines.append(f"  Avoid: {ex.get('bad_pattern', '')}")
            lines.append(f"  Prefer: {ex.get('good_pattern', '')}")
        return "\n".join(lines)
    except Exception:
        return ""

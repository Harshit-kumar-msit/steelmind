"""
Module: api/routes/reports.py + inventory.py + auth.py (combined for brevity)
"""

# ── reports.py ────────────────────────────────────────────────────────────────
from fastapi import APIRouter as _APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from app.db.session import get_db
from app.db.models import Equipment, Alert, WorkOrder, AlertStatus, WorkOrderStatus
from app.ai.llm.client import groq_client
from app.ai.llm.prompts import REPORT_WEEKLY_SYSTEM

reports_router = _APIRouter()


@reports_router.post("/weekly-summary")
async def generate_weekly_report(db: AsyncSession = Depends(get_db)):
    """Generate LLM-written weekly maintenance summary."""
    week_ago = datetime.utcnow() - timedelta(days=7)

    eq_result = await db.execute(select(Equipment).where(Equipment.is_active == True))
    all_eq = eq_result.scalars().all()

    crit_alerts = await db.execute(
        select(Alert).where(Alert.severity == "critical", Alert.created_at >= week_ago)
    )
    wo_done = await db.execute(
        select(WorkOrder).where(WorkOrder.status == WorkOrderStatus.COMPLETED, WorkOrder.completed_at >= week_ago)
    )
    wo_open = await db.execute(
        select(WorkOrder).where(WorkOrder.status.in_(["open", "in_progress"]))
    )

    top_risks = sorted(
        [e for e in all_eq if e.current_priority_score],
        key=lambda e: e.current_priority_score, reverse=True
    )[:5]

    report_prompt = REPORT_WEEKLY_SYSTEM.format(
        date_from=(datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
        date_to=datetime.utcnow().strftime("%Y-%m-%d"),
        total_equipment=len(all_eq),
        critical_alerts=len(crit_alerts.scalars().all()),
        wo_completed=len(wo_done.scalars().all()),
        wo_pending=len(wo_open.scalars().all()),
        downtime_prevented_hours="~24",
        top_risks=", ".join(e.equipment_id for e in top_risks),
        maintenance_spend="42,500",
    )

    report_text = await groq_client.complete(
        messages=[{"role": "user", "content": "Generate the weekly maintenance report."}],
        system_prompt=report_prompt,
        max_tokens=1500,
    )

    return {
        "report_type": "weekly_summary",
        "generated_at": datetime.utcnow().isoformat(),
        "content": report_text,
        "metadata": {
            "total_equipment": len(all_eq),
            "top_risk_equipment": [e.equipment_id for e in top_risks],
        },
    }


router = reports_router


# ── inventory.py ──────────────────────────────────────────────────────────────
from fastapi import APIRouter as _InventoryRouter, Query as _Query
from sqlalchemy import and_ as _and_
from app.db.models import SparePart as _SparePart

inventory_router = _InventoryRouter()


@inventory_router.get("/")
async def list_inventory(
    low_stock: bool = _Query(False),
    equipment_id: str = _Query(""),
    db: AsyncSession = Depends(get_db),
):
    query = select(_SparePart)
    result = await db.execute(query)
    parts = result.scalars().all()

    output = []
    for p in parts:
        if equipment_id and equipment_id not in (p.equipment_compatibility or []):
            continue
        is_low = p.quantity_on_hand <= p.reorder_point
        if low_stock and not is_low:
            continue
        output.append({
            "part_id":                p.part_id,
            "description":            p.description,
            "quantity_on_hand":       p.quantity_on_hand,
            "reorder_point":          p.reorder_point,
            "lead_time_days":         p.lead_time_days,
            "unit_cost_usd":          p.unit_cost_usd,
            "storage_location":       p.storage_location,
            "supplier":               p.supplier,
            "criticality":            p.criticality,
            "equipment_compatibility":p.equipment_compatibility,
            "is_low_stock":           is_low,
        })
    return output


@inventory_router.get("/check")
async def check_parts_availability(
    part_ids: str = _Query(..., description="Comma-separated part IDs"),
    db: AsyncSession = Depends(get_db),
):
    """Check availability for a list of parts — called by Copilot action buttons."""
    ids = [p.strip() for p in part_ids.split(",")]
    result = await db.execute(select(_SparePart).where(_SparePart.part_id.in_(ids)))
    parts = {p.part_id: p for p in result.scalars().all()}

    return {
        pid: {
            "available":        pid in parts and parts[pid].quantity_on_hand > 0,
            "quantity_on_hand": parts[pid].quantity_on_hand if pid in parts else 0,
            "lead_time_days":   parts[pid].lead_time_days   if pid in parts else 14,
            "description":      parts[pid].description       if pid in parts else pid,
        }
        for pid in ids
    }


# ── auth.py ───────────────────────────────────────────────────────────────────
from fastapi import APIRouter as _AuthRouter, HTTPException as _HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Form
from passlib.context import CryptContext
from jose import jwt
from datetime import timedelta as _timedelta
from app.core.config import settings as _settings
from app.db.models import User as _User
from app.db.schemas import LoginRequest, TokenResponse

auth_router = _AuthRouter()
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _create_token(data: dict) -> str:
    to_encode = {**data, "exp": datetime.utcnow() + _timedelta(minutes=_settings.access_token_expire_minutes)}
    return jwt.encode(to_encode, _settings.secret_key, algorithm=_settings.algorithm)


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(_User).where(_User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not _pwd_ctx.verify(body.password, user.hashed_password):
        raise _HTTPException(401, "Invalid credentials")
    token = _create_token({"sub": user.user_id, "role": user.role})
    return TokenResponse(
        access_token=token,
        user_id=user.user_id,
        role=user.role,
        full_name=user.full_name,
    )


@auth_router.post("/register", status_code=201)
async def register(
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form("engineer"),
    db: AsyncSession = Depends(get_db),
):
    user = _User(
        user_id=f"USER-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        email=email,
        full_name=full_name,
        role=role,
        hashed_password=_pwd_ctx.hash(password),
    )
    db.add(user)
    await db.commit()
    return {"status": "created", "user_id": user.user_id}

"""
Module: app/main.py
Purpose: FastAPI application entry point.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import settings
from app.db.session import engine
from app.db.models import Base

from app.db.logbook_model import MaintenanceLog
from app.db.feedback_model import CopilotFeedback

# ── Routes ──
from app.api.routes import (
    auth, equipment, sensors, anomaly,
    alerts, workorders, copilot, reports, inventory
)
from app.api.routes.logbook import router as logbook_router
from app.api.routes.feedback import router as feedback_router


# ───────────────────────── Lifespan ─────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"SteelMind API starting | env={settings.environment}")

    # DB init
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database ready")

    # Safe imports (avoid Render crash if optional modules fail)
    try:
        from app.ai.anomaly.detector import get_detector
        get_detector()
        logger.info("Anomaly detector loaded")
    except Exception as e:
        logger.warning(f"Detector skipped: {e}")

    try:
        from app.ai.rag.retriever import get_retriever
        retriever = get_retriever()
        logger.info(f"RAG ready | chunks={retriever.collection.count()}")
    except Exception as e:
        logger.warning(f"RAG skipped: {e}")

    try:
        from app.ai.llm.orchestrator import get_orchestrator
        get_orchestrator()
        logger.info("LLM orchestrator ready")
    except Exception as e:
        logger.warning(f"Orchestrator skipped: {e}")

    try:
        from app.services.seeder import seed_if_empty
        await seed_if_empty()
        logger.info("Seed complete")
    except Exception as e:
        logger.warning(f"Seeder skipped: {e}")

    task = None
    try:
        from app.services.worker import start_background_tasks
        task = asyncio.create_task(start_background_tasks())
        logger.info("Background workers started")
    except Exception as e:
        logger.warning(f"Workers skipped: {e}")

    logger.info("SteelMind API READY 🚀")
    yield

    if task:
        task.cancel()

    await engine.dispose()
    logger.info("Shutdown complete")


# ───────────────────────── App ─────────────────────────

app = FastAPI(
    title="SteelMind API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ───────────────────────── Middleware ─────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# ───────────────────────── Error Handler ─────────────────────────

@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    logger.error(f"{request.url} | {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ───────────────────────── Routes ─────────────────────────

API = "/api/v1"

app.include_router(auth.router, prefix=f"{API}/auth", tags=["Auth"])
app.include_router(equipment.router, prefix=f"{API}/equipment", tags=["Equipment"])
app.include_router(sensors.router, prefix=f"{API}/sensors", tags=["Sensors"])
app.include_router(anomaly.router, prefix=f"{API}/anomaly", tags=["Anomaly"])
app.include_router(alerts.router, prefix=f"{API}/alerts", tags=["Alerts"])
app.include_router(workorders.router, prefix=f"{API}/workorders", tags=["WorkOrders"])
app.include_router(copilot.router, prefix=f"{API}/copilot", tags=["Copilot"])
app.include_router(reports.router, prefix=f"{API}/reports", tags=["Reports"])
app.include_router(inventory.router, prefix=f"{API}/inventory", tags=["Inventory"])

app.include_router(logbook_router, prefix=f"{API}", tags=["Logbook"])
app.include_router(feedback_router, prefix=f"{API}", tags=["Feedback"])


# ───────────────────────── Health ─────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.version
    }


@app.get("/")
async def root():
    return {
        "message": "SteelMind API",
        "docs": "/docs"
    }
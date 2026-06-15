"""
Module: app/main.py
Purpose: FastAPI application entry point. Registers all routers, middleware,
         CORS, lifespan (startup/shutdown), and exception handlers.
Inputs:  None (loaded by uvicorn)
Outputs: ASGI app instance
Production: Add Sentry for error tracking, Prometheus /metrics endpoint,
            and rate limiting middleware before going live.
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
from app.db.logbook_model import MaintenanceLog    # register table
from app.db.feedback_model import CopilotFeedback  # register table

# ── Route imports ──
from app.api.routes import (
    auth, equipment, sensors, anomaly,
    alerts, workorders, copilot, reports, inventory
)
from app.api.routes.logbook import router as logbook_router
from app.api.routes.feedback import router as feedback_router


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: create DB tables, load ML models, warm up RAG index, seed demo data.
    Shutdown: close connections cleanly.
    """
    logger.info(f"🏭 SteelMind API starting | env={settings.environment}")

    # 1. Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables ready")

    # 2. Load anomaly detection models (pre-trained joblib files)
    from app.ai.anomaly.detector import get_detector
    get_detector()
    logger.info("✅ Anomaly detector loaded")

    # 3. Warm up RAG retriever (loads embedding model + ChromaDB)
    from app.ai.rag.retriever import get_retriever
    retriever = get_retriever()
    logger.info(f"✅ RAG retriever ready | chunks={retriever.collection.count()}")

    # 4. Warm up LLM orchestrator
    from app.ai.llm.orchestrator import get_orchestrator
    get_orchestrator()
    logger.info("✅ LLM orchestrator ready")

    # 5. Seed demo data if tables are empty
    from app.services.seeder import seed_if_empty
    await seed_if_empty()
    logger.info("✅ Demo data seeded")

    # 6. Start background workers (anomaly scan, health updates)
    from app.services.worker import start_background_tasks
    task = asyncio.create_task(start_background_tasks())
    logger.info("✅ Background workers started")

    logger.info("🚀 SteelMind API ready")
    yield

    # Shutdown
    logger.info("Shutting down SteelMind API...")
    task.cancel()
    await engine.dispose()
    logger.info("👋 Shutdown complete")


# ─── App Instance ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="SteelMind API",
    description="Intelligent Maintenance Wizard for Steel Manufacturing Plants",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─── Middleware ───────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if not settings.is_development
                  else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ─── Global Exception Handlers ────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc} | path={request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

API = "/api/v1"

app.include_router(auth.router,       prefix=f"{API}/auth",      tags=["Auth"])
app.include_router(equipment.router,  prefix=f"{API}/equipment", tags=["Equipment"])
app.include_router(sensors.router,    prefix=f"{API}/sensors",   tags=["Sensors"])
app.include_router(anomaly.router,    prefix=f"{API}/anomaly",   tags=["Anomaly"])
app.include_router(alerts.router,     prefix=f"{API}/alerts",    tags=["Alerts"])
app.include_router(workorders.router, prefix=f"{API}/workorders",tags=["Work Orders"])
app.include_router(copilot.router,    prefix=f"{API}/copilot",   tags=["Copilot"])
app.include_router(reports.router,    prefix=f"{API}/reports",   tags=["Reports"])
app.include_router(inventory.router,  prefix=f"{API}/inventory", tags=["Inventory"])
app.include_router(logbook_router,    prefix=f"{API}",           tags=["Logbook"])
app.include_router(feedback_router,   prefix=f"{API}",           tags=["Feedback"])


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "ok",
        "version": settings.version,
        "environment": settings.environment,
    }

@app.get("/", tags=["System"])
async def root():
    return {"message": "SteelMind API", "docs": "/docs"}

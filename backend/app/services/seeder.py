"""
Module: services/seeder.py
Purpose: Load synthetic data into PostgreSQL and InfluxDB on first startup.
         Checks if data already exists — skips if seeded.
         Also trains the Isolation Forest models on synthetic sensor data.
"""
import json
from datetime import datetime
from pathlib import Path
from loguru import logger
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.db.session import AsyncSessionLocal
from app.db.models import Equipment, PlantArea, SparePart, WorkOrder, User, FailureEvent
from app.db.logbook_model import MaintenanceLog    # ensure table registered
from app.db.feedback_model import CopilotFeedback  # ensure table registered

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

SYNTHETIC_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"
RAW_DOCS_DIR  = Path(__file__).parent.parent.parent / "data" / "raw_docs"


async def seed_if_empty():
    """Only seeds if the equipment table is empty."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Equipment).limit(1))
        if result.scalar_one_or_none():
            logger.info("Database already seeded — skipping")
            return

    logger.info("Seeding database with synthetic data...")
    await _seed_postgres()
    await _seed_influxdb()
    await _ingest_documents()
    await _train_models()
    logger.info("✅ Seeding complete")


async def _seed_postgres():
    async with AsyncSessionLocal() as db:
        # ── Plant areas ──
        areas = [
            PlantArea(code="BF",  name="Blast Furnace - Iron Making"),
            PlantArea(code="HSM", name="Hot Strip Mill"),
            PlantArea(code="CC",  name="Continuous Caster"),
            PlantArea(code="RHF", name="Reheating Furnace"),
            PlantArea(code="WTP", name="Water Treatment Plant"),
        ]
        for a in areas:
            db.add(a)

        # ── Demo user ──
        db.add(User(
            user_id="TECH-001",
            email="engineer@steelmind.demo",
            full_name="Rajesh Kumar",
            role="engineer",
            hashed_password=_pwd_ctx.hash("demo1234"),
        ))
        db.add(User(
            user_id="MGR-001",
            email="manager@steelmind.demo",
            full_name="Priya Sharma",
            role="manager",
            hashed_password=_pwd_ctx.hash("demo1234"),
        ))

        await db.commit()

        # ── Equipment ──
        from data.synthetic.generators.generate_all import EQUIPMENT_CATALOG, SENSOR_PROFILES
        for eq_data in EQUIPMENT_CATALOG:
            sensor_cfg = {
                "normal":   {},
                "warning":  {},
                "critical": {},
            }
            profile = SENSOR_PROFILES.get(eq_data["type"], SENSOR_PROFILES["default"])
            for sensor, cfg in profile.items():
                if cfg.get("mean"):
                    sensor_cfg["normal"][sensor]   = cfg["mean"]
                    sensor_cfg["warning"][sensor]  = cfg.get("warning", cfg["mean"] * 1.15)
                    sensor_cfg["critical"][sensor] = cfg["fail"]

            eq = Equipment(
                equipment_id=eq_data["equipment_id"],
                name=eq_data["name"],
                plant_area_code=eq_data["area"],
                equipment_type=eq_data["type"],
                criticality=eq_data["crit"],
                rated_power_kw=eq_data["power_kw"],
                rated_speed_rpm=eq_data["rpm"],
                maintenance_interval_days=90,
                rul_days_baseline=eq_data["rul_base"],
                degradation_rate_k=eq_data["k"],
                sensor_config=sensor_cfg,
                is_active=True,
            )
            db.add(eq)

        # ── Spare parts ──
        from data.synthetic.generators.generate_all import SPARE_PARTS
        for p in SPARE_PARTS:
            db.add(SparePart(
                part_id=p["part_id"],
                description=p["desc"],
                equipment_compatibility=p["compat"],
                quantity_on_hand=p["qty"],
                reorder_point=p["reorder"],
                lead_time_days=p["lead"],
                unit_cost_usd=p["cost"],
                criticality=p["crit"],
            ))

        await db.commit()
        logger.info("PostgreSQL seed complete")

        # ── Seed demo logbook entries ──
        demo_logs = [
            MaintenanceLog(equipment_id="EQ-BF-001", logged_by="TECH-001", log_type="observation",  notes="Oil colour darker than usual during routine check. Slight metallic smell from drain point. Flagged for oil sample collection."),
            MaintenanceLog(equipment_id="EQ-BF-001", logged_by="TECH-002", log_type="measurement",  notes="Vibration baseline reading taken at bearing housing: 2.9 mm/s RMS horizontal, 2.7 vertical. Within normal range at time of measurement."),
            MaintenanceLog(equipment_id="EQ-BF-001", logged_by="TECH-001", log_type="anomaly_note", notes="Unusual rumbling noise heard from DE bearing side during startup. Lasted approximately 10 seconds then cleared. Machine running normally now. Monitor closely."),
            MaintenanceLog(equipment_id="EQ-HSM-001", logged_by="TECH-003", log_type="inspection",  notes="Checked coupling alignment post bearing replacement. Parallel: 0.03mm, Angular: 0.02mm/100mm. Both within permissible limits per SOP-ALIGN-001."),
            MaintenanceLog(equipment_id="EQ-CC-002",  logged_by="TECH-002", log_type="observation",  notes="Minor oil seep observed at seal housing. Not enough to require immediate action but marked for inspection during next PM window."),
        ]
        for log in demo_logs:
            db.add(log)
        await db.commit()
        logger.info("Demo logbook entries seeded")


async def _seed_influxdb():
    """Write 30 days of synthetic sensor data to InfluxDB."""
    from data.synthetic.generators.generate_all import EQUIPMENT_CATALOG, SteelMindDataGenerator
    from app.services.influx_service import get_influx_service

    gen    = SteelMindDataGenerator()
    influx = get_influx_service()

    for eq_data in EQUIPMENT_CATALOG:
        df = gen.generate_sensor_dataframe(eq_data, days=30)
        # Write in daily chunks to avoid memory issues
        days_dfs = [df[i:i+1440] for i in range(0, len(df), 1440)]
        for chunk in days_dfs:
            influx.write_dataframe(eq_data["equipment_id"], chunk)

    logger.info("InfluxDB seed complete")


async def _ingest_documents():
    """Ingest synthetic knowledge documents into ChromaDB."""
    from data.synthetic.generators.generate_all import SteelMindDataGenerator
    from app.ai.rag.ingestor import get_ingestor, DocumentMeta

    gen      = SteelMindDataGenerator()
    gen.generate_documents()   # Write .txt files to raw_docs/

    ingestor = get_ingestor()
    doc_configs = [
        ("centrifugal_compressor_maintenance_manual.txt", "Centrifugal Compressor Maintenance Manual", "manual", ["centrifugal_compressor"], "BF"),
        ("bearing_replacement_sop.txt",                   "Bearing Replacement SOP",                   "sop",    ["EQ-BF-001","EQ-BF-002","EQ-HSM-001"], "general"),
        ("vibration_analysis_guide.txt",                  "Vibration Analysis & Fault Diagnosis Guide", "manual", ["centrifugal_compressor","rolling_mill_drive"], "general"),
        ("failure_rca_case_study_bf001_2024.txt",         "RCA: BF-001 Bearing Failure 2024",           "rca",    ["EQ-BF-001"], "BF"),
        ("iso_4406_oil_cleanliness_standard.txt",         "ISO 4406 Oil Cleanliness Standard",          "standard",[], "general"),
        ("maintenance_planning_best_practices.txt",       "Maintenance Planning Best Practices",         "manual", [], "general"),
    ]

    for filename, title, category, tags, area in doc_configs:
        filepath = RAW_DOCS_DIR / filename
        if not filepath.exists():
            continue
        meta = DocumentMeta(
            doc_id=filename.replace(".txt", ""),
            title=title,
            doc_category=category,
            equipment_tags=tags,
            plant_area=area,
            source_file=str(filepath),
        )
        result = ingestor.ingest_file(str(filepath), meta)
        logger.info(f"  Ingested: {title} — {result['chunks']} chunks")

    logger.info("RAG documents ingested")


async def _train_models():
    """Train Isolation Forest models on seeded sensor data."""
    from data.synthetic.generators.generate_all import EQUIPMENT_CATALOG, SteelMindDataGenerator
    from app.ai.anomaly.detector import get_detector
    import pandas as pd

    gen      = SteelMindDataGenerator()
    detector = get_detector()

    # Group by equipment_type and train one model per type
    type_dfs: dict[str, list] = {}
    for eq_data in EQUIPMENT_CATALOG:
        eq_type = eq_data["type"]
        # Use a fresh non-degraded dataset for training (clean baseline)
        df = gen.generate_sensor_dataframe({**eq_data, "degrade": False}, days=7)
        type_dfs.setdefault(eq_type, []).append(df)

    for eq_type, dfs in type_dfs.items():
        combined = pd.concat(dfs, ignore_index=True)
        result = detector.train(eq_type, combined)
        logger.info(f"  Trained: {eq_type} | samples={result['samples']}")

    logger.info("ML models trained")

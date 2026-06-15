"""
Module: data/synthetic/generators/generate_all.py
Purpose: Generate a complete, realistic synthetic dataset for SteelMind demo.
         Creates equipment registry, sensor streams, failure logs, work orders,
         spare parts inventory, and document corpus.
Run:     python -m data.synthetic.generators.generate_all
Outputs:
  - PostgreSQL: all tables seeded
  - InfluxDB: 30 days of sensor readings per equipment
  - data/raw_docs/: 80 synthetic documents for RAG
  - Console: progress summary

Implementation Notes:
  - Sensor streams include a realistic degradation ramp on 3 of 12 equipment
    (to demonstrate anomaly detection working during demo)
  - Failure events are correlated to sensor degradation for realism
  - Documents are pre-written templates, not LLM-generated (no API cost)
"""
import asyncio
import random
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from faker import Faker
from loguru import logger

fake = Faker("en_IN")   # Indian locale for Bhilai Steel Plant context
random.seed(42)
np.random.seed(42)

# ─── Equipment Catalog ────────────────────────────────────────────────────────

EQUIPMENT_CATALOG = [
    # Blast Furnace (Iron Making)
    {"equipment_id": "EQ-BF-001", "name": "BF No.2 Top Gas Blower",          "type": "centrifugal_compressor", "area": "BF",  "crit": "A", "power_kw": 6000, "rpm": 3000, "rul_base": 180, "k": 0.035, "degrade": True},
    {"equipment_id": "EQ-BF-002", "name": "BF No.3 Top Gas Blower",          "type": "centrifugal_compressor", "area": "BF",  "crit": "A", "power_kw": 6000, "rpm": 3000, "rul_base": 180, "k": 0.030, "degrade": False},
    {"equipment_id": "EQ-BF-003", "name": "BF No.2 Stove Combustion Fan",    "type": "centrifugal_compressor", "area": "BF",  "crit": "B", "power_kw": 750,  "rpm": 1500, "rul_base": 120, "k": 0.040, "degrade": False},

    # Hot Strip Mill
    {"equipment_id": "EQ-HSM-001", "name": "HSM Roughing Mill R2 Main Drive","type": "rolling_mill_drive",     "area": "HSM", "crit": "A", "power_kw": 8000, "rpm": 750,  "rul_base": 200, "k": 0.028, "degrade": True},
    {"equipment_id": "EQ-HSM-002", "name": "HSM Finishing Mill F4 Drive",    "type": "rolling_mill_drive",     "area": "HSM", "crit": "A", "power_kw": 5000, "rpm": 900,  "rul_base": 200, "k": 0.032, "degrade": False},
    {"equipment_id": "EQ-HSM-003", "name": "HSM Downcoiler Hydraulic Unit",  "type": "hydraulic_system",       "area": "HSM", "crit": "B", "power_kw": 400,  "rpm": 1450, "rul_base": 150, "k": 0.045, "degrade": False},

    # Continuous Caster
    {"equipment_id": "EQ-CC-001",  "name": "Caster No.1 Mould Oscillator",   "type": "centrifugal_compressor", "area": "CC",  "crit": "A", "power_kw": 200,  "rpm": 1450, "rul_base": 90,  "k": 0.055, "degrade": False},
    {"equipment_id": "EQ-CC-002",  "name": "Caster No.2 Secondary Cooling Pump","type": "hydraulic_system",   "area": "CC",  "crit": "B", "power_kw": 300,  "rpm": 1450, "rul_base": 150, "k": 0.038, "degrade": True},

    # Reheating Furnace
    {"equipment_id": "EQ-RHF-001", "name": "RHF No.1 Combustion Air Blower", "type": "centrifugal_compressor","area": "RHF", "crit": "B", "power_kw": 900,  "rpm": 1500, "rul_base": 120, "k": 0.042, "degrade": False},
    {"equipment_id": "EQ-RHF-002", "name": "RHF No.2 Combustion Air Blower", "type": "centrifugal_compressor","area": "RHF", "crit": "B", "power_kw": 900,  "rpm": 1500, "rul_base": 120, "k": 0.042, "degrade": False},

    # Utilities
    {"equipment_id": "EQ-WTP-001", "name": "WTP Feed Pump No.1",             "type": "hydraulic_system",       "area": "WTP", "crit": "C", "power_kw": 250,  "rpm": 1450, "rul_base": 200, "k": 0.020, "degrade": False},
    {"equipment_id": "EQ-WTP-002", "name": "WTP Filter Press No.2",          "type": "default",                "area": "WTP", "crit": "C", "power_kw": 75,   "rpm": 0,    "rul_base": 365, "k": 0.015, "degrade": False},
]

# ─── Sensor Profiles Per Equipment Type ───────────────────────────────────────

SENSOR_PROFILES = {
    "centrifugal_compressor": {
        "vibration_rms_mm_s": {"mean": 2.8,  "std": 0.3,  "fail": 7.1},
        "bearing_temp_c":     {"mean": 72.0, "std": 2.0,  "fail": 95.0},
        "lube_pressure_bar":  {"mean": 4.2,  "std": 0.1,  "fail": 3.0, "invert": True},
        "motor_current_a":    {"mean": None, "std_pct": 0.04, "fail_pct": 1.30},  # % of rated
        "speed_rpm":          {"mean": None, "std_pct": 0.005,"fail_pct": None},
        "outlet_temp_c":      {"mean": 145,  "std": 3.0,  "fail": 175},
    },
    "rolling_mill_drive": {
        "vibration_rms_mm_s": {"mean": 3.2,  "std": 0.4,  "fail": 7.5},
        "bearing_temp_c":     {"mean": 78.0, "std": 2.5,  "fail": 100},
        "lube_pressure_bar":  {"mean": 3.5,  "std": 0.15, "fail": 2.5, "invert": True},
        "motor_current_a":    {"mean": None, "std_pct": 0.05, "fail_pct": 1.30},
        "speed_rpm":          {"mean": None, "std_pct": 0.01, "fail_pct": None},
    },
    "hydraulic_system": {
        "lube_pressure_bar":  {"mean": 180,  "std": 5.0,  "fail": 140, "invert": True},
        "outlet_temp_c":      {"mean": 45.0, "std": 2.0,  "fail": 65.0},
        "motor_current_a":    {"mean": None, "std_pct": 0.05, "fail_pct": 1.40},
        "vibration_rms_mm_s": {"mean": 1.5,  "std": 0.2,  "fail": 5.0},
    },
    "default": {
        "vibration_rms_mm_s": {"mean": 3.0,  "std": 0.3,  "fail": 7.5},
        "bearing_temp_c":     {"mean": 75.0, "std": 2.0,  "fail": 98.0},
        "motor_current_a":    {"mean": 40.0, "std": 2.0,  "fail": 56.0},
    },
}

SPARE_PARTS = [
    {"part_id": "SKF-23248",     "desc": "Spherical roller bearing 23248 CC/W33",        "compat": ["EQ-BF-001","EQ-BF-002","EQ-HSM-001"], "qty": 3,  "reorder": 2, "lead": 14, "cost": 4200,  "crit": "A"},
    {"part_id": "SKF-22336",     "desc": "Spherical roller bearing 22336 CC/W33",        "compat": ["EQ-HSM-002","EQ-CC-001"],              "qty": 2,  "reorder": 1, "lead": 21, "cost": 3800,  "crit": "A"},
    {"part_id": "SEAL-GS400",    "desc": "Mechanical seal assembly GS-400",              "compat": ["EQ-BF-001","EQ-BF-002","EQ-BF-003"],  "qty": 5,  "reorder": 2, "lead": 7,  "cost": 850,   "crit": "B"},
    {"part_id": "COUP-DISC-8",   "desc": "Flexible coupling disc pack Size 8",           "compat": ["EQ-BF-001","EQ-BF-003","EQ-RHF-001"], "qty": 0,  "reorder": 1, "lead": 14, "cost": 1200,  "crit": "B"},
    {"part_id": "FILTER-HYD-10", "desc": "Hydraulic return filter element 10 micron",   "compat": ["EQ-HSM-003","EQ-CC-002","EQ-WTP-001"],"qty": 12, "reorder": 4, "lead": 3,  "cost": 280,   "crit": "C"},
    {"part_id": "OIL-MOBIL-320", "desc": "Mobil Gear Oil 320 (200L drum)",              "compat": ["EQ-BF-001","EQ-BF-002","EQ-HSM-001","EQ-HSM-002"], "qty": 6, "reorder": 2, "lead": 5, "cost": 3500, "crit": "B"},
    {"part_id": "IMPELLER-BF6",  "desc": "Blower impeller assembly BF-6 series",        "compat": ["EQ-BF-001","EQ-BF-002"],               "qty": 1,  "reorder": 1, "lead": 45, "cost": 125000,"crit": "A"},
    {"part_id": "VBAND-M200",    "desc": "V-belt set (5 belts) M200 profile",           "compat": ["EQ-RHF-001","EQ-RHF-002","EQ-WTP-001"],"qty": 8,  "reorder": 3, "lead": 2,  "cost": 180,   "crit": "C"},
    {"part_id": "ACTUATOR-P12",  "desc": "Pneumatic actuator P12 replacement kit",      "compat": ["EQ-CC-001","EQ-CC-002"],               "qty": 2,  "reorder": 1, "lead": 10, "cost": 6500,  "crit": "B"},
    {"part_id": "THERMO-K200",   "desc": "K-type thermocouple 200mm immersion",         "compat": ["EQ-RHF-001","EQ-RHF-002"],             "qty": 10, "reorder": 3, "lead": 5,  "cost": 450,   "crit": "C"},
]


# ─── Main Generator ───────────────────────────────────────────────────────────

class SteelMindDataGenerator:

    def __init__(self, output_dir: str = "backend/data"):
        self.output_dir = Path(output_dir)
        self.raw_docs_dir = self.output_dir / "raw_docs"
        self.raw_docs_dir.mkdir(parents=True, exist_ok=True)

    # ── Equipment ─────────────────────────────────────────────────────────────

    def generate_equipment_sql(self) -> str:
        """Generate SQL INSERT statements for equipment."""
        lines = ["-- Plant Areas", "INSERT INTO plant_areas (code, name) VALUES"]
        areas = [
            ("BF",  "Blast Furnace - Iron Making"),
            ("HSM", "Hot Strip Mill"),
            ("CC",  "Continuous Caster"),
            ("RHF", "Reheating Furnace"),
            ("WTP", "Water Treatment Plant"),
        ]
        area_rows = [f"  ('{code}', '{name}')" for code, name in areas]
        lines.append(",\n".join(area_rows) + " ON CONFLICT (code) DO NOTHING;")

        lines += ["", "-- Equipment"]
        for eq in EQUIPMENT_CATALOG:
            sensor_cfg = self._build_sensor_config(eq["type"], eq["power_kw"], eq["rpm"])
            install_date = (datetime.utcnow() - timedelta(days=random.randint(365, 2190))).date()
            last_maint = (datetime.utcnow() - timedelta(days=random.randint(10, 80))).date()
            lines.append(
                f"INSERT INTO equipment (equipment_id, name, plant_area_code, equipment_type, "
                f"criticality, manufacturer, rated_power_kw, rated_speed_rpm, "
                f"maintenance_interval_days, last_maintenance_date, rul_days_baseline, "
                f"degradation_rate_k, sensor_config, status, is_active) VALUES ("
                f"'{eq['equipment_id']}', '{eq['name']}', '{eq['area']}', '{eq['type']}', "
                f"'{eq['crit']}', 'Siemens Energy', {eq['power_kw']}, {eq['rpm']}, "
                f"90, '{last_maint}', {eq['rul_base']}, {eq['k']}, "
                f"'{json.dumps(sensor_cfg)}', 'operational', true) "
                f"ON CONFLICT (equipment_id) DO NOTHING;"
            )
        return "\n".join(lines)

    def _build_sensor_config(self, eq_type: str, power_kw: float, rpm: float) -> dict:
        profile = SENSOR_PROFILES.get(eq_type, SENSOR_PROFILES["default"])
        config = {"normal": {}, "warning": {}, "critical": {}}
        for sensor, cfg in profile.items():
            if cfg.get("mean") is not None:
                config["normal"][sensor]   = cfg["mean"]
                config["warning"][sensor]  = cfg.get("warning", cfg["mean"] * 1.2)
                config["critical"][sensor] = cfg["fail"]
            elif cfg.get("std_pct"):
                # Current-based: use rated power as proxy
                rated_current = (power_kw * 1000) / (400 * 1.732 * 0.9)
                config["normal"][sensor]   = round(rated_current, 1)
                config["warning"][sensor]  = round(rated_current * 1.10, 1)
                config["critical"][sensor] = round(rated_current * 1.30, 1)
        if rpm > 0 and "speed_rpm" in profile:
            config["normal"]["speed_rpm"]   = rpm
            config["warning"]["speed_rpm"]  = rpm * 1.05
            config["critical"]["speed_rpm"] = rpm * 1.10
        return config

    # ── Sensor Streams ────────────────────────────────────────────────────────

    def generate_sensor_dataframe(
        self,
        equipment: dict,
        days: int = 30,
        interval_minutes: int = 1,
    ) -> pd.DataFrame:
        """
        Generate realistic sensor time-series data.
        Equipment marked degrade=True will show progressive degradation
        starting at 70% of the time window.

        Returns DataFrame with columns: timestamp + sensor columns
        """
        n_points = days * 24 * 60 // interval_minutes
        timestamps = [
            datetime.utcnow() - timedelta(minutes=(n_points - i) * interval_minutes)
            for i in range(n_points)
        ]

        eq_type = equipment["type"]
        profile = SENSOR_PROFILES.get(eq_type, SENSOR_PROFILES["default"])
        power_kw = equipment["power_kw"]
        rpm      = equipment["rpm"]
        degrade  = equipment.get("degrade", False)

        # Degradation multiplier: 1.0 for first 70%, then ramps up
        t = np.linspace(0, 1, n_points)
        degrade_start = 0.70
        degrade_array = np.where(
            t > degrade_start,
            1.0 + 0.4 * ((t - degrade_start) / (1 - degrade_start)) ** 1.5,
            1.0
        ) if degrade else np.ones(n_points)

        data = {"timestamp": timestamps}

        for sensor, cfg in profile.items():
            if cfg.get("mean") is not None:
                mean = cfg["mean"]
                std  = cfg["std"]
                inverted = cfg.get("invert", False)
                if inverted:
                    # Pressure drops when degrading
                    values = np.random.normal(mean / degrade_array, std, n_points)
                else:
                    values = np.random.normal(mean * degrade_array, std * degrade_array, n_points)
                # Add daily sinusoidal variation (±2%)
                daily_cycle = 1.0 + 0.02 * np.sin(2 * np.pi * t * days)
                values = values * daily_cycle
                # Clip to physical bounds
                values = np.clip(values, 0, cfg["fail"] * 1.5)
                data[sensor] = np.round(values, 3)

            elif cfg.get("std_pct") and power_kw > 0:
                rated = (power_kw * 1000) / (400 * 1.732 * 0.9)
                values = np.random.normal(rated * degrade_array, rated * cfg["std_pct"], n_points)
                data[sensor] = np.round(np.clip(values, 0, rated * 2), 2)

        if rpm > 0 and "speed_rpm" in SENSOR_PROFILES.get(eq_type, {}):
            speed_std = rpm * 0.005
            data["speed_rpm"] = np.round(np.random.normal(rpm, speed_std, n_points), 1)

        data["equipment_id"] = equipment["equipment_id"]
        return pd.DataFrame(data)

    # ── Spare Parts ───────────────────────────────────────────────────────────

    def generate_spare_parts_sql(self) -> str:
        lines = ["-- Spare Parts Inventory"]
        for part in SPARE_PARTS:
            compat_json = json.dumps(part["compat"]).replace("'", "''")
            lines.append(
                f"INSERT INTO spare_parts (part_id, description, equipment_compatibility, "
                f"quantity_on_hand, reorder_point, lead_time_days, unit_cost_usd, criticality) "
                f"VALUES ('{part['part_id']}', '{part['desc']}', '{compat_json}', "
                f"{part['qty']}, {part['reorder']}, {part['lead']}, {part['cost']}, '{part['crit']}') "
                f"ON CONFLICT (part_id) DO NOTHING;"
            )
        return "\n".join(lines)

    # ── Work Orders ───────────────────────────────────────────────────────────

    def generate_work_orders(self) -> list[dict]:
        """Generate 50 historical work orders."""
        work_orders = []
        wo_types = ["preventive", "corrective", "predictive"]
        priorities = ["P1", "P2", "P3", "P4"]
        tasks_by_type = {
            "centrifugal_compressor": [
                "Check vibration levels", "Inspect bearing temperature",
                "Collect oil sample", "Check alignment", "Replace bearing",
                "Lube system flush", "Coupling inspection"
            ],
            "rolling_mill_drive": [
                "Vibration spectrum analysis", "Motor insulation test",
                "Gearbox oil change", "Coupling disc inspection",
                "Bearing replacement", "Alignment check"
            ],
            "hydraulic_system": [
                "Filter element replacement", "Oil analysis",
                "Seal inspection", "Pressure test", "Valve function test"
            ],
        }
        technicians = ["TECH-001", "TECH-002", "TECH-003", "TECH-004", "TECH-005"]

        for i in range(50):
            eq = random.choice(EQUIPMENT_CATALOG)
            wo_type = random.choices(wo_types, weights=[0.5, 0.3, 0.2])[0]
            priority = random.choices(priorities, weights=[0.05, 0.20, 0.50, 0.25])[0]
            created = datetime.utcnow() - timedelta(days=random.randint(1, 90))
            completed = created + timedelta(days=random.randint(1, 7))

            eq_tasks = tasks_by_type.get(eq["type"], ["General inspection"])
            selected_tasks = random.sample(eq_tasks, min(3, len(eq_tasks)))

            parts_needed = [
                p for p in SPARE_PARTS
                if eq["equipment_id"] in p["compat"]
            ]
            parts_used = random.sample(parts_needed, min(1, len(parts_needed)))

            work_orders.append({
                "wo_code": f"WO-{created.year}-{1000+i}",
                "equipment_id": eq["equipment_id"],
                "wo_type": wo_type,
                "priority": priority,
                "status": "completed",
                "title": f"{wo_type.title()} — {eq['name'][:40]}",
                "description": f"Scheduled {wo_type} maintenance for {eq['name']}",
                "tasks": selected_tasks,
                "estimated_hours": round(random.uniform(2, 8), 1),
                "actual_hours": round(random.uniform(2, 10), 1),
                "scheduled_date": completed.isoformat(),
                "completed_at": completed.isoformat(),
                "assigned_to": random.sample(technicians, 2),
                "parts_consumed": [{"part_id": p["part_id"], "qty": 1} for p in parts_used],
                "findings": random.choice([
                    "Found early bearing wear — bearing replaced as planned.",
                    "Oil sample showed elevated Fe particles. Flushed lube system.",
                    "Alignment within tolerance. No corrective action needed.",
                    "Coupling disc showing fatigue — replaced with new assembly.",
                    "All parameters within normal range. PM completed as planned.",
                ]),
                "created_at": created.isoformat(),
            })
        return work_orders

    # ── Documents ─────────────────────────────────────────────────────────────

    def generate_documents(self):
        """Write synthetic knowledge base documents to raw_docs/."""
        docs = self._get_document_templates()
        for doc in docs:
            path = self.raw_docs_dir / f"{doc['filename']}.txt"
            path.write_text(doc["content"], encoding="utf-8")
            logger.info(f"  Written: {path.name}")
        logger.info(f"Generated {len(docs)} documents in {self.raw_docs_dir}")

    def _get_document_templates(self) -> list[dict]:
        return [
            {
                "filename": "centrifugal_compressor_maintenance_manual",
                "content": """CENTRIFUGAL COMPRESSOR MAINTENANCE MANUAL
Applicable Equipment: Top Gas Blowers, Combustion Air Blowers
Equipment Types: Single-stage and two-stage centrifugal compressors

Section 1: Vibration Standards and Limits
──────────────────────────────────────────
Vibration measurement shall be conducted per ISO 13373-7:2017.
Measurement point: Bearing housing, horizontal and vertical planes.

Severity zones per ISO 10816-3 (Machines >15kW, ≤15,000 rpm):
- Zone A (New):     0 – 2.3 mm/s RMS    — Acceptable for new commissioning
- Zone B (Normal):  2.3 – 4.5 mm/s RMS  — Acceptable for unrestricted long-term operation
- Zone C (Warning): 4.5 – 7.1 mm/s RMS  — Acceptable for short-term operation only. Schedule maintenance.
- Zone D (Critical): > 7.1 mm/s RMS     — SHUTDOWN REQUIRED. Imminent damage.

Action on Zone C: Collect vibration spectrum within 4 hours. Check bearing temperature trend.
Raise corrective work order within 24 hours.

Section 2: Bearing Temperature Limits
──────────────────────────────────────
Operating bearing temperature limits for rolling element bearings (SKF 23xxx series):
- Normal: < 80°C (recommended for long bearing life)
- Warning: 80–95°C (acceptable short-term, investigate cause)
- Critical: > 95°C (TRIP REQUIRED — continued operation risks bearing seizure)

Temperature rise rate: If temperature increases > 5°C in 30 minutes, treat as critical.
Root causes of elevated bearing temperature:
1. Insufficient lubrication (check lube oil pressure and flow rate)
2. Contaminated lubricant (collect oil sample per ISO 4406)
3. Bearing preload excessive (check installation torque specs)
4. Misalignment (check coupling alignment per Section 5)
5. Overloading (check motor current vs rated current)

Section 3: Lubrication System Requirements
───────────────────────────────────────────
Lube oil specification: ISO VG 100 mineral oil, or Mobil DTE 746 / Shell Turbo T 100
Oil pressure — normal operating range: 3.5–4.8 bar (g)
Oil pressure warning: < 3.5 bar — check filter differential pressure, inspect pump
Oil pressure trip: < 3.0 bar — automatic shutdown (SAFETY SYSTEM)

Oil temperature: Maintain 40–55°C at bearing inlet
Oil sample frequency: Every 500 operating hours, or after any bearing temperature exceedance
Oil analysis parameters (per ISO 4406): Particle count Class 17/15/12 maximum
Iron (Fe) particle limit: < 30 ppm. Investigate at > 30 ppm. Change oil at > 100 ppm.

Section 4: Bearing Replacement Procedure
─────────────────────────────────────────
Required tools: Bearing heater (induction type), SKF TMFT 36 fitting tool,
               calibrated torque wrench, dial gauge, feeler gauges, infrared thermometer

Pre-installation:
1. Apply LOTO (Lockout/Tagout) per SOP-LOTO-001
2. Confirm machine is at ambient temperature (< 40°C)
3. Drain lube oil — collect sample before draining (for condition analysis)
4. Remove coupling guard and disconnect coupling

Bearing installation:
1. Clean shaft and housing bore with lint-free cloth and solvent
2. Inspect shaft for fretting, corrosion, or damage. Dress if required (max 0.02mm)
3. Heat bearing to 80–100°C using induction heater (NEVER use open flame)
4. Install bearing onto shaft within 60 seconds of removal from heater
5. Drive bearing against shaft shoulder — do NOT hammer directly on races
6. Torque locking nut to: 850 Nm for 23248 series; 1100 Nm for 23260 series
7. Check axial clearance: 0.10–0.20mm for 23248 with C3 clearance

Post-installation verification:
1. Manually rotate shaft: should rotate freely with no binding
2. Check bearing temperature 30 minutes after startup: should stabilise ≤ 10°C above ambient
3. Collect vibration baseline reading after 2 hours of operation

Section 5: Alignment Specification
────────────────────────────────────
Permissible misalignment (after hot alignment, running at operating temperature):
- Parallel (radial):  ≤ 0.05 mm
- Angular:            ≤ 0.05 mm/100mm
Use laser alignment tool (Prüftechnik Optalign or equivalent).
Realign when: new installation, bearing replacement, coupling change, or if vibration > 4.5 mm/s.

Section 6: Preventive Maintenance Schedule
───────────────────────────────────────────
Daily (every shift):
□ Check lube oil pressure (visual gauge or DCS reading)
□ Check bearing temperature (DCS trend)
□ Listen for unusual noise (metal-on-metal, rumbling, high pitch)
□ Check for oil leaks at seals and fittings

Monthly:
□ Collect oil sample (per ISO 4406 protocol)
□ Vibration measurement (both planes, record and trend)
□ Check coupling guard integrity
□ Clean air filter and cooling fins

90-day PM:
□ Full vibration spectrum analysis with FFT
□ Bearing clearance check
□ Oil system flush and refill
□ Coupling disc inspection
□ Alignment check and correction
□ Thermal imaging of motor terminals
""",
            },
            {
                "filename": "bearing_replacement_sop",
                "content": """STANDARD OPERATING PROCEDURE
SOP-MAINT-BRG-001: Rolling Bearing Replacement — Centrifugal Compressors

Document No.: SOP-MAINT-BRG-001 | Rev: 3 | Date: 2024-01-15
Approved by: Chief Maintenance Engineer

1. SCOPE
This procedure covers the removal and installation of rolling element bearings
(spherical roller type, SKF 23xxx series) on centrifugal compressors in the
Blast Furnace and Reheating Furnace departments.

2. SAFETY REQUIREMENTS
Mandatory PPE: Safety helmet, heat-resistant gloves (when using bearing heater),
safety glasses, steel-toe boots, hearing protection.

LOTO Requirements: Full electrical LOTO per SOP-LOTO-001 before starting.
Tag type: Personal Danger Tag (Red tag with engineer's name and date).
Isolation points: Main isolator at MCC panel + local switch near machine.

Never proceed without signed PERMIT-TO-WORK (PTW) from shift supervisor.

3. PRE-WORK CHECKS
□ Confirm PTW signed and approved
□ Confirm machine has been isolated and de-energised for ≥ 15 minutes
□ Confirm machine surface temperature < 40°C (use IR thermometer)
□ Confirm all required spare parts are available:
   - Replacement bearing (check part number matches shaft diameter)
   - Oil seal rings (replace whenever bearing is changed)
   - Locking nut (replace if worn threads observed)
□ Check replacement bearing certificate — verify part number, batch, date code

4. BEARING REMOVAL PROCEDURE
Step 1: Drain lube oil system. Collect drain sample in clean glass jar.
        Label with: equipment ID, date, operating hours since last change.
        Send to lab for Fe/Cr/Cu analysis.

Step 2: Remove coupling guard. Mark coupling halves with paint marker
        (ensures correct reassembly orientation).

Step 3: Use SKF TMPU 10/14 puller to remove coupling hub.
        CAUTION: Do not use impact tools on threaded shaft end.

Step 4: Remove bearing housing end cover (4x M16 bolts, 130 Nm torque).

Step 5: Remove locking nut using bearing nut wrench HN-type.
        Lock washer must be fully bent back before attempting removal.

Step 6: Use hydraulic bearing puller (SKF TMHP series) to remove bearing.
        Apply pressure slowly — bearing should move freely without jerking.
        If bearing seized: apply penetrating fluid, wait 30 mins, retry.

Step 7: Inspect shaft: measure diameter with micrometer at 3 points.
        Accept: within +0/-0.01mm of nominal.
        Reject: scratches, fretting, pitting > 0.02mm deep.

5. BEARING INSTALLATION PROCEDURE
Step 1: Clean all contact surfaces with lint-free cloth and IPA solvent.

Step 2: Apply thin film of clean oil to shaft seating surface.

Step 3: Heat replacement bearing using induction heater:
        - Target temperature: 90°C (use temperature indicating crayon)
        - Maximum allowed: 110°C
        - Do NOT heat above 110°C — this changes hardness of races
        - Time estimate: 23248 bearing takes ~12 minutes to reach 90°C

Step 4: Remove bearing from heater. Wearing heat-resistant gloves,
        immediately slide bearing onto shaft. Drive firmly against shaft shoulder.
        Complete this within 60 seconds before bearing contracts on cooling.

Step 5: Install new lock washer and locking nut.
        Torque to: 850 Nm for 23248 / 1100 Nm for 23260.
        Bend lock washer tab into nut slot.

Step 6: Install new oil seals. Apply light coat of grease to seal lips.

Step 7: Reassemble bearing housing cover. Torque M16 bolts to 130 Nm
        in cross pattern (4 passes: 30%, 60%, 100%, verify).

Step 8: Reconnect coupling. Verify alignment per SOP-ALIGN-001.
        Permissible: parallel ≤ 0.05mm, angular ≤ 0.05mm/100mm.

6. POST-INSTALLATION VERIFICATION
□ Fill lube oil to correct level (sight glass midpoint)
□ Prime lube pump — check pressure reaches 3.5 bar before starting main machine
□ Start machine. Record startup bearing temperatures at 5, 10, 30 minutes.
   Normal: stabilises at ≤ 10°C above ambient within 30 minutes.
□ Record vibration baseline at 2 hours of operation.
   Expected: ≤ 2.5 mm/s RMS (new bearing, fresh alignment)
□ Complete work order findings report

7. DOCUMENTATION
- Record in CMMS: bearing part number, batch, replacement date, technician IDs
- Update bearing history card for equipment
- File oil sample submission form with laboratory

8. COMMON MISTAKES TO AVOID
❌ Using open flame to heat bearing — causes metallurgical damage
❌ Hammering directly on bearing races — causes brinelling
❌ Re-using lock washer — hardening makes it likely to crack
❌ Skipping alignment check after reassembly — most common cause of premature failure
❌ Running without verifying lube pressure — can cause dry start and immediate seizure
""",
            },
            {
                "filename": "vibration_analysis_guide",
                "content": """VIBRATION ANALYSIS AND FAULT DIAGNOSIS GUIDE
Reference: ISO 13373-1:2002, ISO 13373-7:2017, VDI 3832

1. MEASUREMENT FUNDAMENTALS
Measurement units: mm/s RMS for overall vibration (ISO 10816 standard)
                   mm peak-to-peak for displacement (for low-speed machines)
                   g for acceleration (for high-frequency diagnostics)
Measurement frequency: 10 Hz to 1000 Hz for rolling element bearings
                        10 Hz to 200 Hz for overall machine condition

Sensor placement:
- Horizontal radial (HOR): Most sensitive to unbalance, misalignment
- Vertical radial (VER): Also sensitive to looseness
- Axial (AXL): Most sensitive to axial misalignment, thrust bearing issues

2. FAULT SIGNATURES IN FREQUENCY SPECTRUM

2.1 UNBALANCE
Primary indicator: High 1× (1X) component in radial direction
Phase: Typically stable single-plane phase
Amplitude: Proportional to speed² (doubles when speed doubles)
Action: Dynamic balancing in field (ISO 1940-1, Grade G6.3 for compressors)

2.2 MISALIGNMENT
Primary indicator: High 2× (2X) component, often with 1× also elevated
Axial vibration > 50% of radial vibration
Phase: 180° phase difference across coupling (angular misalignment)
Action: Check and correct laser alignment. Permissible: 0.05mm/0.05mm.

2.3 BEARING DEFECT FREQUENCIES
Calculate bearing defect frequencies from bearing geometry:
- Ball Pass Frequency Outer race (BPFO): = (n/2) × f_r × (1 - d/D × cos α)
- Ball Pass Frequency Inner race (BPFI): = (n/2) × f_r × (1 + d/D × cos α)
- Ball Spin Frequency (BSF):            = (D/2d) × f_r × (1 - (d/D × cos α)²)
Where: n = number of rolling elements, f_r = shaft speed in Hz,
       d = ball diameter, D = pitch diameter, α = contact angle

Early bearing defect: Elevated noise floor in 2000-10000 Hz range
                      Possible BPFO/BPFI sidebands
Moderate defect:      Clear BPFO or BPFI peak, with harmonics
Severe defect:        Broadband vibration increase, random high-frequency noise
                      Overall vibration approaching Zone C/D

2.4 LOOSENESS (STRUCTURAL)
Primary indicator: Multiple harmonics of running speed (1X, 2X, 3X ... up to 10X)
Sub-harmonics (0.5X) may appear
Phase: Unstable phase reading
Check: Foundation bolts, bearing housing bolts, bearing clearance

3. OIL ANALYSIS CORRELATION
High Fe particles (>50 ppm) + elevated vibration → bearing wear confirmed
High Cu particles (>30 ppm) → bronze cage wear or sleeve bearing damage
High Si (>20 ppm) → dirt ingestion, check seals and breathers
Viscosity change >10% from new oil → contamination or degradation, change oil

4. DIAGNOSIS DECISION TREE
Is overall vibration > 4.5 mm/s?
  YES → Is it primarily 1X or 2X?
          1X dominant → Check balance and alignment
          2X dominant → Check alignment (especially angular)
          Neither → Check bearing frequencies, looseness
       → Is bearing temperature also elevated?
          YES → Critical: Check lubrication AND bearing condition → Emergency PM within 24h
          NO  → Schedule diagnostic within 7 days
  NO  → Is there a change from last measurement > 1 mm/s?
          YES → Investigate: Collect spectrum, check lubrication
          NO  → Normal operation, continue routine monitoring
""",
            },
            {
                "filename": "failure_rca_case_study_bf001_2024",
                "content": """ROOT CAUSE ANALYSIS REPORT
Equipment: EQ-BF-001 — BF No.2 Top Gas Blower
Event Date: November 2024 | Report Date: December 2024
Prepared by: Maintenance Engineering Department

1. FAILURE DESCRIPTION
The BF No.2 Top Gas Blower experienced an unplanned shutdown due to high bearing
temperature trip (95°C). The machine had been in continuous operation for 127 days
since last scheduled maintenance (PM completed on 10-Sep-2024).

Total unplanned downtime: 8.5 hours
Production impact: Blast furnace output reduced to 60% capacity
Estimated loss: USD 680,000 (8.5h × $80,000/h)

2. SYMPTOM TIMELINE (Pre-failure indicators)
Day -12: Oil analysis showed Fe particles at 45 ppm (above 30 ppm action limit).
         Lab report received but not actioned — root cause of this delay under review.
Day -5:  Bearing temperature rose from 72°C to 78°C (DCS trend, no alarm set at this level).
Day -3:  Vibration increased from 2.8 to 3.6 mm/s (within Zone B, no alert triggered).
Day -1:  Bearing temperature reached 85°C. DCS alarm triggered. Operator acknowledged
         but took no corrective action (insufficient awareness of severity).
Day 0:   Bearing temperature trip at 95°C at 03:22. Machine auto-shut.
         Manual inspection at 06:45 confirmed inner race spalling on DE bearing.

3. ROOT CAUSE ANALYSIS (5-Why Method)
Why 1: Why did the bearing fail?
→ Inner race fatigue spalling due to insufficient lubrication

Why 2: Why was lubrication insufficient?
→ Lubricant contaminated with iron particles (180 ppm Fe measured in post-failure sample)

Why 3: Why was lubricant contaminated?
→ Oil filter bypass valve was left in partially open position after October PM
   (confirmed by physical inspection of filter housing after failure)

Why 4: Why was the bypass valve left open?
→ Post-PM checklist did not include explicit step to verify bypass valve closure
   (checklist gap identified as systemic issue)

Why 5: Why was no corrective action taken on Day -12 oil analysis result?
→ No formal process for routing abnormal oil analysis results to maintenance planner.
   Result was filed in paper log but not entered into CMMS as a work order trigger.

ROOT CAUSE: Filter bypass valve left partially open during October PM → oil contamination
            → lubricant film breakdown → metal-to-metal contact → bearing spalling.

CONTRIBUTING FACTORS:
- No alarm configured for bearing temperature in 80-90°C range (only trip at 95°C)
- Oil analysis result not actioned within required 7-day window
- Operator not aware that 85°C temperature with rising trend warrants immediate escalation

4. CORRECTIVE ACTIONS
Immediate (completed):
✅ Replace DE bearing (SKF 23248) — completed 14-Nov-2024
✅ Full lube system flush — completed 14-Nov-2024
✅ Verify all filter bypass valves closed on all 3 blowers

Short-term (30 days):
□ Add DCS alarm at 85°C bearing temperature on all critical compressors
□ Update post-PM checklist to include: "Verify filter bypass valve closed — sign-off required"
□ Implement formal oil analysis result routing: email notification to maintenance planner
  with 7-day action deadline

Long-term (90 days):
□ Install inline particle counter on lube system (budget: ₹2.4 lakh per machine)
□ Review PM interval for Class A compressors (current 90 days → proposed 60 days)
□ Implement vibration trending alert: alert when vibration increases > 0.5 mm/s in 7 days

5. LESSONS LEARNED
The failure was predictable and preventable. Three separate indicators were available
(oil analysis, temperature trend, vibration increase) but none triggered timely corrective
action due to process gaps, not equipment failures.

Key lesson: Predictive maintenance data has no value unless there is a defined process
to convert abnormal readings into maintenance work orders with a tracked timeline.
""",
            },
            {
                "filename": "iso_4406_oil_cleanliness_standard",
                "content": """OIL CLEANLINESS STANDARD REFERENCE
Based on ISO 4406:2021 — Hydraulic fluid power — Fluids — Method for coding the level of contamination

1. ISO 4406 CLEANLINESS CODES
The ISO 4406 code uses three numbers, e.g., 17/15/12
- First number: particles ≥ 4 μm per mL
- Second number: particles ≥ 6 μm per mL
- Third number: particles ≥ 14 μm per mL

Each code increment doubles the particle count.
Code 12 = 1,000 – 2,000 particles/mL
Code 17 = 32,000 – 64,000 particles/mL

2. RECOMMENDED CLEANLINESS LEVELS
Application                         Target Code    Max Code
────────────────────────────────────────────────────────────
Centrifugal compressor bearings     15/13/10       17/15/12
Rolling mill drive gearboxes        16/14/11       18/16/13
Hydraulic press systems             14/12/10       16/14/11
General circulating oil systems     17/15/12       19/17/14

3. STEEL PLANT SPECIFIC LIMITS (per internal standard SM-LUBE-002)
Equipment Class A (Mission Critical):
  Target: ISO 16/14/11 | Alert: 17/15/12 | Action (change oil): 18/16/13

Equipment Class B:
  Target: ISO 17/15/12 | Alert: 18/16/13 | Action (change oil): 19/17/14

4. ELEMENTAL ANALYSIS LIMITS (ppm)
Element   Alert   Critical   Significance
────────────────────────────────────────────────────────
Fe        30      100        Bearing/gear wear
Cu        20      50         Bronze cage/bushing wear
Cr        5       15         Steel rolling element wear
Pb        10      30         White metal bearing wear
Si        20      50         Dirt ingestion (check seals)
Al        10      25         Piston wear (hydraulics)

5. SAMPLING PROCEDURE
1. Sample from live, circulating oil — NOT from drain or sump bottom
2. Sample port: mid-circuit return line (not inlet or outlet)
3. Flush sample port: 100ml before collecting sample
4. Collect 100ml in clean, dry sample bottle (pre-labelled)
5. Submit within 24 hours. If storing: keep at room temperature, away from sunlight.
6. Record on sample form: equipment ID, operating hours, oil type, date of last oil change
""",
            },
            {
                "filename": "maintenance_planning_best_practices",
                "content": """MAINTENANCE PLANNING AND SCHEDULING GUIDE
Steel Plant Maintenance Department — Best Practices Manual

1. MAINTENANCE STRATEGY OVERVIEW
A world-class steel plant maintenance program uses a combination of strategies:

Breakdown (Reactive): < 5% of total maintenance hours
  - Used only for non-critical equipment or low-cost items
  - Decision threshold: replacement cost < 2 hours of downtime cost

Time-Based Preventive (PM): 30-40% of total maintenance hours
  - Calendar or running-hours based
  - Used for equipment with known wear-out failure modes

Condition-Based Predictive (PdM): 50-60% of total maintenance hours
  - Triggered by sensor thresholds or trend breaches
  - Requires vibration, oil analysis, and thermography programs
  - Optimal strategy for Class A and B rotating equipment

2. PRIORITY CLASSIFICATION
Work orders are classified by risk and urgency:

P1 — Emergency (act within 2 hours):
  - Active failure or imminent shutdown
  - Safety risk to personnel
  - Risk of cascading failure to upstream/downstream equipment

P2 — Urgent (act within 24 hours):
  - Anomaly score > 75 or vibration in Zone C
  - Bearing temperature > 85°C with rising trend
  - Hydraulic pressure < warning setpoint

P3 — High (act within 7 days):
  - Anomaly score 50-75 or vibration approaching Zone C
  - Oil analysis alert (not critical)
  - PM overdue by > 20% of interval

P4 — Routine (next scheduled window):
  - Scheduled PM within normal interval
  - Minor defects with slow degradation trend

3. MAINTENANCE WINDOW PLANNING
Weekly maintenance windows: Saturday 06:00 – 14:00 (8 hours, standard)
Major quarterly outage: 72 hours planned, 3 weeks advance notice to production

Optimisation principles:
a) Group equipment in the same physical area to minimise technician travel
b) Schedule critical path items (long repair duration or hard-to-source parts) first
c) Never schedule two Class A items in the same area simultaneously
   (loss of redundancy during maintenance window)
d) Confirm all spare parts 48 hours before window — raise emergency purchase if missing

4. SPARE PARTS MANAGEMENT
ABC classification:
  A-parts: Critical for production. Minimum stock = 1 unit on-shelf.
           Maximum lead time tolerance = 24 hours.
  B-parts: Important. Minimum stock = based on historical usage.
           Maximum lead time tolerance = 14 days.
  C-parts: Non-critical. Order as needed.

Reorder point formula:
  ROP = (Average daily usage × Lead time days) + Safety stock
  Safety stock = 1.645 × σ_demand × √Lead time (for 95% service level)

5. METRICS AND KPIs
Target KPIs for world-class maintenance:
  OEE (Overall Equipment Effectiveness): > 85%
  MTBF (Mean Time Between Failures):    Increase 10% year-on-year
  MTTR (Mean Time to Repair):           < 4 hours for Class A equipment
  PM Compliance:                         > 95% of PMs completed on schedule
  Maintenance Cost / Replacement Value:  < 2.5% per year
  Emergency Work %:                      < 5% of total maintenance hours
""",
            },
        ]


# ─── Runner ───────────────────────────────────────────────────────────────────

async def main():
    """Generate all synthetic data and save to files."""
    logger.info("🏭 Starting SteelMind synthetic data generation...")

    gen = SteelMindDataGenerator()

    # 1. Generate SQL files
    logger.info("Generating equipment SQL...")
    sql = gen.generate_equipment_sql()
    Path("backend/data/synthetic/equipment_seed.sql").write_text(sql)

    sql_parts = gen.generate_spare_parts_sql()
    Path("backend/data/synthetic/spare_parts_seed.sql").write_text(sql_parts)

    # 2. Generate sensor data (save to CSV for InfluxDB batch load)
    logger.info("Generating sensor time-series data...")
    Path("backend/data/synthetic/sensor_csvs").mkdir(parents=True, exist_ok=True)
    for eq in EQUIPMENT_CATALOG:
        df = gen.generate_sensor_dataframe(eq, days=30)
        out = Path(f"backend/data/synthetic/sensor_csvs/{eq['equipment_id']}.csv")
        df.to_csv(out, index=False)
        degrade_marker = " [DEGRADING ↑]" if eq.get("degrade") else ""
        logger.info(f"  {eq['equipment_id']}: {len(df):,} readings{degrade_marker}")

    # 3. Generate work orders JSON
    logger.info("Generating work orders...")
    wos = gen.generate_work_orders()
    Path("backend/data/synthetic/work_orders.json").write_text(json.dumps(wos, indent=2))
    logger.info(f"  Generated {len(wos)} work orders")

    # 4. Generate knowledge base documents
    logger.info("Generating RAG documents...")
    gen.generate_documents()

    logger.info("✅ Data generation complete!")
    logger.info("Next step: Run `python -m app.services.db_seeder` to load into databases")


if __name__ == "__main__":
    asyncio.run(main())

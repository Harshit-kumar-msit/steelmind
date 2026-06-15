"""
Module: ai/llm/tool_executor.py
Purpose: Executes the tools the LLM decides to call.
         Each tool_name maps to a real backend service/DB call.
         Returns structured results that get fed back to the LLM as
         tool_result messages in the ReAct loop.

Design: All tools are async. Results are JSON-serialisable dicts.
        Errors are caught and returned as {"error": "..."} so the
        LLM can gracefully handle unavailable data.
"""
import json
from datetime import datetime
from typing import Any, Optional
from loguru import logger


class ToolExecutor:
    """
    Executes tool calls from the LLM agent loop.
    Injected with db session and service singletons at construction time.

    Usage:
        executor = ToolExecutor(db=db, equipment_id=ctx.equipment_id)
        result = await executor.execute("get_anomaly_detail", {"equipment_id": "EQ-BF-001"})
    """

    def __init__(self, db, default_equipment_id: str = ""):
        self.db = db
        self.default_equipment_id = default_equipment_id
        self._citations: list[dict] = []   # accumulated across all tool calls

    @property
    def citations(self) -> list[dict]:
        return self._citations

    async def execute(self, tool_name: str, args: dict) -> str:
        """
        Dispatch to the right tool handler.
        Returns a JSON string — fed back to LLM as tool_result content.
        """
        logger.debug(f"Tool call: {tool_name}({json.dumps(args)[:120]})")
        try:
            handlers = {
                "get_equipment_health":   self._get_equipment_health,
                "get_anomaly_detail":     self._get_anomaly_detail,
                "get_rul_breakdown":      self._get_rul_breakdown,
                "check_spare_parts":      self._check_spare_parts,
                "get_open_alerts":        self._get_open_alerts,
                "get_maintenance_logs":   self._get_maintenance_logs,
                "get_work_orders":        self._get_work_orders,
                "get_plant_priority_queue": self._get_plant_priority_queue,
                "create_work_order":      self._create_work_order,
                "add_maintenance_log":    self._add_maintenance_log,
                "search_knowledge_base":  self._search_knowledge_base,
            }
            handler = handlers.get(tool_name)
            if not handler:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

            result = await handler(**args)
            return json.dumps(result, default=str)

        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return json.dumps({"error": str(e), "tool": tool_name})

    # ── Tool Handlers ──────────────────────────────────────────────────────────

    async def _get_equipment_health(self, equipment_id: str) -> dict:
        from sqlalchemy import select
        from app.db.models import Equipment
        result = await self.db.execute(
            select(Equipment).where(Equipment.equipment_id == equipment_id)
        )
        eq = result.scalar_one_or_none()
        if not eq:
            return {"error": f"Equipment {equipment_id} not found"}
        return {
            "equipment_id":       eq.equipment_id,
            "name":               eq.name,
            "status":             eq.status,
            "criticality":        eq.criticality,
            "anomaly_score":      eq.current_anomaly_score,
            "rul_days":           eq.current_rul_days,
            "degradation_index":  eq.current_degradation_index,
            "priority_score":     eq.current_priority_score,
            "last_maintenance":   eq.last_maintenance_date.isoformat() if eq.last_maintenance_date else None,
            "last_updated":       eq.last_health_update.isoformat() if eq.last_health_update else None,
        }

    async def _get_anomaly_detail(
        self, equipment_id: str, equipment_type: str = ""
    ) -> dict:
        from app.ai.anomaly.detector import get_detector
        from app.services.influx_service import get_influx_service
        from sqlalchemy import select
        from app.db.models import Equipment

        # Get equipment type from DB if not provided
        if not equipment_type:
            result = await self.db.execute(
                select(Equipment).where(Equipment.equipment_id == equipment_id)
            )
            eq = result.scalar_one_or_none()
            equipment_type = eq.equipment_type if eq else "default"

        influx = get_influx_service()
        df = await influx.query_equipment_sensors(equipment_id, hours=1)
        if df.empty:
            return {"error": "No sensor data available", "equipment_id": equipment_id}

        detector = get_detector()
        r = detector.score(equipment_id, equipment_type, df.iloc[-1].to_dict(), df)

        return {
            "equipment_id":    r.equipment_id,
            "anomaly_score":   r.anomaly_score,
            "is_anomaly":      r.is_anomaly,
            "severity":        r.severity,
            "top_contributor": r.top_contributor,
            "sensor_values":   r.sensor_values,
            "z_scores":        r.z_scores,
            "contributions":   r.contributions,
            "note": (
                f"Top contributor is {r.top_contributor} with z-score "
                f"{r.z_scores.get(r.top_contributor, 0):.2f}σ above baseline"
            ),
        }

    async def _get_rul_breakdown(
        self, equipment_id: str, equipment_type: str = ""
    ) -> dict:
        from app.ai.prediction.rul_estimator import get_estimator
        from app.services.influx_service import get_influx_service
        from sqlalchemy import select
        from app.db.models import Equipment

        result = await self.db.execute(
            select(Equipment).where(Equipment.equipment_id == equipment_id)
        )
        eq = result.scalar_one_or_none()
        if not eq:
            return {"error": f"Equipment {equipment_id} not found"}

        influx = get_influx_service()
        df = await influx.query_equipment_sensors(equipment_id, hours=24)
        if df.empty:
            return {"rul_days": eq.current_rul_days, "note": "Using cached value — no live sensor data"}

        days_since_maint = 0
        if eq.last_maintenance_date:
            days_since_maint = (datetime.utcnow() - eq.last_maintenance_date).days

        estimator = get_estimator()
        r = estimator.estimate(
            equipment_id=equipment_id,
            equipment_type=equipment_type or eq.equipment_type,
            df=df,
            baseline_rul_days=eq.rul_days_baseline,
            degradation_rate_k=eq.degradation_rate_k,
            last_maintenance_days_ago=days_since_maint,
        )
        return {
            "equipment_id":        r.equipment_id,
            "rul_days":            r.rul_days,
            "rul_hours":           r.rul_hours,
            "degradation_index":   r.degradation_index,
            "confidence":          r.confidence,
            "warning_level":       r.warning_level,
            "trend_slope":         r.trend_slope,
            "trend_days_to_failure": r.trend_days_to_failure,
            "sensor_contributions": r.sensor_contributions,
            "notes":               r.notes,
        }

    async def _check_spare_parts(self, part_ids: list[str]) -> dict:
        from sqlalchemy import select
        from app.db.models import SparePart
        result = await self.db.execute(
            select(SparePart).where(SparePart.part_id.in_(part_ids))
        )
        parts = {p.part_id: p for p in result.scalars().all()}
        output = {}
        for pid in part_ids:
            if pid in parts:
                p = parts[pid]
                output[pid] = {
                    "description":      p.description,
                    "quantity_on_hand": p.quantity_on_hand,
                    "available":        p.quantity_on_hand > 0,
                    "reorder_point":    p.reorder_point,
                    "lead_time_days":   p.lead_time_days,
                    "unit_cost_usd":    p.unit_cost_usd,
                    "storage_location": p.storage_location,
                    "is_low_stock":     p.quantity_on_hand <= p.reorder_point,
                }
            else:
                output[pid] = {"available": False, "error": "Part not found in inventory"}
        return {"parts": output, "total_checked": len(part_ids)}

    async def _get_open_alerts(
        self, equipment_id: str = "", severity: str = ""
    ) -> dict:
        from sqlalchemy import select, and_
        from app.db.models import Alert, AlertStatus
        eq_id = equipment_id or self.default_equipment_id
        conditions = [Alert.status == AlertStatus.OPEN]
        if eq_id:
            conditions.append(Alert.equipment_id == eq_id)
        if severity:
            conditions.append(Alert.severity == severity)

        result = await self.db.execute(
            select(Alert).where(and_(*conditions)).order_by(Alert.created_at.desc()).limit(10)
        )
        alerts = result.scalars().all()
        return {
            "count": len(alerts),
            "alerts": [
                {
                    "alert_code":    a.alert_code,
                    "equipment_id":  a.equipment_id,
                    "severity":      a.severity,
                    "title":         a.title,
                    "description":   a.description[:200],
                    "anomaly_score": a.anomaly_score,
                    "rul_days":      a.rul_days,
                    "age_hours":     round((datetime.utcnow() - a.created_at).total_seconds() / 3600, 1),
                }
                for a in alerts
            ]
        }

    async def _get_maintenance_logs(
        self, equipment_id: str, limit: int = 5
    ) -> dict:
        from sqlalchemy import select, desc
        from app.db.logbook_model import MaintenanceLog
        result = await self.db.execute(
            select(MaintenanceLog)
            .where(MaintenanceLog.equipment_id == equipment_id)
            .order_by(desc(MaintenanceLog.created_at))
            .limit(min(limit, 20))
        )
        logs = result.scalars().all()
        return {
            "equipment_id": equipment_id,
            "count": len(logs),
            "logs": [
                {
                    "logged_by":  log.logged_by,
                    "log_type":   log.log_type,
                    "notes":      log.notes,
                    "timestamp":  log.created_at.isoformat(),
                }
                for log in logs
            ]
        }

    async def _get_work_orders(
        self, equipment_id: str = "", status: str = "", priority: str = ""
    ) -> dict:
        from sqlalchemy import select, and_
        from app.db.models import WorkOrder
        conditions = []
        if equipment_id: conditions.append(WorkOrder.equipment_id == equipment_id)
        if status:        conditions.append(WorkOrder.status == status)
        if priority:      conditions.append(WorkOrder.priority == priority)

        query = select(WorkOrder)
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(WorkOrder.created_at.desc()).limit(10)

        result = await self.db.execute(query)
        wos = result.scalars().all()
        return {
            "count": len(wos),
            "work_orders": [
                {
                    "wo_code":        w.wo_code,
                    "equipment_id":   w.equipment_id,
                    "title":          w.title,
                    "priority":       w.priority,
                    "status":         w.status,
                    "wo_type":        w.wo_type,
                    "estimated_hours":w.estimated_hours,
                    "scheduled_date": w.scheduled_date.isoformat() if w.scheduled_date else None,
                    "tasks":          w.tasks,
                }
                for w in wos
            ]
        }

    async def _get_plant_priority_queue(
        self, top_n: int = 5, criticality: str = ""
    ) -> dict:
        from sqlalchemy import select
        from app.db.models import Equipment
        query = select(Equipment).where(
            Equipment.is_active == True,
            Equipment.current_priority_score.isnot(None)
        )
        if criticality:
            query = query.where(Equipment.criticality == criticality)
        query = query.order_by(Equipment.current_priority_score.desc()).limit(min(top_n, 20))

        result = await self.db.execute(query)
        equipment_list = result.scalars().all()
        return {
            "count": len(equipment_list),
            "priority_queue": [
                {
                    "rank":            i + 1,
                    "equipment_id":    eq.equipment_id,
                    "name":            eq.name,
                    "criticality":     eq.criticality,
                    "priority_score":  eq.current_priority_score,
                    "anomaly_score":   eq.current_anomaly_score,
                    "rul_days":        eq.current_rul_days,
                    "status":          eq.status,
                }
                for i, eq in enumerate(equipment_list)
            ]
        }

    async def _create_work_order(
        self,
        equipment_id: str,
        title: str,
        priority: str,
        wo_type: str,
        tasks: list[str] = None,
        estimated_hours: float = 4.0,
    ) -> dict:
        from app.db.models import WorkOrder, WorkOrderStatus
        wo_code = f"WO-{datetime.utcnow().year}-AI{datetime.utcnow().strftime('%m%d%H%M%S')}"
        wo = WorkOrder(
            wo_code=wo_code,
            equipment_id=equipment_id,
            wo_type=wo_type,
            priority=priority,
            status=WorkOrderStatus.OPEN,
            title=title,
            tasks=tasks or [],
            estimated_hours=estimated_hours,
            ai_generated=True,
            created_by="ai_agent",
        )
        self.db.add(wo)
        await self.db.flush()
        return {
            "created": True,
            "wo_code": wo_code,
            "equipment_id": equipment_id,
            "priority": priority,
            "title": title,
            "message": f"Work order {wo_code} created successfully with priority {priority}",
        }

    async def _add_maintenance_log(
        self, equipment_id: str, log_type: str, notes: str
    ) -> dict:
        from app.db.logbook_model import MaintenanceLog
        log = MaintenanceLog(
            equipment_id=equipment_id,
            logged_by="ai_agent",
            log_type=log_type,
            notes=notes,
        )
        self.db.add(log)
        await self.db.flush()
        return {
            "logged": True,
            "equipment_id": equipment_id,
            "log_type": log_type,
            "message": f"Log entry recorded for {equipment_id}",
        }

    async def _search_knowledge_base(
        self, query: str, equipment_id: str = "", doc_category: str = ""
    ) -> dict:
        from app.ai.rag.retriever import get_retriever
        retriever = get_retriever()
        chunks = retriever.retrieve(
            query=query,
            equipment_id=equipment_id,
            doc_category=doc_category or "",
            top_k=5,
        )
        # Accumulate citations for the response
        self._citations.extend(retriever.get_citations(chunks))

        return {
            "query": query,
            "results_found": len(chunks),
            "context": retriever.format_context(chunks),
            "citations": [
                {
                    "chunk_id": c.chunk_id,
                    "title":    c.title,
                    "category": c.doc_category,
                    "preview":  c.text[:200],
                }
                for c in chunks
            ],
        }

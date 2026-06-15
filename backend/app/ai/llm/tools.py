"""
Module: ai/llm/tools.py
Purpose: Groq-native function-calling tool definitions.
         The LLM sees these as callable tools and decides autonomously
         which ones to call, in what order, and how many times.
         Each tool maps to a real backend service call.

This replaces the hardcoded if/else intent routing in the old orchestrator.
The agent can now chain tools: fetch anomaly → check parts → get logs → answer.
"""
from typing import Any

# ─── Tool Schemas (Groq / OpenAI format) ─────────────────────────────────────

STEELMIND_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_equipment_health",
            "description": (
                "Get the current health metrics for a specific equipment: "
                "anomaly score, RUL (remaining useful life in days), "
                "degradation index, priority score, and status. "
                "Call this when the engineer asks about equipment condition, "
                "health, or when you need current sensor-derived metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {
                        "type": "string",
                        "description": "Equipment ID e.g. EQ-BF-001, EQ-HSM-001"
                    }
                },
                "required": ["equipment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_anomaly_detail",
            "description": (
                "Get detailed anomaly breakdown for an equipment: "
                "per-sensor z-scores, top contributing sensor, "
                "anomaly score 0-100, severity level, and live sensor values. "
                "Call this when diagnosing what is causing an anomaly or "
                "when the engineer asks 'why is the score high?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {"type": "string"},
                    "equipment_type": {
                        "type": "string",
                        "description": "Equipment type e.g. centrifugal_compressor, rolling_mill_drive"
                    }
                },
                "required": ["equipment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_rul_breakdown",
            "description": (
                "Get detailed RUL (Remaining Useful Life) estimation with "
                "per-sensor degradation contributions, trend slope, "
                "confidence level, and warning level. "
                "Call this when asked about remaining life, time to failure, "
                "or degradation trend."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {"type": "string"},
                    "equipment_type": {"type": "string"}
                },
                "required": ["equipment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_spare_parts",
            "description": (
                "Check availability, quantity on hand, and lead time "
                "for one or more spare parts. "
                "Call this when discussing repair options, maintenance planning, "
                "or when the engineer asks if we have parts in stock."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "part_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of part IDs e.g. ['SKF-23248', 'COUP-DISC-8']"
                    }
                },
                "required": ["part_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_open_alerts",
            "description": (
                "Get all open alerts for an equipment or for the entire plant. "
                "Returns severity, title, age, and anomaly/RUL values. "
                "Call this when the engineer asks about active problems, "
                "current alerts, or what needs attention now."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {
                        "type": "string",
                        "description": "Leave empty for plant-wide alerts"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info", ""],
                        "description": "Filter by severity level"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_maintenance_logs",
            "description": (
                "Get recent maintenance log entries (floor observations, "
                "measurements, repairs, anomaly notes) for an equipment. "
                "Call this for context about what technicians have observed "
                "recently, when doing root cause analysis, or when the "
                "engineer refers to a previous observation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent entries to retrieve (default 5)"
                    }
                },
                "required": ["equipment_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_orders",
            "description": (
                "Get work orders for an equipment or plant-wide. "
                "Filters by status (open, in_progress, completed) "
                "and priority (P1, P2, P3, P4). "
                "Call this when planning maintenance, checking what is "
                "already scheduled, or reviewing repair history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["open", "in_progress", "completed", ""]
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["P1", "P2", "P3", "P4", ""]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_plant_priority_queue",
            "description": (
                "Get all equipment sorted by priority score (highest risk first). "
                "Returns top N equipment with scores and recommended actions. "
                "Call this when asked about plant-wide health, what to focus on, "
                "or when planning a maintenance window."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "How many top-risk equipment to return (default 5)"
                    },
                    "criticality": {
                        "type": "string",
                        "enum": ["A", "B", "C", ""],
                        "description": "Filter by criticality class"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_work_order",
            "description": (
                "Create a new maintenance work order. "
                "Call this when the engineer explicitly asks to create, "
                "raise, or log a work order. "
                "Always confirm the details before calling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {"type": "string"},
                    "title":        {"type": "string"},
                    "priority":     {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
                    "wo_type":      {"type": "string", "enum": ["preventive", "corrective", "predictive", "emergency"]},
                    "tasks":        {"type": "array", "items": {"type": "string"}},
                    "estimated_hours": {"type": "number"}
                },
                "required": ["equipment_id", "title", "priority", "wo_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_maintenance_log",
            "description": (
                "Add a maintenance log entry for an equipment. "
                "Call this when the engineer describes a new observation, "
                "measurement, or finding that should be recorded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {"type": "string"},
                    "log_type": {
                        "type": "string",
                        "enum": ["observation", "inspection", "repair", "measurement", "anomaly_note"]
                    },
                    "notes": {"type": "string"}
                },
                "required": ["equipment_id", "log_type", "notes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search the plant knowledge base (equipment manuals, SOPs, "
                "failure case studies, ISO standards, maintenance guides). "
                "Returns relevant document chunks with citations. "
                "Call this when the engineer asks about procedures, standards, "
                "failure modes, or when you need technical reference material."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query e.g. 'bearing replacement procedure' or 'vibration limits ISO 10816'"
                    },
                    "equipment_id": {
                        "type": "string",
                        "description": "Optional: focus search on this equipment's documents"
                    },
                    "doc_category": {
                        "type": "string",
                        "enum": ["manual", "sop", "rca", "standard", "checklist", ""],
                        "description": "Optional: filter by document type"
                    }
                },
                "required": ["query"]
            }
        }
    },
]

# ─── Tool name set for quick lookup ───────────────────────────────────────────
TOOL_NAMES = {t["function"]["name"] for t in STEELMIND_TOOLS}

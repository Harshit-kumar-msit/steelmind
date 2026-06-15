"""
Module: ai/llm/orchestrator.py
Purpose: Agentic orchestrator using Groq native function-calling (ReAct loop).
         The LLM autonomously decides which tools to call, in what order,
         and how many times — replacing the old hardcoded if/else intent routing.

ReAct Loop:
  1. Send user message + tool schemas to LLM
  2. LLM responds with tool_call(s) OR a final text answer
  3. If tool_calls: execute each → append tool_results → go to step 1
  4. If text: stream to user, done

Max iterations: 8 (prevents infinite loops)
Tools available: 11 (see tools.py)

This means the agent can autonomously chain:
  get_anomaly_detail → check_spare_parts → search_knowledge_base → answer
without any hardcoded routing logic.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, AsyncGenerator

from loguru import logger

from app.ai.llm.client import groq_client
from app.ai.llm.tools import STEELMIND_TOOLS
from app.ai.llm.tool_executor import ToolExecutor
from app.ai.llm.role_prompts import get_role_instruction
from app.ai.llm.prompts import build_copilot_prompt
from app.core.config import settings


MAX_TOOL_ITERATIONS = 8   # safety ceiling on ReAct loop


# ─── Context & Response types ──────────────────────────────────────────────────

@dataclass
class EquipmentContext:
    equipment_id:         str   = ""
    equipment_name:       str   = ""
    equipment_type:       str   = ""
    criticality:          str   = "B"
    anomaly_score:        float = 0.0
    severity:             str   = "normal"
    rul_days:             float = 999.0
    priority_score:       float = 0.0
    active_alerts_count:  int   = 0
    sensor_snapshot:      dict  = field(default_factory=dict)
    last_maintenance_date:Optional[str] = None


@dataclass
class AssistantResponse:
    text:                    str
    citations:               list[dict] = field(default_factory=list)
    actions:                 list[dict] = field(default_factory=list)
    tool_calls_made:         list[str]  = field(default_factory=list)
    model_used:              str        = ""
    iterations:              int        = 0


# ─── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(
    ctx: EquipmentContext,
    user_role: str,
    plant_name: str,
    logbook_context: str,
) -> str:
    role_block = get_role_instruction(user_role)

    from app.api.routes.feedback import load_feedback_examples
    feedback_block = load_feedback_examples()

    sensor_str = ""
    if ctx.sensor_snapshot:
        lines = []
        for k, v in ctx.sensor_snapshot.items():
            lines.append(f"  {k}: {v}")
        sensor_str = "\n".join(lines)

    learned_block = ""
    if feedback_block:
        learned_block = "LEARNED CORRECTIONS:\n" + feedback_block

    recent_block = ""
    if logbook_context:
        recent_block = "RECENT FLOOR OBSERVATIONS:\n" + logbook_context

    system = f"""You are SteelMind, an agentic AI maintenance copilot for {plant_name}.

You have access to tools that query live plant data. Use them autonomously.

CURRENT CONTEXT:
- Equipment in focus: {ctx.equipment_id or 'none'} — {ctx.equipment_name}
- Anomaly score: {ctx.anomaly_score}/100 ({ctx.severity})
- RUL estimate: {ctx.rul_days} days
- Priority score: {ctx.priority_score}/100
- Active alerts: {ctx.active_alerts_count}
- Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

LIVE SENSOR SNAPSHOT:
{sensor_str or 'Not available — use get_anomaly_detail tool'}

{recent_block}

TOOL USE GUIDELINES:
1. For health → get_equipment_health / get_anomaly_detail
2. For RUL → get_rul_breakdown
3. For repair → check_spare_parts first
4. For RCA → combine anomaly + logs + knowledge base
5. Chain tools freely when needed

ANSWER GUIDELINES:
- Be specific and actionable
- Cite sources when available
- End with recommendation

{role_block}

{learned_block}
"""
    return system

# ─── Orchestrator ──────────────────────────────────────────────────────────────

class LLMOrchestrator:
    """
    Agentic orchestrator with Groq function-calling ReAct loop.

    The LLM decides which tools to call. We execute them and feed results back.
    Loop continues until the LLM produces a text response (no more tool calls)
    or MAX_TOOL_ITERATIONS is reached.

    Usage:
        orch = LLMOrchestrator()
        response = await orch.respond(message, context, history, db=db)
        async for chunk in orch.stream_response(message, context, history, db=db):
            yield chunk
    """

    # ── Non-streaming ─────────────────────────────────────────────────────────

    async def respond(
        self,
        message: str,
        context: EquipmentContext,
        conversation_history: list[dict],
        db=None,
        user_name: str = "Engineer",
        user_role: str = "engineer",
        plant_name: str = "Bhilai Steel Plant",
        logbook_context: str = "",
    ) -> AssistantResponse:
        """
        Full ReAct loop. Returns complete AssistantResponse.
        """
        executor  = ToolExecutor(db=db, default_equipment_id=context.equipment_id)
        system    = _build_system_prompt(context, user_role, plant_name, logbook_context)
        messages  = [*conversation_history[-20:], {"role": "user", "content": message}]
        tool_calls_made: list[str] = []
        iterations = 0

        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1

            response = await self._call_llm(system, messages)
            choice   = response.choices[0]
            msg      = choice.message

            # ── No tool calls → final answer ──
            if not msg.tool_calls:
                text = msg.content or ""
                return AssistantResponse(
                    text=text,
                    citations=executor.citations,
                    actions=self._extract_actions(text),
                    tool_calls_made=tool_calls_made,
                    model_used=settings.groq_model,
                    iterations=iterations,
                )

            # ── Execute tool calls ──
            # Append assistant message with tool_calls
            messages.append({
                "role":       "assistant",
                "content":    msg.content or "",
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ]
            })

            # Execute each tool call and append results
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                tool_calls_made.append(tool_name)
                logger.info(f"Agent calling tool: {tool_name}({list(args.keys())})")

                result_str = await executor.execute(tool_name, args)

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      result_str,
                })

        # Safety fallback if max iterations hit
        logger.warning(f"Max tool iterations ({MAX_TOOL_ITERATIONS}) reached")
        return AssistantResponse(
            text="I gathered the available data but hit the analysis limit. Here is what I found: please check the equipment health dashboard for the latest readings.",
            citations=executor.citations,
            tool_calls_made=tool_calls_made,
            model_used=settings.groq_model,
            iterations=iterations,
        )

    # ── Streaming ─────────────────────────────────────────────────────────────

    async def stream_response(
        self,
        message: str,
        context: EquipmentContext,
        conversation_history: list[dict],
        db=None,
        user_name: str = "Engineer",
        user_role: str = "engineer",
        plant_name: str = "Bhilai Steel Plant",
        logbook_context: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Streaming ReAct loop.
        Tool calls execute silently; only the final text answer is streamed.

        Yields JSON strings:
          {"type": "tool_call",  "name": "get_anomaly_detail", "args": {...}}
          {"type": "tool_result","name": "get_anomaly_detail", "ok": true}
          {"type": "citations",  "data": [...]}
          {"type": "token",      "content": "..."}
          {"type": "done",       "tool_calls": [...], "iterations": N}
        """
        executor  = ToolExecutor(db=db, default_equipment_id=context.equipment_id)
        system    = _build_system_prompt(context, user_role, plant_name, logbook_context)
        messages  = [*conversation_history[-20:], {"role": "user", "content": message}]
        tool_calls_made: list[str] = []
        iterations = 0

        # ── ReAct loop (non-streaming for tool calls) ──
        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1

            response = await self._call_llm(system, messages)
            choice   = response.choices[0]
            msg      = choice.message

            if not msg.tool_calls:
                # Final answer — stream it
                break

            # Execute tools, yield progress events
            messages.append({
                "role":       "assistant",
                "content":    msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            })

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                tool_calls_made.append(tool_name)
                logger.info(f"[stream] Agent tool: {tool_name}")

                # Yield tool_call event (frontend can show "Checking spare parts…")
                yield json.dumps({
                    "type": "tool_call",
                    "name": tool_name,
                    "args": {k: v for k, v in args.items() if k != "query"},
                }) + "\n"

                result_str = await executor.execute(tool_name, args)

                yield json.dumps({
                    "type": "tool_result",
                    "name": tool_name,
                    "ok":   "error" not in json.loads(result_str),
                }) + "\n"

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      result_str,
                })

        # ── Send citations before streaming text ──
        if executor.citations:
            yield json.dumps({"type": "citations", "data": executor.citations}) + "\n"

        # ── Stream final text answer ──
        final_text = ""
        if iterations < MAX_TOOL_ITERATIONS and not msg.tool_calls:
            # Stream the last LLM response
            async for token in groq_client.stream(
                messages=messages,
                system_prompt=system,
            ):
                final_text += token
                yield json.dumps({"type": "token", "content": token}) + "\n"
        else:
            # Fallback: get a final answer after tool loop
            final_response = await self._call_llm(system, messages)
            final_text = final_response.choices[0].message.content or ""
            for token in self._split_tokens(final_text):
                yield json.dumps({"type": "token", "content": token}) + "\n"

        # ── Extract action buttons from final text ──
        actions = self._extract_actions(final_text)

        yield json.dumps({
            "type":       "done",
            "tool_calls": tool_calls_made,
            "iterations": iterations,
            "actions":    actions,
        }) + "\n"

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _call_llm(self, system: str, messages: list[dict]):
        """Single LLM call with tools. Returns raw Groq response."""
        return await groq_client._client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "system", "content": system}, *messages],
            tools=STEELMIND_TOOLS,
            tool_choice="auto",
            temperature=settings.groq_temperature,
            max_tokens=settings.groq_max_tokens,
        )

    def _extract_actions(self, text: str) -> list[dict]:
        """
        Extract ACTION: directives from LLM response text.
        Format: ACTION:TYPE|key=value|key=value
        These become clickable buttons in the frontend.
        """
        import re
        actions = []
        pattern = r"ACTION:([A-Z_]+)\|([^\n]+)"
        label_map = {
            "create_wo":    "📋 Create Work Order",
            "check_parts":  "🔩 Check Spare Parts",
            "ack_alert":    "✅ Acknowledge Alert",
            "add_log":      "📝 Add Log Entry",
            "open_planner": "📅 Open Planner",
        }
        for match in re.finditer(pattern, text):
            action_type = match.group(1).lower()
            params = {}
            for pair in match.group(2).split("|"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k.strip()] = v.strip()
            actions.append({
                "action_type": action_type,
                "label":       label_map.get(action_type, action_type.replace("_", " ").title()),
                "payload":     params,
            })
        return actions

    def _split_tokens(self, text: str, size: int = 8) -> list[str]:
        """Split text into small chunks for fake streaming."""
        return [text[i:i+size] for i in range(0, len(text), size)]


# ─── Singleton ─────────────────────────────────────────────────────────────────

_orchestrator_instance: Optional[LLMOrchestrator] = None


def get_orchestrator() -> LLMOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = LLMOrchestrator()
    return _orchestrator_instance

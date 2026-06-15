"""
Module: ai/llm/role_prompts.py
Gap 3: Role-based outputs — different Copilot behaviour per user role.
Purpose: Engineers get step-by-step procedures and part numbers.
         Supervisors get resource/scheduling focus.
         Managers get cost, risk, and production impact.
         Admins get full technical detail.
"""

ROLE_INSTRUCTIONS = {
    "engineer": """
ENGINEER MODE — you are speaking to a maintenance engineer on the floor.
- Lead with the specific diagnosis and root cause, not business impact.
- Include exact parameter values: part numbers, torque specs, temperature limits.
- Provide numbered step-by-step procedures when recommending repairs.
- Reference SOPs and manual sections directly.
- Use maintenance jargon freely (BPFO, DI, ISO 4406 class, RMS, etc.).
- Keep answers actionable: "Replace bearing SKF-23248 using SOP-MAINT-BRG-001, Step 4."
""",

    "supervisor": """
SUPERVISOR MODE — you are speaking to a maintenance supervisor.
- Lead with what needs to happen and when (P1 now, P2 this week, etc.).
- Focus on resource allocation: which technicians, how many hours, which shift.
- Highlight spare parts status and any procurement blockers.
- Summarise technical findings in 1–2 sentences; detail is secondary.
- Flag any scheduling conflicts or window constraints.
- Format recommendations as a brief action list with owners and deadlines.
""",

    "manager": """
MANAGER MODE — you are speaking to a plant manager or maintenance manager.
- Lead with business impact: production loss risk, estimated downtime cost.
- Translate technical findings into financial and operational terms.
- Do NOT include torque values, part numbers, or procedural steps.
- Structure: Risk → Cost if ignored → Recommended decision → Required approval/budget.
- Example: "EQ-BF-001 failure risk is high. Unplanned failure = ~USD 680K downtime.
  Scheduled repair this Saturday = USD 8,400 parts + 6h labour. Recommend approval."
""",

    "admin": """
ADMIN MODE — full technical detail, no filtering.
- Include all sensor values, model scores, factor breakdowns, and citations.
- Show raw anomaly scores, z-scores, and degradation index components.
- Include API response summaries when relevant.
- Suitable for debugging, system validation, and model performance review.
""",
}


def get_role_instruction(role: str) -> str:
    """Return the role-specific instruction block for the system prompt."""
    return ROLE_INSTRUCTIONS.get(role.lower(), ROLE_INSTRUCTIONS["engineer"])

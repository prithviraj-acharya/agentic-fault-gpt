from __future__ import annotations

import json
from typing import Any, Dict, Sequence

from diagnostic_agent.controller.schemas import IncidentContext


def build_system_prompt(*, allowed_evidence_ids: Sequence[str]) -> str:
    """Create the system prompt.

    Keep this focused on behavior constraints and schema rules.
    Any schema changes must happen in the repo's Pydantic model, not here.
    """

    allowed_preview = ", ".join(list(allowed_evidence_ids)[:60])

    return (
        "You are an HVAC diagnostic reasoner. Use ONLY the evidence provided in the user message "
        "(IncidentContext windows and retrieved document chunks). Do NOT use outside knowledge.\n\n"
        "Include a short high-level justification (NOT chain-of-thought): add exactly one sentence starting with "
        "'Reasoning:' inside root_cause. Keep it <= 25 words and do not provide step-by-step reasoning.\n\n"
        "Grounding rules:\n"
        "- Every meaningful claim must cite evidence IDs from the allowed list.\n"
        "- evidence_ids may ONLY reference allowed evidence IDs.\n"
        "- If evidence is insufficient or conflicting, set conflict=true and use low confidence.\n"
        "- If only one weak source supports the diagnosis, cap confidence at <= 0.6.\n"
        "- Increase confidence only when windows + manuals/past cases align.\n\n"
        "Consistency self-check before responding:\n"
        "- root_cause must match symptoms/rules described by windows.\n"
        "- recommended_actions must be appropriate to the fault type (sensor vs damper vs coil).\n"
        "- If contradictions exist, lower confidence and set conflict=true.\n\n"
        "Output rules (STRICT):\n"
        "- Return STRICT JSON ONLY (no markdown, no code fences, no extra text).\n"
        "- Return NO EXTRA KEYS beyond the schema below.\n"
        "- Keep outputs concise to avoid truncation: title <= 80 chars; root_cause <= 2 sentences; "
        "recommended_actions <= 5 items.\n"
        "- Embed citations inline in strings as '(evidence: id1,id2)' when making claims.\n\n"
        "Forbidden content:\n"
        "- Do NOT mention API parameters, token limits, truncation, IncompleteDetails, or the model name.\n"
        "- If you cannot produce a grounded diagnosis, say so in-domain (e.g., insufficient evidence) "
        "and lower confidence.\n\n"
        "Schema (exact keys):\n"
        '{"title": str, "root_cause": str, "confidence": float, '
        '"recommended_actions": [str], "evidence_ids": [str], "conflict": bool}\n\n'
        f"Allowed evidence_ids (subset shown): {allowed_preview}"
    )


def build_user_prompt(
    *,
    ctx: IncidentContext,
    rule_ids: Sequence[str],
    symptom_summary: str,
    time_range: Dict[str, str | None],
    evidence_windows: Sequence[Dict[str, Any]],
    retrieved_docs: Sequence[Dict[str, Any]],
    template: str,
) -> str:
    """Create the user payload containing only provided context and evidence."""

    payload: Dict[str, Any] = {
        "incident_key": (
            list(ctx.incident_key)
            if isinstance(ctx.incident_key, tuple)
            else ctx.incident_key
        ),
        "ahu_id": ctx.ahu_id,
        "detected_fault_type": ctx.detected_fault_type,
        "stage": ctx.stage,
        "time_range": time_range,
        "rule_ids": list(rule_ids),
        "symptom_summary": symptom_summary,
        "evidence_windows": list(evidence_windows),
        "retrieved_docs": list(retrieved_docs),
    }

    template = (template or "").strip()
    if template:
        payload["prompt_template"] = template

    return json.dumps(payload, ensure_ascii=False, indent=2)

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from diagnostic_agent.controller.schemas import DiagnosisResult, IncidentContext
from diagnostic_agent.reasoner.openai.client import call_openai_responses_api
from diagnostic_agent.reasoner.openai.evidence import (
    docs_payload,
    overall_time_range,
    symptom_summary,
    top_rule_ids,
    windows_payload,
)
from diagnostic_agent.reasoner.openai.parsing import fallback_result, parse_and_validate
from diagnostic_agent.reasoner.openai.prompts import (
    build_system_prompt,
    build_user_prompt,
)

logger = logging.getLogger(__name__)


def _trace_enabled(var_name: str) -> bool:
    v = (os.getenv(var_name) or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _preview(text: str, *, max_chars: int) -> str:
    t = (text or "").replace("\r\n", "\n")
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 3] + "..."


@dataclass
class OpenAIReasoner:
    """OpenAI-backed reasoner (stateless/pure).

    This class is the Phase-6 interface entrypoint used by the controller/worker:
    `diagnose(ctx) -> DiagnosisResult`.

    Implementation details live in small helper modules under
    `diagnostic_agent.reasoner.openai.*` to keep this file readable.

    Hard constraints:
    - Stateless: no caching/memory across calls
    - Uses ONLY `ctx` as knowledge (windows + retrieved docs)
    - One model call (plus optional one repair retry on schema invalid JSON)
    - No orchestration/loops; returns exactly one DiagnosisResult per call
    """

    # Model selection: can be set explicitly, or via a convenience `mode`.
    # Environment variables override constructor values:
    # - OPENAI_MODEL (highest priority)
    # - OPENAI_MODEL_MODE in {cheap,strong}
    model: Optional[str] = None
    mode: Optional[Literal["cheap", "strong"]] = None

    prompt_template_path: Optional[str] = None
    timeout_s: float = 30.0

    # Output size control for the Responses API.
    max_output_tokens: int = 1800

    def diagnose(
        self, ctx: IncidentContext, model_override: Optional[str] = None
    ) -> DiagnosisResult:
        """Produce a grounded `DiagnosisResult` from the provided IncidentContext.

        This method is defensive:
        - validates strict JSON against the repo's Pydantic `DiagnosisResult`
        - performs at most ONE repair retry if JSON/schema is invalid
        - falls back to an "uncertain" result on API/validation errors
        """

        template = self._load_template()

        # Evidence payloads (and evidence allow-list) derived strictly from ctx.
        evidence_windows, window_ids = windows_payload(ctx.recent_windows)
        retrieved_docs, doc_ids = docs_payload(ctx.retrieved_docs)
        allowed_evidence_ids = sorted(set(window_ids) | set(doc_ids))

        # Compact “derived” fields used in the prompt.
        rule_ids = top_rule_ids(ctx.recent_windows)
        symptoms = symptom_summary(ctx.recent_windows)
        time_range = overall_time_range(ctx.recent_windows)

        system_msg = build_system_prompt(allowed_evidence_ids=allowed_evidence_ids)
        user_msg = build_user_prompt(
            ctx=ctx,
            rule_ids=rule_ids,
            symptom_summary=symptoms,
            time_range=time_range,
            evidence_windows=evidence_windows,
            retrieved_docs=retrieved_docs,
            template=template,
        )

        model = self._resolve_model(model_override=model_override)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return fallback_result(
                reason="Missing OPENAI_API_KEY",
                safe_evidence_ids=allowed_evidence_ids,
            )

        max_out = self.max_output_tokens
        try:
            env_max = (os.getenv("PHASE6_OPENAI_MAX_OUTPUT_TOKENS") or "").strip()
            if env_max:
                max_out = int(env_max)
        except Exception:
            max_out = self.max_output_tokens

        trace_io = _trace_enabled("PHASE6_TRACE_IO")
        trace_openai = _trace_enabled("PHASE6_TRACE_OPENAI")
        trace_prompts = trace_openai or _trace_enabled("PHASE6_TRACE_OPENAI_PROMPTS")
        trace_responses = trace_openai or _trace_enabled(
            "PHASE6_TRACE_OPENAI_RESPONSES"
        )

        if trace_io or trace_openai:
            logger.info(
                "%s",
                {
                    "event": "phase6.openai_call_start",
                    "model": model,
                    "stage": int(getattr(ctx, "stage", 1) or 1),
                    "max_output_tokens": int(self.max_output_tokens),
                    "allowed_evidence_ids_count": len(allowed_evidence_ids),
                    "windows_count": len(ctx.recent_windows or []),
                    "retrieved_docs_count": len(ctx.retrieved_docs or []),
                },
            )
            if trace_prompts:
                logger.info(
                    "%s",
                    {
                        "event": "phase6.openai_prompt_preview",
                        "system_preview": _preview(system_msg, max_chars=900),
                        "user_preview": _preview(user_msg, max_chars=3000),
                    },
                )

        # --- OpenAI call (Responses API, single shot) ---
        raw_text: Optional[str] = None
        try:
            raw_text = call_openai_responses_api(
                api_key=api_key,
                model=model,
                system_msg=system_msg,
                user_msg=user_msg,
                timeout_s=self.timeout_s,
                max_output_tokens=max_out,
            )

            if trace_responses:
                logger.info(
                    "%s",
                    {
                        "event": "phase6.openai_raw_output_preview",
                        "raw_preview": _preview(str(raw_text or ""), max_chars=3500),
                    },
                )

            parsed = parse_and_validate(raw_text, allowed_evidence_ids)
            if parsed is not None:
                if trace_io or trace_openai:
                    logger.info(
                        "%s",
                        {
                            "event": "phase6.openai_parsed_result",
                            "result": {
                                "title": parsed.title,
                                "confidence": float(parsed.confidence),
                                "conflict": bool(parsed.conflict),
                                "evidence_ids": list(parsed.evidence_ids or [])[:12],
                            },
                        },
                    )
                return parsed

            # --- One repair retry (schema/JSON only) ---
            raw_for_repair = (raw_text or "").strip() if raw_text is not None else ""
            if raw_for_repair.startswith("Response("):
                raw_for_repair = ""
            if len(raw_for_repair) > 2000:
                raw_for_repair = raw_for_repair[:2000] + "..."

            repair_msg = (
                "Fix the following model output so it matches the DiagnosisResult schema exactly. "
                "Output JSON only (no markdown, no explanations).\n\n"
                "Do NOT mention token limits, truncation, API parameters, IncompleteDetails, or the model name.\n"
                "If evidence is insufficient or conflicting, output an in-domain low-confidence result with conflict=true.\n\n"
                "Schema keys: title (str), root_cause (str), confidence (0..1 float), "
                "recommended_actions (list[str]), evidence_ids (list[str]), conflict (bool).\n\n"
                f"Allowed evidence_ids: {allowed_evidence_ids}\n\n"
                "Model output to repair (may be empty if the first response was incomplete/non-JSON):\n"
                f"{raw_for_repair}"
            )
            raw_text_2 = self._call_openai(
                api_key=api_key,
                model=model,
                system_msg=(
                    "You are a JSON repair bot. Return ONLY strict JSON for the provided schema. "
                    "No extra keys."
                ),
                user_msg=repair_msg,
                max_output_tokens=min(max(max_out, 600), 1400),
            )

            if trace_responses:
                logger.info(
                    "%s",
                    {
                        "event": "phase6.openai_raw_output_preview_repair",
                        "raw_preview": _preview(str(raw_text_2 or ""), max_chars=3500),
                    },
                )

            parsed2 = parse_and_validate(raw_text_2, allowed_evidence_ids)
            if parsed2 is not None:
                if trace_io or trace_openai:
                    logger.info(
                        "%s",
                        {
                            "event": "phase6.openai_parsed_result",
                            "result": {
                                "title": parsed2.title,
                                "confidence": float(parsed2.confidence),
                                "conflict": bool(parsed2.conflict),
                                "evidence_ids": list(parsed2.evidence_ids or [])[:12],
                            },
                        },
                    )
                return parsed2

            return fallback_result(
                reason="Model JSON invalid after one repair retry",
                safe_evidence_ids=allowed_evidence_ids,
            )

        except Exception as exc:
            return fallback_result(
                reason=f"OpenAI error: {type(exc).__name__}: {exc}",
                safe_evidence_ids=allowed_evidence_ids,
            )

    def _load_template(self) -> str:
        if not self.prompt_template_path:
            return ""
        p = Path(self.prompt_template_path)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    @staticmethod
    def _ctx_to_payload(ctx: IncidentContext) -> Dict[str, Any]:
        return ctx.model_dump()

    def _resolve_model(self, *, model_override: Optional[str] = None) -> str:
        """Resolve model name using the required override order.

        Priority:
        1) per-call override (nice-to-have)
        2) OPENAI_MODEL env var (highest priority env)
        3) OPENAI_MODEL_MODE env var
        4) constructor `model`
        5) constructor `mode`
        6) default: gpt-5-mini
        """

        if model_override:
            return str(model_override).strip()

        env_model = (os.getenv("OPENAI_MODEL") or "").strip()
        if env_model:
            return env_model

        env_mode = (os.getenv("OPENAI_MODEL_MODE") or "").strip().lower()
        if env_mode == "strong":
            return "gpt-5.2"
        if env_mode == "cheap":
            return "gpt-5-mini"

        if self.model:
            return str(self.model).strip()
        if (self.mode or "").lower() == "strong":
            return "gpt-5.2"

        return "gpt-5-mini"

    def _call_openai(
        self,
        *,
        api_key: str,
        model: str,
        system_msg: str,
        user_msg: str,
        max_output_tokens: int,
    ) -> str:
        """Backward-compatible shim for the smoke script / any internal callers."""

        return call_openai_responses_api(
            api_key=api_key,
            model=model,
            system_msg=system_msg,
            user_msg=user_msg,
            timeout_s=self.timeout_s,
            max_output_tokens=max_output_tokens,
        )


# --- Non-executed usage snippet (for docs/tests) ---
if False:  # pragma: no cover
    import os

    # cheap/testing
    reasoner = OpenAIReasoner(mode="cheap")  # gpt-5-mini
    # strong/demo
    reasoner = OpenAIReasoner(mode="strong")  # gpt-5.2

    os.environ["OPENAI_MODEL_MODE"] = "strong"
    os.environ["OPENAI_MODEL"] = "gpt-5.2"

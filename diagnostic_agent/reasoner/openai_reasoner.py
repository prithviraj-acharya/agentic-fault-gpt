from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from diagnostic_agent.controller.schemas import DiagnosisResult, IncidentContext


@dataclass
class OpenAIReasoner:
    """Placeholder OpenAI reasoner implementation.

    This is intentionally minimal so Phase 6 remains runnable with MockReasoner.
    """

    model: str = "gpt-5.2-mini"  # default placeholder; configure via env
    prompt_template_path: Optional[str] = None
    timeout_s: float = 30.0

    def diagnose(self, ctx: IncidentContext) -> DiagnosisResult:
        template = self._load_template()
        _ = template  # to be used later

        raise RuntimeError(
            "OpenAIReasoner is a placeholder. Use MockReasoner for Phase 6 demos, "
            "or implement the OpenAI call + prompt formatting here."
        )

    def _load_template(self) -> str:
        if not self.prompt_template_path:
            return ""
        p = Path(self.prompt_template_path)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    @staticmethod
    def _ctx_to_payload(ctx: IncidentContext) -> Dict[str, Any]:
        return ctx.model_dump()

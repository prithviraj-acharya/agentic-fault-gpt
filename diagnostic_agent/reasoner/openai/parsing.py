from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence

from diagnostic_agent.controller.schemas import DiagnosisResult


def extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from model output.

    The model occasionally returns extra text; we defensively scan for the first balanced `{...}`.
    """

    s = (text or "").strip()
    if not s:
        return None

    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except Exception:
        pass

    start = s.find("{")
    if start < 0:
        return None

    depth = 0
    in_str = False
    escape = False

    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start : i + 1]
                try:
                    v = json.loads(candidate)
                    return v if isinstance(v, dict) else None
                except Exception:
                    return None

    return None


def parse_and_validate(
    raw_text: Optional[str],
    allowed_evidence_ids: Sequence[str],
) -> Optional[DiagnosisResult]:
    """Parse JSON and validate against the repo's Pydantic `DiagnosisResult`."""

    if not raw_text or not str(raw_text).strip():
        return None

    obj = extract_first_json_object(str(raw_text))
    if obj is None:
        return None

    # Reject meta/non-diagnostic responses.
    title = str(obj.get("title") or "")
    root = str(obj.get("root_cause") or "")
    blob = (title + "\n" + root).lower()
    if any(
        m in blob
        for m in [
            "max_output_tokens",
            "token limit",
            "truncated",
            "incompletedetails",
            "response metadata",
            "model output",
        ]
    ):
        return None

    allowed = {str(e) for e in allowed_evidence_ids if e}

    ev = obj.get("evidence_ids")
    if isinstance(ev, list):
        obj["evidence_ids"] = [str(x) for x in ev if str(x) in allowed]
    else:
        obj["evidence_ids"] = []

    ra = obj.get("recommended_actions")
    if isinstance(ra, list):
        obj["recommended_actions"] = [str(x).strip() for x in ra if str(x).strip()]
    elif isinstance(ra, str) and ra.strip():
        obj["recommended_actions"] = [ra.strip()]
    else:
        obj["recommended_actions"] = []

    try:
        conf_raw = obj.get("confidence", None)
        if conf_raw is not None:
            conf = float(conf_raw)
            obj["confidence"] = max(0.0, min(1.0, conf))
    except Exception:
        pass

    try:
        return DiagnosisResult.model_validate(obj)
    except Exception:
        return None


def fallback_result(
    *, reason: str, safe_evidence_ids: Sequence[str]
) -> DiagnosisResult:
    """Return a schema-valid fallback result."""

    safe_all = [str(e) for e in safe_evidence_ids if e]
    safe_windows = [e for e in safe_all if e.startswith("window:") or "_" in e]
    safe = (safe_windows or safe_all)[:3]

    return DiagnosisResult(
        title="Uncertain diagnosis",
        root_cause=(
            "Could not produce a grounded schema-valid diagnosis. "
            f"(evidence: none) (reason: {reason})"
        ),
        confidence=0.2,
        recommended_actions=["Collect additional evidence and rerun diagnosis"],
        evidence_ids=list(safe),
        conflict=True,
    )

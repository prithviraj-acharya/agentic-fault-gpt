from __future__ import annotations

from typing import Any, Dict, List


def call_openai_responses_api(
    *,
    api_key: str,
    model: str,
    system_msg: str,
    user_msg: str,
    timeout_s: float,
    max_output_tokens: int,
) -> str:
    """Single OpenAI Responses API call.

    This is kept separate to reduce noise in the main reasoner implementation.
    """

    import httpx
    from openai import OpenAI  # type: ignore

    http_client = httpx.Client(timeout=timeout_s)
    try:
        client = OpenAI(api_key=api_key, http_client=http_client)

        json_schema: Dict[str, Any] = {
            "name": "diagnosis_result",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "root_cause": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "recommended_actions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "conflict": {"type": "boolean"},
                },
                "required": [
                    "title",
                    "root_cause",
                    "confidence",
                    "recommended_actions",
                    "evidence_ids",
                    "conflict",
                ],
            },
            "strict": True,
        }

        create_kwargs: Dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "max_output_tokens": int(max_output_tokens),
        }

        try:
            create_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": json_schema,
            }
            resp = client.responses.create(**create_kwargs)
        except Exception:
            # Some models / SDK versions may not accept response_format.
            create_kwargs.pop("response_format", None)
            resp = client.responses.create(**create_kwargs)

        out = getattr(resp, "output_text", None)
        if isinstance(out, str) and out.strip():
            incomplete = getattr(resp, "incomplete_details", None)
            if incomplete:
                raise RuntimeError(f"incomplete_response:{incomplete}")
            return out

        if hasattr(resp, "output"):
            chunks: List[str] = []
            for item in resp.output or []:
                for c in getattr(item, "content", []) or []:
                    t = getattr(c, "text", None)
                    if isinstance(t, str):
                        chunks.append(t)
            if chunks:
                return "\n".join(chunks)

        return str(resp)
    finally:
        try:
            http_client.close()
        except Exception:
            pass

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _trace_openai() -> bool:
    v = (os.getenv("PHASE6_TRACE_OPENAI") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


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

    def _env_float(name: str, default: float) -> float:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except Exception:
            return default

    def _env_int(name: str) -> int | None:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return None
        if raw.lower() in {"none", "off", "false"}:
            return None
        try:
            return int(raw)
        except Exception:
            return None

    def _drop_if_unsupported(create_kwargs: Dict[str, Any], exc: Exception) -> bool:
        """Drop known optional kwargs if the SDK/model rejects them.

        Returns True if we removed anything.
        """

        msg = f"{type(exc).__name__}:{exc}".lower()
        removed = False
        for k in (
            "seed",
            "temperature",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
        ):
            if k in create_kwargs and (
                "unexpected keyword" in msg
                or "unknown parameter" in msg
                or "unrecognized" in msg
                or f"{k}" in msg
            ):
                create_kwargs.pop(k, None)
                removed = True
        return removed

    http_client = httpx.Client(timeout=timeout_s)
    try:
        client = OpenAI(api_key=api_key, http_client=http_client)

        # NOTE: Keep the schema tight to reduce long / rambling outputs which can
        # trigger `incomplete_details.reason == "max_output_tokens"`.
        json_schema: Dict[str, Any] = {
            "name": "diagnosis_result",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string", "maxLength": 120},
                    "root_cause": {"type": "string", "maxLength": 700},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "recommended_actions": {
                        "type": "array",
                        "maxItems": 5,
                        "items": {"type": "string", "maxLength": 220},
                    },
                    "evidence_ids": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string", "maxLength": 120},
                    },
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

        # Make runs stable by default: lower randomness => more repeatable confidence.
        # Users can override via env vars.
        create_kwargs["temperature"] = _env_float("PHASE6_OPENAI_TEMPERATURE", 0.0)
        create_kwargs["top_p"] = _env_float("PHASE6_OPENAI_TOP_P", 1.0)
        # Seed is not consistently supported across SDK versions/models.
        # Only send it when explicitly configured.
        seed = _env_int("PHASE6_OPENAI_SEED")
        if seed is not None:
            create_kwargs["seed"] = seed

        # Keep penalties deterministic/neutral (and overrideable if needed).
        create_kwargs["presence_penalty"] = _env_float(
            "PHASE6_OPENAI_PRESENCE_PENALTY", 0.0
        )
        create_kwargs["frequency_penalty"] = _env_float(
            "PHASE6_OPENAI_FREQUENCY_PENALTY", 0.0
        )

        # Reduce "all reasoning, no answer" failure mode when supported.
        # If unsupported by the model/SDK, we silently drop it.
        create_kwargs["reasoning"] = {"effort": "low"}

        used_response_format = False
        dropped_reasoning = False
        dropped_sampling = False
        try:
            create_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": json_schema,
            }
            used_response_format = True
            try:
                resp = client.responses.create(**create_kwargs)
            except Exception as exc_schema_call:
                if _drop_if_unsupported(create_kwargs, exc_schema_call):
                    dropped_sampling = True
                    resp = client.responses.create(**create_kwargs)
                else:
                    raise
        except Exception as exc_schema:
            # Some models / SDK versions may not accept response_format.
            used_response_format = False
            create_kwargs.pop("response_format", None)

            # Some models/SDKs also reject the `reasoning` param.
            try:
                try:
                    resp = client.responses.create(**create_kwargs)
                except Exception as exc_no_schema:
                    if _drop_if_unsupported(create_kwargs, exc_no_schema):
                        dropped_sampling = True
                        resp = client.responses.create(**create_kwargs)
                    else:
                        raise
            except Exception:
                create_kwargs.pop("reasoning", None)
                dropped_reasoning = True
                try:
                    resp = client.responses.create(**create_kwargs)
                except Exception as exc_no_reasoning:
                    if _drop_if_unsupported(create_kwargs, exc_no_reasoning):
                        dropped_sampling = True
                        resp = client.responses.create(**create_kwargs)
                    else:
                        raise

            if _trace_openai():
                logger.info(
                    "%s",
                    {
                        "event": "phase6.openai_response_format_fallback",
                        "model": model,
                        "dropped_reasoning": dropped_reasoning,
                        "dropped_sampling": dropped_sampling,
                        "error": f"{type(exc_schema).__name__}:{exc_schema}",
                    },
                )

        if _trace_openai():
            logger.info(
                "%s",
                {
                    "event": "phase6.openai_response_meta",
                    "model": model,
                    "used_response_format": used_response_format,
                    "dropped_reasoning": dropped_reasoning,
                    "dropped_sampling": dropped_sampling,
                    "temperature": create_kwargs.get("temperature", None),
                    "top_p": create_kwargs.get("top_p", None),
                    "seed": create_kwargs.get("seed", None),
                    "status": getattr(resp, "status", None),
                    "incomplete_details": getattr(resp, "incomplete_details", None),
                    "has_output_text": bool(getattr(resp, "output_text", None)),
                },
            )

        out = getattr(resp, "output_text", None)
        if isinstance(out, str) and out.strip():
            # If the response hit `max_output_tokens`, the API may still return
            # schema-valid JSON. Let the caller's validator decide.
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

        # If the model returned *no* user-visible text (common when status=incomplete
        # and only a reasoning item is present), don't stringify the entire Response
        # object; that creates a huge "repair" prompt and makes things worse.
        status = getattr(resp, "status", None)
        incomplete = getattr(resp, "incomplete_details", None)
        if str(status).lower() == "incomplete" or incomplete is not None:
            return ""

        return str(resp)
    finally:
        try:
            http_client.close()
        except Exception:
            pass

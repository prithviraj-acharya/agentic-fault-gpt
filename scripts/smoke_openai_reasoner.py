from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, cast

# Allow running as a standalone script without installing the repo as a package.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env into process environment (so OPENAI_API_KEY is picked up).
# This keeps the reasoner itself stateless and avoids requiring callers to export vars.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(dotenv_path=REPO_ROOT / ".env", override=False)
except Exception:
    # If python-dotenv isn't installed, we simply rely on existing environment variables.
    pass

from diagnostic_agent.controller.schemas import (
    IncidentContext,
    RetrievalStats,
    RetrievedDoc,
    WindowSummaryMinimal,
)
from diagnostic_agent.reasoner.openai_reasoner import OpenAIReasoner


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        s = (line or "").strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            yield obj


def _load_windows_from_jsonl(
    *,
    jsonl_path: Path,
    ahu_id: str,
    max_windows: int,
) -> list[WindowSummaryMinimal]:
    """Load real window summaries from a JSONL file.

    Expected input format matches data/generated/window_summaries.jsonl.
    """

    if not jsonl_path.exists():
        return []

    rows = [r for r in _iter_jsonl(jsonl_path) if str(r.get("ahu_id")) == str(ahu_id)]
    rows = rows[-max_windows:]
    out: list[WindowSummaryMinimal] = []
    for r in rows:
        out.append(
            WindowSummaryMinimal(
                ahu_id=str(r.get("ahu_id") or ahu_id),
                window_id=(str(r.get("window_id")) if r.get("window_id") else None),
                time=(r.get("time") if isinstance(r.get("time"), dict) else None),
                anomalies=[
                    a for a in (r.get("anomalies") or []) if isinstance(a, dict)
                ],
                signature=(str(r.get("signature")) if r.get("signature") else None),
                summary_text=str(
                    r.get("text_summary")
                    or r.get("summary_text")
                    or r.get("text")
                    or ""
                )
                or None,
            )
        )
    return out


def _parse_kv_bar_line(line: str) -> dict[str, str]:
    # Example: "doc_id=ASHRAE_GUIDELINE | file=Ashrae-Guideline.pdf | chunk_index=57 | pages=25"
    out: dict[str, str] = {}
    for part in [p.strip() for p in (line or "").split("|")]:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _parse_retrieval_output_docs(
    *,
    output_txt_path: Path,
    query_index: int,
    max_per_corpus: int = 3,
) -> tuple[Optional[str], list[RetrievedDoc]]:
    """Parse output.txt (Phase 4 retrieval demo) to build RetrievedDoc items.

    Returns (fault_type_from_section, docs).
    """

    if not output_txt_path.exists():
        return None, []

    text = output_txt_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Find the start of the Q{n}: section.
    q_prefix = f"Q{int(query_index)}:"
    start = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith(q_prefix)), None
    )
    if start is None:
        return None, []

    # Find end (next Q or end of file).
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("Q")),
        len(lines),
    )
    section = lines[start:end]

    # Try to parse fault_type from the Q line.
    fault_type: Optional[str] = None
    q_line = section[0]
    if "fault_type=" in q_line:
        fault_type = q_line.split("fault_type=", 1)[1].strip()

    docs: list[RetrievedDoc] = []
    corpus: Optional[str] = None
    current_id: Optional[str] = None
    current_distance: Optional[float] = None
    current_meta: dict[str, Any] = {}
    current_snippet_lines: list[str] = []
    seen_counts: dict[str, int] = {"manuals": 0, "past_cases": 0}

    def _flush() -> None:
        nonlocal current_id, current_distance, current_meta, current_snippet_lines
        if not corpus or not current_id:
            current_id = None
            current_distance = None
            current_meta = {}
            current_snippet_lines = []
            return
        if seen_counts.get(corpus, 0) >= max_per_corpus:
            current_id = None
            current_distance = None
            current_meta = {}
            current_snippet_lines = []
            return
        snippet = " ".join([s.strip() for s in current_snippet_lines if s.strip()])
        docs.append(
            RetrievedDoc(
                corpus=corpus,
                doc_id=str(current_id),
                distance=current_distance,
                text=snippet,
                metadata=dict(current_meta),
            )
        )
        seen_counts[corpus] = seen_counts.get(corpus, 0) + 1
        current_id = None
        current_distance = None
        current_meta = {}
        current_snippet_lines = []

    i = 0
    while i < len(section):
        ln = section[i]
        s = ln.strip()

        if s.startswith("Manuals"):
            _flush()
            corpus = "manuals"
        elif s.startswith("Past Cases"):
            _flush()
            corpus = "past_cases"

        # Entry header line: "#1  id=..."
        if s.startswith("#") and "id=" in s:
            _flush()
            # id=ASHRAE_GUIDELINE::chunk::57
            current_id = s.split("id=", 1)[1].strip()
            current_distance = None
            current_meta = {}
            current_snippet_lines = []

        # Distance line: "distance=0.3088  score=0.764"
        if "distance=" in s:
            try:
                dist_s = s.split("distance=", 1)[1].split()[0]
                current_distance = float(dist_s)
            except Exception:
                current_distance = None

        # Metadata line: starts with doc_id= or case_id=
        if s.startswith("doc_id=") or s.startswith("case_id="):
            current_meta.update(_parse_kv_bar_line(s))

        if s == "snippet:":
            # Consume subsequent indented lines until blank or next entry.
            j = i + 1
            while j < len(section):
                nxt = section[j]
                nxts = nxt.strip()
                if not nxts:
                    break
                if nxts.startswith("#") and "id=" in nxts:
                    break
                if nxts.startswith("✅"):
                    break
                current_snippet_lines.append(nxt)
                j += 1
            i = j
            continue

        i += 1

    _flush()
    return fault_type, docs


def _sample_ctx(*, ahu_id: str, detected_fault_type: str) -> IncidentContext:
    """Fallback minimal context: 2 windows + 2 docs (synthetic)."""
    windows = [
        WindowSummaryMinimal(
            ahu_id=ahu_id,
            window_id=f"{ahu_id}_2026-01-27T10:00:00Z_300s_tumbling",
            time={"start": "2026-01-27T10:00:00Z", "end": "2026-01-27T10:05:00Z"},
            anomalies=[
                {
                    "rule_id": "SAT_TRACKING_ERROR_HIGH",
                    "message": "Supply air temperature above setpoint while cooling demand is high",
                    "severity": "high",
                }
            ],
            signature="sig-demo-1",
            summary_text=(
                f"{ahu_id} window 10:00–10:05Z: sa_temp_mean_minus_sp=+2.4C, "
                "cc_valve_mean=88%. anomalies=SAT_TRACKING_ERROR_HIGH"
            ),
        ),
        WindowSummaryMinimal(
            ahu_id=ahu_id,
            window_id=f"{ahu_id}_2026-01-27T10:05:00Z_300s_tumbling",
            time={"start": "2026-01-27T10:05:00Z", "end": "2026-01-27T10:10:00Z"},
            anomalies=[
                {
                    "rule_id": "CC_VALVE_SATURATING",
                    "message": "Cooling coil valve near saturation",
                    "severity": "high",
                }
            ],
            signature="sig-demo-2",
            summary_text=(
                f"{ahu_id} window 10:05–10:10Z: sa_temp_mean_minus_sp=+2.7C, "
                "cc_valve_mean=92%. anomalies=CC_VALVE_SATURATING"
            ),
        ),
    ]

    docs = [
        RetrievedDoc(
            corpus="manuals",
            doc_id="manual:cooling-coil::chunk::0",
            distance=0.12,
            text=(
                "If the cooling coil valve command is high but supply air temperature remains above setpoint, "
                "inspect for coil fouling, restricted airflow (filters), or insufficient chilled water flow. "
                "Verify actuator stroke and valve operation."
            ),
            metadata={
                "doc_id": "manual:cooling-coil",
                "chunk_type": "procedure",
                "page_start": 12,
                "page_end": 13,
                "title": "Cooling Coil Maintenance",
            },
        ),
        RetrievedDoc(
            corpus="past_cases",
            doc_id="past:cc-underperforming::chunk::1",
            distance=0.22,
            text=(
                "Past case: persistent SAT error with cc_valve near saturation. Likely root cause: coil heat-transfer "
                "degradation (fouling/reduced effectiveness). Steps: inspect coil face and filters; verify airflow; "
                "confirm chilled water availability; clean coil and retest."
            ),
            metadata={
                "doc_id": "past:cc-underperforming",
                "chunk_type": "case",
                "title": "CC underperforming",
            },
        ),
    ]

    return IncidentContext(
        incident_key=(ahu_id, detected_fault_type),
        ahu_id=ahu_id,
        detected_fault_type=detected_fault_type,
        seen_streak=4,
        clear_streak=0,
        last_seen_at="2026-01-27T10:10:00Z",
        recent_windows=windows,
        stage=1,
        retrieval_stats=RetrievalStats(
            manuals_count=1,
            past_cases_count=1,
            case_history_count=0,
            manuals_has_any=True,
            past_cases_has_any=True,
            min_distance=0.12,
            avg_distance=0.17,
            error=None,
        ),
        retrieved_docs=docs,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test for OpenAIReasoner.diagnose()")
    ap.add_argument(
        "--mode",
        choices=["cheap", "strong"],
        default="cheap",
        help="Select model strength preset for smoke testing (cheap=gpt-5-mini, strong=gpt-5.2)",
    )
    ap.add_argument(
        "--model", default=None, help="Explicit model override (highest priority)"
    )
    ap.add_argument(
        "--ahu-id",
        default="1",
        help="AHU id to filter when loading real windows (default: 1)",
    )
    ap.add_argument(
        "--fault-type",
        default="COOLING_COIL_FAULT",
        help="Detected fault type label for IncidentContext (default: COOLING_COIL_FAULT)",
    )
    ap.add_argument(
        "--windows-jsonl",
        default=str(REPO_ROOT / "data" / "generated" / "window_summaries.jsonl"),
        help="Path to real window_summaries JSONL (default: data/generated/window_summaries.jsonl)",
    )
    ap.add_argument(
        "--max-windows",
        type=int,
        default=8,
        help="Max windows to include from JSONL (default: 8)",
    )
    ap.add_argument(
        "--retrieval-output",
        default=str(REPO_ROOT / "output.txt"),
        help="Optional: path to Phase 4 retrieval demo output.txt (default: output.txt)",
    )
    ap.add_argument(
        "--query",
        type=int,
        default=1,
        help="Which Q section to parse from retrieval output (default: 1)",
    )
    ap.add_argument(
        "--show-prompts",
        action="store_true",
        help="Print the exact system/user prompt payload sent to the model",
    )
    ap.add_argument(
        "--debug-raw",
        action="store_true",
        help="Debug: print raw first-call model output (truncated) and exit",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout seconds for the OpenAI call",
    )
    ap.add_argument(
        "--max-output-tokens",
        type=int,
        default=1200,
        help="Max output tokens for the model response (default: 1200)",
    )
    args = ap.parse_args()

    mode = cast(Literal["cheap", "strong"], args.mode)

    # Note: The reasoner honors env vars (OPENAI_MODEL / OPENAI_MODEL_MODE).
    # For this smoke script, we want the CLI flag to be authoritative unless --model is provided.
    reasoner = OpenAIReasoner(mode=mode, timeout_s=float(args.timeout))
    reasoner.max_output_tokens = int(args.max_output_tokens)

    model_override: Optional[str]
    if args.model:
        model_override = str(args.model)
    elif mode == "strong":
        model_override = "gpt-5.2"
    else:
        model_override = "gpt-5-mini"

    # Load real windows if available; otherwise fall back to synthetic windows.
    windows_path = Path(str(args.windows_jsonl))
    windows = _load_windows_from_jsonl(
        jsonl_path=windows_path,
        ahu_id=str(args.ahu_id),
        max_windows=int(args.max_windows),
    )

    # Optionally parse real retrieval demo output.txt into RetrievedDoc items.
    ft_from_output: Optional[str] = None
    docs: list[RetrievedDoc] = []
    out_path = Path(str(args.retrieval_output))
    if out_path.exists():
        ft_from_output, docs = _parse_retrieval_output_docs(
            output_txt_path=out_path,
            query_index=int(args.query),
            max_per_corpus=3,
        )

    detected_fault_type = str(ft_from_output or args.fault_type)

    if windows:
        ctx = IncidentContext(
            incident_key=(str(args.ahu_id), detected_fault_type),
            ahu_id=str(args.ahu_id),
            detected_fault_type=detected_fault_type,
            seen_streak=4,
            clear_streak=0,
            last_seen_at=None,
            recent_windows=windows,
            stage=1,
            retrieval_stats=RetrievalStats(
                manuals_count=len([d for d in docs if d.corpus == "manuals"]),
                past_cases_count=len([d for d in docs if d.corpus == "past_cases"]),
                case_history_count=0,
                manuals_has_any=any(d.corpus == "manuals" for d in docs),
                past_cases_has_any=any(d.corpus == "past_cases" for d in docs),
                error=None,
            ),
            retrieved_docs=docs,
        )
    else:
        ctx = _sample_ctx(
            ahu_id=str(args.ahu_id), detected_fault_type=detected_fault_type
        )

    resolved_model = reasoner._resolve_model(
        model_override=model_override
    )  # noqa: SLF001
    print(f"Resolved model: {resolved_model}")
    print(f"OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")
    if windows_path.exists():
        print(f"Loaded windows from: {windows_path}")
        print(f"Windows included: {len(ctx.recent_windows)}")
    if out_path.exists():
        print(f"Parsed retrieval docs from: {out_path} (Q{int(args.query)})")
        print(f"Retrieved docs included: {len(ctx.retrieved_docs)}")

    if args.show_prompts:
        window_payload, window_ids = reasoner._windows_payload(
            ctx.recent_windows
        )  # noqa: SLF001
        docs_payload, doc_ids = reasoner._docs_payload(
            ctx.retrieved_docs
        )  # noqa: SLF001
        allowed = sorted(set(window_ids) | set(doc_ids))
        rule_ids = reasoner._top_rule_ids(ctx.recent_windows)  # noqa: SLF001
        symptom_summary = reasoner._symptom_summary(ctx.recent_windows)  # noqa: SLF001
        time_range = reasoner._overall_time_range(ctx.recent_windows)  # noqa: SLF001

        sys_msg = reasoner._system_prompt(allowed_evidence_ids=allowed)  # noqa: SLF001
        user_msg = reasoner._user_prompt(
            ctx=ctx,
            rule_ids=rule_ids,
            symptom_summary=symptom_summary,
            time_range=time_range,
            evidence_windows=window_payload,
            retrieved_docs=docs_payload,
            template=reasoner._load_template(),  # noqa: SLF001
        )

        print("\n=== SYSTEM PROMPT ===\n")
        print(sys_msg)
        print("\n=== USER PAYLOAD (JSON) ===\n")
        print(user_msg)

    if args.debug_raw:
        # Directly call the underlying OpenAI request once and print the raw text.
        window_payload, window_ids = reasoner._windows_payload(
            ctx.recent_windows
        )  # noqa: SLF001
        docs_payload, doc_ids = reasoner._docs_payload(
            ctx.retrieved_docs
        )  # noqa: SLF001
        allowed = sorted(set(window_ids) | set(doc_ids))
        rule_ids = reasoner._top_rule_ids(ctx.recent_windows)  # noqa: SLF001
        symptom_summary = reasoner._symptom_summary(ctx.recent_windows)  # noqa: SLF001
        time_range = reasoner._overall_time_range(ctx.recent_windows)  # noqa: SLF001

        sys_msg = reasoner._system_prompt(allowed_evidence_ids=allowed)  # noqa: SLF001
        user_msg = reasoner._user_prompt(
            ctx=ctx,
            rule_ids=rule_ids,
            symptom_summary=symptom_summary,
            time_range=time_range,
            evidence_windows=window_payload,
            retrieved_docs=docs_payload,
            template=reasoner._load_template(),  # noqa: SLF001
        )

        raw = reasoner._call_openai(  # noqa: SLF001
            api_key=os.getenv("OPENAI_API_KEY") or "",
            model=resolved_model,
            system_msg=sys_msg,
            user_msg=user_msg,
            max_output_tokens=int(args.max_output_tokens),
        )
        print("\n=== RAW MODEL OUTPUT (truncated) ===\n")
        print((raw or "")[:2000])
        return 0

    res = reasoner.diagnose(ctx, model_override=model_override)

    print("\n=== DiagnosisResult ===\n")
    # Pydantic v2
    as_dict: dict[str, Any] = res.model_dump()
    print(json.dumps(as_dict, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

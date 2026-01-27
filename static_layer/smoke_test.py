"""
Phase 4 Retrieval Smoke Test (Demo-Friendly)

Runs demo queries against both Chroma collections:
  - manuals      (engineering manuals / guidelines)
  - past_cases   (historical incident/case snippets)

Usage:
  1) python static_layer/build_manuals_index.py
  2) python static_layer/build_past_cases_index.py
  3) python static_layer/smoke_test.py

Output highlights:
  - Top-K hits
  - Provenance (doc_id/case_id + chunk/page metadata)
  - Distance score (lower is better) + a derived "similarity" indicator
"""

from __future__ import annotations

import argparse
import textwrap
from typing import Any, Dict, List

try:
    # Preferred: supports `python -m static_layer.smoke_test`
    from static_layer.retrievers import retrieve_manuals, retrieve_past_cases
except Exception:  # pragma: no cover
    # Fallback: allows `python static_layer/smoke_test.py` from repo root
    from retrievers import retrieve_manuals, retrieve_past_cases

# QUERIES = [
#     "SAT not tracking setpoint cc_valve high",
#     "mixed air temperature tracks return air damper",
#     "economizer ineffective oa damper stuck",
#     "avg_zone_temp drift but sat normal",
#     "cooling coil effectiveness reduced valve near max",
#     "damper linkage actuator inspection procedure",
# ]

QUERIES = [
    "fault_type=COOLING_COIL_FAULT\nrules=SAT_TOO_HIGH_WHEN_VALVE_HIGH, SAT_NOT_DROPPING_WHEN_VALVE_HIGH\nSupply air temperature remains high despite cooling valve command near max; SAT not dropping to setpoint under high cooling demand.",
    "fault_type=OA_DAMPER_STUCK\nrules=OA_DAMPER_STUCK_OR_FLATLINE\neconomizer ineffective; outside air damper position flatlines despite command changes; mixed air does not reflect outdoor air influence.",
    "fault_type=RA_DAMPER_STUCK\nrules=RA_DAMPER_STUCK_OR_FLATLINE\nmixed air temperature tracks return air; return air damper appears stuck or not modulating; MAT follows RAT over time.",
    "fault_type=ZONE_TEMP_SENSOR_DRIFT\nrules=ZONE_TEMP_PERSISTENT_TREND\navg_zone_temp shows persistent drift or trend while supply air temperature remains normal; possible zone temperature sensor bias or calibration drift.",
    "fault_type=COOLING_COIL_FAULT\nrules=SAT_NOT_DROPPING_WHEN_VALVE_HIGH\ncooling coil effectiveness reduced; chilled water valve near maximum but SAT remains elevated; insufficient heat transfer or flow issue.",
    "fault_type=OA_DAMPER_STUCK\nrules=OA_DAMPER_STUCK_OR_FLATLINE\ndamper linkage/actuator inspection procedure; outside air damper not responding to control signal; verify actuator, linkage binding, and position feedback.",
]


WRAP_WIDTH = 92


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 4 retrieval smoke test (manuals + past_cases)",
    )
    p.add_argument(
        "--query",
        type=str,
        default=None,
        help='Run a single query (demo mode), e.g. --query "economizer ineffective oa damper stuck"',
    )
    p.add_argument(
        "--top-k", type=int, default=3, help="Top-K results to print (default: 3)"
    )
    return p.parse_args()


def _fmt_score(distance: Any) -> str:
    """
    Chroma commonly returns a 'distance' (lower = closer).
    For demo clarity we print:
      - raw distance
      - a derived similarity score in [0,1]: score = 1/(1+distance)
    """
    try:
        d = float(distance)
        score = 1.0 / (1.0 + d)
        return f"distance={d:.4f}  score={score:.3f}"
    except Exception:
        return f"distance={distance}  score=N/A"


def _wrap(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "(empty snippet)"
    return "\n".join(textwrap.wrap(text, width=WRAP_WIDTH, subsequent_indent=" " * 6))


def _print_section_header(title: str, subtitle: str) -> None:
    print(f"\n  {title}")
    print(f"  {subtitle}")


def _print_results(results: List[Dict[str, Any]], kind: str, top_k: int) -> bool:
    if not results:
        print("    ❌ No results returned")
        return False

    shown = 0
    for idx, r in enumerate(results, start=1):
        md = r.get("metadata") or {}
        score = r.get("score")

        if kind == "manuals":
            page_start = md.get("page_start")
            page_end = md.get("page_end")
            if page_start is not None and page_end is not None:
                page_range = (
                    str(page_start)
                    if str(page_start) == str(page_end)
                    else f"{page_start}-{page_end}"
                )
            else:
                page_range = "N/A"
            prov = (
                f"doc_id={md.get('doc_id')} | file={md.get('file_name')} | "
                f"chunk_index={md.get('chunk_index')} | pages={page_range}"
            )
        else:
            prov = f"case_id={md.get('case_id')} | fault_type={md.get('fault_type')}"

        print(f"\n    #{idx}  id={r.get('id')}")
        print(f"        {_fmt_score(score)}")
        print(f"        {prov}")
        print(f"        snippet:")
        print(f"        {_wrap(r.get('text_snippet') or r.get('text') or '')}")

        shown += 1
        if shown >= top_k:
            break

    return True


def main() -> None:
    args = _parse_args()
    top_k = max(1, int(args.top_k))
    print("\nPHASE 4 RETRIEVAL DEMO — Chroma KB Smoke Test")
    print("Collections: manuals (static docs) + past_cases (historical incidents)\n")

    passed = 0

    queries = [args.query] if args.query else list(QUERIES)
    for i, q in enumerate(queries, start=1):
        print("=" * 96)
        print(f"Q{i}: {q}")

        manuals = retrieve_manuals(q, top_k=top_k)
        cases = retrieve_past_cases(q, top_k=top_k)

        _print_section_header(
            f"Manuals (Top {top_k})",
            "→ Static engineering references (diagnosis + procedures) with doc provenance",
        )
        ok_manuals = _print_results(manuals, kind="manuals", top_k=top_k)

        _print_section_header(
            f"Past Cases (Top {top_k})",
            "→ Historical incident snippets (what happened + what fixed it) with case provenance",
        )
        ok_cases = _print_results(cases, kind="past_cases", top_k=top_k)

        if ok_manuals and ok_cases:
            print("\n  ✅ PASS: Retrieved from BOTH collections")
            passed += 1
        else:
            print("\n  ⚠️  PARTIAL: One of the collections returned no hits")

    print("\n" + "=" * 96)
    print(
        f"Summary: {passed}/{len(queries)} queries retrieved results from both collections."
    )
    print("Done.\n")


if __name__ == "__main__":
    main()

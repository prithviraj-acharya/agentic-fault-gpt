"""
Phase 5 Retrieval Smoke Test (Window History)

Usage:
  1) python dynamic_layer/indexer_worker.py
  2) python dynamic_layer/smoke_test_history.py --query "cc_valve high" --top-k 5
"""

from __future__ import annotations

import argparse
import textwrap
from typing import Any, Dict, List

try:
    # Preferred: supports `python -m dynamic_layer.smoke_test_history`
    from dynamic_layer.retrievers import retrieve_window_history
except Exception:  # pragma: no cover
    from retrievers import retrieve_window_history

WRAP_WIDTH = 92


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 5 retrieval smoke test (window_history)",
    )
    p.add_argument(
        "--query",
        type=str,
        default="cc_valve high, sa_temp drift",
        help='Query string, e.g. --query "economizer damper stuck"',
    )
    p.add_argument(
        "--top-k", type=int, default=5, help="Top-K results to print (default: 5)"
    )
    return p.parse_args()


def _fmt_score(distance: Any) -> str:
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


def _print_results(results: List[Dict[str, Any]], top_k: int) -> None:
    if not results:
        print("No results returned")
        return

    shown = 0
    for idx, r in enumerate(results, start=1):
        md = r.get("metadata") or {}
        score = r.get("score")

        signature = md.get("signature")
        start = md.get("start")
        end = md.get("end")
        max_sev = md.get("max_severity")
        rule_ids = md.get("rule_ids")

        print(f"\n#{idx}  id={r.get('id')}")
        print(f"    {_fmt_score(score)}")
        print(
            f"    signature={signature} | start={start} | end={end} | "
            f"max_severity={max_sev} | rule_ids={rule_ids}"
        )
        print("    snippet:")
        print(f"    {_wrap(r.get('text') or '')}")

        shown += 1
        if shown >= top_k:
            break


def main() -> None:
    args = _parse_args()
    top_k = max(1, int(args.top_k))

    print("\nPHASE 5 RETRIEVAL DEMO - Window History\n")
    print(f"Query: {args.query}")
    results = retrieve_window_history(args.query, top_k=top_k)
    _print_results(results, top_k=top_k)
    print("\nDone.\n")


if __name__ == "__main__":
    main()

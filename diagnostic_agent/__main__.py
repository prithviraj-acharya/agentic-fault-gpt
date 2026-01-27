from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from diagnostic_agent.controller.controller import Phase6Controller
from diagnostic_agent.controller.controller import main as kafka_main
from diagnostic_agent.controller.controller import setup_logging
from diagnostic_agent.reasoner.mock_reasoner import MockReasoner

# Best-effort .env loading for local/dev usage.
# (Keeps production behavior unchanged: real deployments should set env vars explicitly.)
try:
    from dotenv import load_dotenv  # type: ignore

    REPO_ROOT = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=REPO_ROOT / ".env", override=False)
except Exception:
    pass


def _build_reasoner(
    *,
    kind: str,
    openai_mode: str,
    openai_model: str | None,
    timeout_s: float,
) -> object:
    if kind == "mock":
        return MockReasoner()

    # Lazy import so the repo can still run in mock-only setups.
    from diagnostic_agent.reasoner.openai_reasoner import OpenAIReasoner

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    # Mode selects the default model; --openai-model overrides.
    reasoner = OpenAIReasoner(
        mode=openai_mode if openai_mode in {"cheap", "strong"} else None,
        timeout_s=timeout_s,
    )
    if openai_model:
        reasoner.model = str(openai_model)
    return reasoner


def _run_replay(
    *,
    jsonl_path: str,
    max_lines: int | None,
    sleep_s: float,
    reasoner_kind: str,
    openai_mode: str,
    openai_model: str | None,
    timeout_s: float,
) -> None:
    setup_logging()
    reasoner = _build_reasoner(
        kind=reasoner_kind,
        openai_mode=openai_mode,
        openai_model=openai_model,
        timeout_s=timeout_s,
    )
    controller = Phase6Controller(reasoner=reasoner)  # type: ignore[arg-type]

    # Kafka loop stays off; we only need the diagnosis worker.
    controller.worker.start()

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if max_lines is not None and i >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if isinstance(raw, dict):
                controller.handle_window_summary(raw)
            if sleep_s > 0:
                time.sleep(sleep_s)

    # Wait for diagnosis jobs to drain.
    controller.jobs.join()
    controller.stop()


def cli() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(prog="diagnostic_agent", add_help=True)
    parser.add_argument(
        "--replay-jsonl",
        dest="replay_jsonl",
        default=None,
        help="Replay window summaries from a JSONL file (no Kafka).",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=None,
        help="Optional cap on number of JSONL records to process.",
    )
    parser.add_argument(
        "--sleep-s",
        type=float,
        default=0.0,
        help="Optional sleep between records (seconds) to simulate streaming.",
    )

    parser.add_argument(
        "--reasoner",
        choices=["mock", "openai"],
        default="mock",
        help="Which reasoner to use for replay mode (default: mock)",
    )
    parser.add_argument(
        "--openai-mode",
        choices=["cheap", "strong"],
        default="cheap",
        help="OpenAI model preset when --reasoner=openai (default: cheap)",
    )
    parser.add_argument(
        "--openai-model",
        default=None,
        help="Explicit OpenAI model override when --reasoner=openai",
    )
    parser.add_argument(
        "--openai-timeout-s",
        type=float,
        default=30.0,
        help="HTTP timeout seconds for OpenAI calls when --reasoner=openai (default: 30)",
    )

    args = parser.parse_args()

    if args.replay_jsonl:
        _run_replay(
            jsonl_path=args.replay_jsonl,
            max_lines=args.max_lines,
            sleep_s=float(args.sleep_s),
            reasoner_kind=str(args.reasoner),
            openai_mode=str(args.openai_mode),
            openai_model=(str(args.openai_model) if args.openai_model else None),
            timeout_s=float(args.openai_timeout_s),
        )
    else:
        kafka_main()


if __name__ == "__main__":  # pragma: no cover
    cli()

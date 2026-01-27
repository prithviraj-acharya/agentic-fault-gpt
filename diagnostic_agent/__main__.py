from __future__ import annotations

import argparse
import json
import time

from diagnostic_agent.controller.controller import Phase6Controller
from diagnostic_agent.controller.controller import main as kafka_main
from diagnostic_agent.controller.controller import setup_logging
from diagnostic_agent.reasoner.mock_reasoner import MockReasoner


def _run_replay(*, jsonl_path: str, max_lines: int | None, sleep_s: float) -> None:
    setup_logging()
    controller = Phase6Controller(reasoner=MockReasoner())

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

    args = parser.parse_args()

    if args.replay_jsonl:
        _run_replay(
            jsonl_path=args.replay_jsonl,
            max_lines=args.max_lines,
            sleep_s=float(args.sleep_s),
        )
    else:
        kafka_main()


if __name__ == "__main__":  # pragma: no cover
    cli()

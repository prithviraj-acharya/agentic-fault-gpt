from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from telemetry_pipeline.consumer import iter_telemetry_events


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test consumer for AHU telemetry events (Kafka)."
    )
    parser.add_argument(
        "--bootstrap-servers",
        default="localhost:9092",
        help="Kafka bootstrap servers (default: localhost:9092)",
    )
    parser.add_argument(
        "--topic",
        default="ahu.telemetry",
        help="Kafka topic name (default: ahu.telemetry)",
    )
    parser.add_argument(
        "--group-id",
        default="ahu-telemetry-smoke",
        help="Consumer group id (default: ahu-telemetry-smoke)",
    )
    parser.add_argument(
        "--from-beginning",
        action="store_true",
        help="If set, read from earliest offset (otherwise latest)",
    )
    parser.add_argument(
        "--min-interval-s",
        type=float,
        default=0.0,
        help="Minimum wall-clock seconds between processed messages (0 means no throttling) (default: 0)",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=0,
        help="Stop after N messages (0 means no message limit) (default: 0)",
    )
    parser.add_argument(
        "--idle-timeout-s",
        type=float,
        default=0.0,
        help="Stop if no message arrives for this many seconds (0 means run forever) (default: 0)",
    )
    # Backwards-compatible alias (kept for older docs/scripts).
    parser.add_argument(
        "--timeout-s",
        dest="idle_timeout_s",
        type=float,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (slower)",
    )

    args = parser.parse_args()

    if args.max_messages < 0:
        raise SystemExit("--max-messages must be >= 0")
    if args.idle_timeout_s < 0:
        raise SystemExit("--idle-timeout-s must be >= 0")
    if args.min_interval_s < 0:
        raise SystemExit("--min-interval-s must be >= 0")

    received = 0
    for event in iter_telemetry_events(
        bootstrap_servers=str(args.bootstrap_servers),
        topic=str(args.topic),
        group_id=str(args.group_id),
        from_beginning=bool(args.from_beginning),
        poll_timeout_s=1.0,
        idle_timeout_s=(
            float(args.idle_timeout_s) if float(args.idle_timeout_s) > 0 else None
        ),
        min_interval_s=(
            float(args.min_interval_s) if float(args.min_interval_s) > 0 else None
        ),
    ):
        if args.pretty:
            print(json.dumps(event, indent=2, sort_keys=True))
        else:
            print(json.dumps(event, separators=(",", ":"), sort_keys=False))

        received += 1
        if args.max_messages > 0 and received >= int(args.max_messages):
            break

    print(f"Consumed {received} messages from topic '{args.topic}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

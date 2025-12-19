from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from telemetry_pipeline.consumer import iter_kafka_events


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
        "--max-messages",
        type=int,
        default=10,
        help="Stop after N messages (0 means run until timeout) (default: 10)",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=10.0,
        help="Stop if no message arrives within this many seconds (default: 10)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (slower)",
    )

    args = parser.parse_args()

    if args.max_messages < 0:
        raise SystemExit("--max-messages must be >= 0")
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be > 0")

    received = 0
    for parsed in iter_kafka_events(
        bootstrap_servers=str(args.bootstrap_servers),
        topic=str(args.topic),
        group_id=str(args.group_id),
        from_beginning=bool(args.from_beginning),
        poll_timeout_s=float(args.timeout_s),
    ):
        if args.pretty and isinstance(parsed, dict):
            print(json.dumps(parsed, indent=2, sort_keys=True))
        else:
            if isinstance(parsed, dict):
                print(json.dumps(parsed, separators=(",", ":"), sort_keys=False))
            else:
                print(parsed)

        received += 1
        if args.max_messages > 0 and received >= int(args.max_messages):
            break

    print(f"Consumed {received} messages from topic '{args.topic}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

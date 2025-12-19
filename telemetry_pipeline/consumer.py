from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterator


def try_parse_json(data: bytes) -> Dict[str, Any] | str:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return data.decode("utf-8", errors="replace")


def iter_kafka_events(
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    from_beginning: bool,
    poll_timeout_s: float,
    idle_timeout_s: float | None = None,
    min_interval_s: float | None = None,
) -> Iterator[Dict[str, Any] | str]:
    """Iterate events from a Kafka topic.

    This is the reusable consumer primitive for Phase 3. Windowing/feature extraction
    should consume from this iterator rather than embedding Kafka-specific code.
    """

    try:
        from confluent_kafka import Consumer  # type: ignore
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "Kafka consumer requires confluent-kafka. Install it and retry: pip install confluent-kafka"
        ) from e

    auto_offset_reset = "earliest" if bool(from_beginning) else "latest"

    consumer = Consumer(
        {
            "bootstrap.servers": str(bootstrap_servers),
            "group.id": str(group_id),
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": True,
        }
    )

    consumer.subscribe([str(topic)])

    last_message_t = time.monotonic()
    last_yield_t: float | None = None

    try:
        while True:
            msg = consumer.poll(float(poll_timeout_s))
            if msg is None:
                if idle_timeout_s is not None and idle_timeout_s > 0:
                    if (time.monotonic() - last_message_t) >= float(idle_timeout_s):
                        return
                continue
            if msg.error() is not None:
                raise SystemExit(f"Kafka consumer error: {msg.error()}")

            value = msg.value()
            if value is None:
                continue
            last_message_t = time.monotonic()

            if min_interval_s is not None and float(min_interval_s) > 0.0:
                now = time.monotonic()
                if last_yield_t is not None:
                    remaining = float(min_interval_s) - (now - last_yield_t)
                    if remaining > 0:
                        time.sleep(remaining)
                last_yield_t = time.monotonic()
            yield try_parse_json(value)
    finally:
        consumer.close()

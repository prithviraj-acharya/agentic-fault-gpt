from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Generator, Optional

logger = logging.getLogger(__name__)


def _preview_bytes(data: bytes, *, limit: int = 256) -> bytes:
    if len(data) <= limit:
        return data
    return data[:limit] + b"...(truncated)"


def try_parse_json(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        parsed: Any = json.loads(data.decode("utf-8"))
    except Exception as e:
        logger.warning(
            "Failed to parse JSON: %s. Raw data (len=%d, preview=%r)",
            e,
            len(data),
            _preview_bytes(data),
        )
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "Skipping non-object JSON (type=%s). Raw data (len=%d, preview=%r)",
            type(parsed).__name__,
            len(data),
            _preview_bytes(data),
        )
        return None

    return parsed


def iter_kafka_events_raw(
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    from_beginning: bool,
    poll_timeout_s: float,
    idle_timeout_s: float | None = None,
    min_interval_s: float | None = None,
) -> Generator[Dict[str, Any], None, None]:
    """Iterate raw events from a Kafka topic (yields dicts, skips invalid JSON)."""
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

            last_message_t = time.monotonic()
            value = msg.value()
            if value is None:
                continue

            if min_interval_s is not None and float(min_interval_s) > 0.0:
                now = time.monotonic()
                if last_yield_t is not None:
                    remaining = float(min_interval_s) - (now - last_yield_t)
                    if remaining > 0:
                        time.sleep(remaining)
                last_yield_t = time.monotonic()

            parsed = try_parse_json(value)
            if parsed is None:
                # Already logged
                continue

            # Log Kafka metadata for traceability
            meta = {
                "partition": msg.partition(),
                "offset": msg.offset(),
                "kafka_timestamp": msg.timestamp()[1] if msg.timestamp() else None,
            }
            logger.debug("Kafka message meta: %s", meta)

            yield parsed
    finally:
        consumer.close()


def iter_telemetry_events(
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    from_beginning: bool,
    poll_timeout_s: float,
    idle_timeout_s: float | None = None,
    min_interval_s: float | None = None,
) -> Generator[Dict[str, Any], None, None]:
    """Yield normalized telemetry events matching `docs/specifications/simulation/telemetry_schema.md`.

    Output shape (flat):
      {"timestamp": str, "ahu_id": <str/int>, <signal>: <num|None>, ...}

    Accepts either:
      - flat payloads (signals at top-level)
      - nested payloads under `signals`
    """

    for event in iter_kafka_events_raw(
        bootstrap_servers=bootstrap_servers,
        topic=topic,
        group_id=group_id,
        from_beginning=from_beginning,
        poll_timeout_s=poll_timeout_s,
        idle_timeout_s=idle_timeout_s,
        min_interval_s=min_interval_s,
    ):
        ts = event.get("timestamp") or event.get("ts")
        ahu_id = event.get("ahu_id")
        signals = event.get("signals")

        if signals is None:
            signals = {
                k: v
                for k, v in event.items()
                if k not in ("ts", "timestamp", "ahu_id", "signals")
            }

        if ts is None or ahu_id is None or not isinstance(signals, dict):
            logger.warning("Skipping event missing required fields: %r", event)
            continue

        if not isinstance(ts, str):
            ts = str(ts)

        out: Dict[str, Any] = {"timestamp": ts, "ahu_id": ahu_id}
        for k, v in signals.items():
            out[str(k)] = v

        yield out

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol


class SummarySink(Protocol):
    def publish(self, summary: Dict[str, Any]) -> None: ...

    def close(self) -> None: ...


@dataclass
class JsonlSink:
    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8", newline="\n")

    def publish(self, summary: Dict[str, Any]) -> None:
        line = json.dumps(summary, sort_keys=True, separators=(",", ":"))
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.flush()
        finally:
            self._fh.close()


class KafkaSink:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic: str,
        key_field: str = "ahu_id",
        client_id: str = "ahu-window-summaries",
        flush_timeout_s: float = 10.0,
    ) -> None:
        self._topic = str(topic)
        self._key_field = str(key_field)
        self._flush_timeout_s = float(flush_timeout_s)

        try:
            from confluent_kafka import Producer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Kafka sink requires confluent-kafka. Install it: pip install confluent-kafka"
            ) from e

        self._producer = Producer(
            {
                "bootstrap.servers": str(bootstrap_servers),
                "client.id": str(client_id),
            }
        )

    def _on_delivery(self, err, msg) -> None:  # pragma: no cover
        if err is not None:
            raise RuntimeError(f"Kafka delivery failed: {err}")

    def publish(self, summary: Dict[str, Any]) -> None:  # pragma: no cover
        payload = json.dumps(summary, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        key_val = summary.get(self._key_field)
        key = None if key_val is None else str(key_val).encode("utf-8")

        while True:
            try:
                self._producer.produce(
                    self._topic, value=payload, key=key, on_delivery=self._on_delivery
                )
                break
            except BufferError:
                self._producer.poll(0.1)

        self._producer.poll(0)

    def close(self) -> None:  # pragma: no cover
        self._producer.flush(self._flush_timeout_s)

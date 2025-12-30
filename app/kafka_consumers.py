from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, Iterable, Optional

from app.config import Settings
from app.stores import TelemetryStore, WindowStore
from app.utils import parse_iso8601

logger = logging.getLogger(__name__)


def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        try:
            if v != v:  # NaN
                return None
        except Exception:
            pass
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.lower() in {"nan", "none", "null"}:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def normalize_telemetry_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ahu_id = raw.get("ahu_id")
    if ahu_id is None:
        return None

    ts_raw = raw.get("ts") or raw.get("timestamp")
    if not isinstance(ts_raw, str):
        ts_raw = str(ts_raw) if ts_raw is not None else ""
    ts = parse_iso8601(ts_raw)
    if ts is None:
        return None

    values: Dict[str, float] = {}

    nested = raw.get("values")
    if isinstance(nested, dict):
        source = nested
    else:
        nested2 = raw.get("signals")
        source = nested2 if isinstance(nested2, dict) else raw

    for k, v in source.items():
        key = str(k)
        if key in {"ahu_id", "ts", "timestamp", "values", "signals"}:
            continue
        fv = _coerce_float(v)
        if fv is None:
            continue
        values[key] = fv

    return {"ahu_id": str(ahu_id), "ts": ts, "values": values}


def normalize_window_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    window_id = raw.get("window_id")
    ahu_id = raw.get("ahu_id")
    signature = raw.get("signature")

    t = raw.get("time")
    if not isinstance(t, dict):
        return None
    start = t.get("start")
    end = t.get("end")

    if not window_id or ahu_id is None or not signature:
        return None
    if not isinstance(start, str) or not isinstance(end, str):
        return None

    # Ensure parsable times (store raw object as-is, but validate minimally)
    if parse_iso8601(start) is None or parse_iso8601(end) is None:
        return None

    return raw


class KafkaIngest:
    def __init__(
        self,
        *,
        settings: Settings,
        telemetry_store: TelemetryStore,
        window_store: WindowStore,
    ) -> None:
        self.settings = settings
        self.telemetry_store = telemetry_store
        self.window_store = window_store

        replay = bool(getattr(self.settings, "kafka_replay_on_startup", False))
        self._group_suffix = f"-{int(time.time())}" if replay else ""

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self._threads = [
            threading.Thread(
                target=self._run_telemetry_consumer,
                name="kafka-telemetry-consumer",
                daemon=True,
            ),
            threading.Thread(
                target=self._run_window_consumer,
                name="kafka-window-consumer",
                daemon=True,
            ),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()

    def _consumer(self, *, group_id: str, topics: Iterable[str]):
        try:
            from confluent_kafka import Consumer  # type: ignore
        except Exception as e:  # pragma: no cover
            logger.error("confluent-kafka not available (%s); Kafka ingest disabled", e)
            return None

        c = Consumer(
            {
                "bootstrap.servers": self.settings.kafka_bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": self.settings.kafka_auto_offset_reset,
                "enable.auto.commit": True,
            }
        )
        c.subscribe(list(topics))
        return c

    def _run_telemetry_consumer(self) -> None:
        prefix = str(
            getattr(self.settings, "kafka_consumer_group_prefix", "dashboard")
            or "dashboard"
        )
        c = self._consumer(
            group_id=f"{prefix}-telemetry{self._group_suffix}",
            topics=self.settings.kafka_telemetry_topics,
        )
        if c is None:
            return

        try:
            while not self._stop.is_set():
                msg = c.poll(0.5)
                if msg is None:
                    continue
                if msg.error() is not None:
                    logger.warning("Telemetry consumer error: %s", msg.error())
                    continue

                value = msg.value()
                if value is None:
                    continue

                try:
                    raw = json.loads(value.decode("utf-8"))
                except Exception:
                    logger.warning("Invalid telemetry JSON; skipping")
                    continue

                if not isinstance(raw, dict):
                    continue

                try:
                    norm = normalize_telemetry_event(raw)
                    if norm is None:
                        continue
                    self.telemetry_store.add(norm["ahu_id"], norm["ts"], norm["values"])
                except Exception as e:
                    logger.warning("Telemetry handling error: %s", e)
        finally:
            try:
                c.close()
            except Exception:
                pass

    def _run_window_consumer(self) -> None:
        prefix = str(
            getattr(self.settings, "kafka_consumer_group_prefix", "dashboard")
            or "dashboard"
        )
        c = self._consumer(
            group_id=f"{prefix}-windows{self._group_suffix}",
            topics=self.settings.kafka_window_topics,
        )
        if c is None:
            return

        try:
            while not self._stop.is_set():
                msg = c.poll(0.5)
                if msg is None:
                    continue
                if msg.error() is not None:
                    logger.warning("Window consumer error: %s", msg.error())
                    continue

                value = msg.value()
                if value is None:
                    continue

                try:
                    raw = json.loads(value.decode("utf-8"))
                except Exception:
                    logger.warning("Invalid window JSON; skipping")
                    continue

                if not isinstance(raw, dict):
                    continue

                try:
                    norm = normalize_window_event(raw)
                    if norm is None:
                        continue
                    self.window_store.add(norm)
                except Exception as e:
                    logger.warning("Window handling error: %s", e)
        finally:
            try:
                c.close()
            except Exception:
                pass

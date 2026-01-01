from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Protocol

import pandas as pd

from simulation.simulator import (
    build_metadata,
    iter_telemetry_events,
    load_and_validate_scenario,
)
from simulation.utils import (
    FaultEpisode,
    parse_iso8601,
    shift_window_and_episodes_to_start,
)


class EventSink(Protocol):
    def publish(self, event: Dict[str, Any]) -> None: ...

    def close(self) -> None: ...


@dataclass
class LocalPrintSink:
    """Local sink that prints one JSON event per line."""

    pretty: bool = False
    _disabled: bool = False

    def publish(self, event: Dict[str, Any]) -> None:
        # When piping to commands like PowerShell `Select-Object -First N`, the
        # downstream may close stdout early. Further writes can raise BrokenPipeError
        # or OSError; in that case we disable printing but continue generation.
        if self._disabled:
            return
        if self.pretty:
            try:
                print(json.dumps(event, indent=2, sort_keys=True))
            except (BrokenPipeError, OSError):
                self._disabled = True
        else:
            try:
                print(json.dumps(event, separators=(",", ":"), sort_keys=False))
            except (BrokenPipeError, OSError):
                self._disabled = True

    def close(self) -> None:
        return


class KafkaSink:
    """Kafka sink placeholder.

    This is intentionally implemented as an optional adapter so you can validate
    event format + replay timing locally first.
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic: str,
        key_field: str = "ahu_id",
        client_id: str = "ahu-telemetry-producer",
        flush_timeout_s: float = 10.0,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._key_field = key_field
        self._client_id = client_id
        self._flush_timeout_s = float(flush_timeout_s)

        # Lazy import so local mode works without Kafka dependencies.
        try:
            from confluent_kafka import Producer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Kafka mode requires confluent-kafka. Install it and retry: pip install confluent-kafka"
            ) from e

        self._producer = Producer(
            {
                "bootstrap.servers": self._bootstrap_servers,
                "client.id": self._client_id,
            }
        )

    def _on_delivery(self, err, msg) -> None:  # pragma: no cover
        if err is not None:
            # Surface delivery errors clearly in local dev.
            raise RuntimeError(f"Kafka delivery failed: {err}")

    def publish(self, event: Dict[str, Any]) -> None:  # pragma: no cover
        payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
        key_val = event.get(self._key_field)
        key = None if key_val is None else str(key_val).encode("utf-8")

        # Backpressure: if the local producer queue is full, poll and retry.
        while True:
            try:
                self._producer.produce(
                    self._topic, value=payload, key=key, on_delivery=self._on_delivery
                )
                break
            except BufferError:
                self._producer.poll(0.1)

        # Poll to serve delivery callbacks and keep internal buffers moving.
        self._producer.poll(0)

    def close(self) -> None:  # pragma: no cover
        self._producer.flush(self._flush_timeout_s)


@dataclass
class TeeSink:
    sinks: List[EventSink]

    def publish(self, event: Dict[str, Any]) -> None:
        for sink in self.sinks:
            sink.publish(event)

    def close(self) -> None:
        # Close in reverse order (helps flush external resources first).
        for sink in reversed(self.sinks):
            sink.close()


class CsvFileSink:
    def __init__(self, *, path: Path, fieldnames: List[str]) -> None:
        self._path = path
        self._fieldnames = fieldnames
        self._fh = path.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._fh, fieldnames=self._fieldnames)
        self._writer.writeheader()
        # Ensure header is visible even if the process is interrupted early.
        self._fh.flush()

    def publish(self, event: Dict[str, Any]) -> None:
        # Enforce that all requested columns are present.
        missing = [k for k in self._fieldnames if k not in event]
        if missing:
            raise ValueError(f"Event missing required fields for CSV: {missing}")
        self._writer.writerow({k: event.get(k) for k in self._fieldnames})
        # Keep the file non-empty/progressing during streaming.
        self._fh.flush()

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()


def _iter_events_from_csv(path: Path) -> Iterator[Dict[str, Any]]:
    df = pd.read_csv(path)
    if df.empty:
        return

    # For replay timing we need timestamps.
    if "timestamp" not in df.columns:
        raise ValueError(
            "telemetry CSV must include a 'timestamp' column. "
            "Ensure your scenario 'signals' includes 'timestamp'."
        )

    # Preserve the row payload exactly as in CSV.
    for row in df.to_dict(orient="records"):
        # pandas may type keys as Hashable; normalize to str for consistent event schema.
        yield {str(k): v for k, v in row.items()}


def _replay(
    events: Iterable[Dict[str, Any]],
    *,
    sink: EventSink,
    speed: float,
    emit_interval_s: float | None = None,
    max_events: int | None = None,
) -> int:
    """Replay events in timestamp order.

    speed:
      - 1.0 = real-time gaps
      - 2.0 = 2x faster (sleep half as long)
      - 0.0 = no sleeping (as fast as possible)

        emit_interval_s:
            - If set to a value > 0, sleeps a fixed number of seconds between emitted
                events and overrides timestamp-based sleeping via `speed`.
    """

    prev_ts = None
    count = 0
    try:
        for event in events:
            if max_events is not None and max_events >= 0 and count >= max_events:
                break
            ts_raw = event.get("timestamp")
            if not isinstance(ts_raw, str) or not ts_raw.strip():
                raise ValueError("Event missing non-empty 'timestamp' field")
            ts = parse_iso8601(ts_raw)

            if emit_interval_s is None or emit_interval_s <= 0.0:
                if prev_ts is not None and speed > 0.0:
                    gap_s = (ts - prev_ts).total_seconds()
                    if gap_s > 0:
                        time.sleep(gap_s / speed)

            sink.publish(event)
            prev_ts = ts
            count += 1

            if emit_interval_s is not None and emit_interval_s > 0.0:
                # Sleep *after* publishing so the first event is immediate.
                # Don't sleep after the last emitted event.
                if max_events is None or count < max_events:
                    time.sleep(float(emit_interval_s))
    finally:
        sink.close()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay generated telemetry as a local stream (Kafka-ready adapter)"
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--scenario",
        type=Path,
        help="Path to scenario JSON to generate events from (streams while generating)",
    )
    source.add_argument(
        "--input",
        type=Path,
        help="Explicit path to a telemetry CSV (replay mode)",
    )
    source.add_argument(
        "--run-id",
        type=str,
        help="Run id to replay from data/generated/<run_id>_telemetry.csv (replay mode)",
    )

    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=Path("data/generated"),
        help="Directory that contains generated telemetry files (default: data/generated)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/generated"),
        help="Output directory for generated CSV/metadata (scenario mode only; default: data/generated)",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "kafka"],
        default="local",
        help="Output mode: local prints JSON lines; kafka publishes to a topic.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=0.0,
        help="Replay speed factor: 1.0=real-time, 2.0=2x faster, 0=as fast as possible",
    )
    parser.add_argument(
        "--emit-interval-s",
        "--emit-interval-sec",
        type=float,
        default=None,
        help=(
            "If set to > 0, sleep a fixed number of seconds between emitted events "
            "(overrides timestamp-based replay via --speed)"
        ),
    )
    parser.add_argument(
        "--start-now",
        action="store_true",
        help=(
            "Shift scenario timestamps so the run starts at current UTC time, while keeping "
            "fault episode offsets the same (scenario mode only)"
        ),
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="If > 0, stop after emitting this many events (useful for quick previews)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON in local mode (slower).",
    )

    # Kafka options (used only in --mode kafka)
    parser.add_argument(
        "--bootstrap-servers",
        default="localhost:9092",
        help="Kafka bootstrap servers (kafka mode only)",
    )
    parser.add_argument(
        "--topic",
        default="ahu.telemetry",
        help="Kafka topic name (kafka mode only)",
    )
    parser.add_argument(
        "--key-field",
        default="ahu_id",
        help="Event field used as Kafka message key (kafka mode only)",
    )

    parser.add_argument(
        "--client-id",
        default="ahu-telemetry-producer",
        help="Kafka client.id (kafka mode only)",
    )
    parser.add_argument(
        "--flush-timeout-s",
        type=float,
        default=10.0,
        help="Flush timeout in seconds on shutdown (kafka mode only)",
    )

    args = parser.parse_args()

    if args.speed < 0.0:
        raise SystemExit("--speed must be >= 0")
    if args.emit_interval_s is not None and args.emit_interval_s < 0.0:
        raise SystemExit("--emit-interval-s must be >= 0")
    if args.max_events < 0:
        raise SystemExit("--max-events must be >= 0")

    # Primary stream sink.
    if args.mode == "local":
        base_sink = LocalPrintSink(pretty=bool(args.pretty))
    else:
        base_sink = KafkaSink(
            bootstrap_servers=str(args.bootstrap_servers),
            topic=str(args.topic),
            key_field=str(args.key_field),
            client_id=str(args.client_id),
            flush_timeout_s=float(args.flush_timeout_s),
        )

    # Scenario mode: generate events using the simulator's shared generator, while
    # simultaneously writing CSV + metadata to --out.
    if args.scenario is not None:
        scenario_path = args.scenario
        if not scenario_path.is_absolute():
            scenario_path = Path.cwd() / scenario_path

        scenario, start_time, end_time, interval_sec, episodes = (
            load_and_validate_scenario(scenario_path=scenario_path)
        )

        if bool(args.start_now):
            start_time, end_time, episodes = shift_window_and_episodes_to_start(
                start_time=start_time,
                end_time=end_time,
                episodes=episodes,
                new_start_time=datetime.now(timezone.utc),
            )

        signals = list(scenario["signals"])
        if "timestamp" not in signals:
            raise SystemExit(
                "Scenario 'signals' must include 'timestamp' for streaming"
            )
        if "ahu_id" not in signals:
            raise SystemExit("Scenario 'signals' must include 'ahu_id' for streaming")

        out_dir = args.out
        if not out_dir.is_absolute():
            out_dir = Path.cwd() / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        run_id = str(scenario["run_id"])
        telemetry_path = out_dir / f"{run_id}_telemetry.csv"
        metadata_path = out_dir / f"{run_id}_metadata.json"

        # Metadata is purely scenario-derived, so write it up-front.
        # This also ensures the file exists even if stdout piping stops the process early
        # (e.g., PowerShell `Select-Object -First N` terminates upstream producers).
        metadata = build_metadata(
            scenario=scenario,
            scenario_path=scenario_path,
            start_time=start_time,
            end_time=end_time,
            interval_sec=interval_sec,
            episodes=episodes,
        )
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        csv_sink = CsvFileSink(path=telemetry_path, fieldnames=signals)

        # Build final sink list:
        # - Always write CSV
        # - Stream to selected mode (local stdout OR kafka)
        sinks: List[EventSink] = [csv_sink]

        sinks.append(base_sink)

        sink = TeeSink(sinks)

        events = iter_telemetry_events(
            scenario=scenario,
            start_time=start_time,
            end_time=end_time,
            interval_sec=interval_sec,
            episodes=episodes,
        )

        max_events = None if args.max_events == 0 else int(args.max_events)
        count = _replay(
            events,
            sink=sink,
            speed=float(args.speed),
            emit_interval_s=args.emit_interval_s,
            max_events=max_events,
        )

        print(f"Streamed {count} events from scenario: {scenario_path}")
        print(f"Wrote telemetry: {telemetry_path}")
        print(f"Wrote metadata: {metadata_path}")
        return 0

    # Replay mode: replay from an existing telemetry CSV.
    if args.input is not None:
        input_path = args.input
    else:
        generated_dir = args.generated_dir
        if not generated_dir.is_absolute():
            generated_dir = Path.cwd() / generated_dir
        input_path = generated_dir / f"{args.run_id}_telemetry.csv"

    if not input_path.is_absolute():
        input_path = Path.cwd() / input_path
    if not input_path.exists():
        raise SystemExit(f"Telemetry file not found: {input_path}")

    events = _iter_events_from_csv(input_path)
    max_events = None if args.max_events == 0 else int(args.max_events)

    count = _replay(
        events,
        sink=base_sink,
        speed=float(args.speed),
        emit_interval_s=args.emit_interval_s,
        max_events=max_events,
    )
    print(f"Replayed {count} events from {input_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

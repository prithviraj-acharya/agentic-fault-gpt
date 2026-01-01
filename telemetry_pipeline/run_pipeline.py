from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping

from simulation.utils import validate_scenario
from telemetry_pipeline.config_loader import load_frozen_configs
from telemetry_pipeline.consumer import iter_telemetry_events
from telemetry_pipeline.features import extract_features
from telemetry_pipeline.ordering import PerAhuOrderingBuffer
from telemetry_pipeline.rules import RuleEngine
from telemetry_pipeline.sinks import JsonlSink, KafkaSink, SummarySink
from telemetry_pipeline.summarizer import build_window_summary
from telemetry_pipeline.validator import EventValidator
from telemetry_pipeline.windowing import WindowManager

logger = logging.getLogger(__name__)


def _iter_events_from_csv(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # csv gives strings; keep as-is and let validator coerce.
            yield {str(k): v for k, v in row.items()}


def _build_sink(args: argparse.Namespace) -> SummarySink:
    if args.sink == "jsonl":
        if not args.out:
            raise SystemExit("--out is required for sink=jsonl")
        return JsonlSink(Path(args.out))

    if args.sink == "kafka":
        if not args.bootstrap_servers or not args.summary_topic:
            raise SystemExit(
                "--bootstrap-servers and --summary-topic required for sink=kafka"
            )
        return KafkaSink(
            bootstrap_servers=args.bootstrap_servers, topic=args.summary_topic
        )

    raise SystemExit(f"Unsupported sink: {args.sink}")


def _align_floor_epoch(ts: datetime, *, window_size_sec: int) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    epoch = int(ts.timestamp())
    aligned = epoch - (epoch % int(window_size_sec))
    return datetime.fromtimestamp(aligned, tz=timezone.utc)


def _load_fault_episode_offsets(scenario_path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("scenario must be a JSON object")

    scenario_start, _scenario_end, _interval, episodes = validate_scenario(raw)

    out: List[Dict[str, Any]] = []
    for ep in episodes:
        out.append(
            {
                "episode_id": ep.episode_id,
                "fault_type": ep.fault_type,
                "start_offset_sec": (ep.start_time - scenario_start).total_seconds(),
                "end_offset_sec": (ep.end_time - scenario_start).total_seconds(),
            }
        )

    # Ensure deterministic order
    out.sort(key=lambda x: (float(x["start_offset_sec"]), str(x["episode_id"])))
    return out


def _is_within_any_episode(offset_sec: float, episodes: List[Dict[str, Any]]) -> bool:
    for ep in episodes:
        start_s = float(ep["start_offset_sec"])
        end_s = float(ep["end_offset_sec"])
        if start_s <= offset_sec < end_s:
            return True
    return False


def run_pipeline(
    events: Iterable[Mapping[str, Any]],
    *,
    config_dir: Path,
    sink: SummarySink,
    scenario_episode_offsets: List[Dict[str, Any]] | None = None,
    gate_anomalies_to_scenario: bool = False,
) -> int:
    cfg = load_frozen_configs(config_dir=config_dir)
    signals_cfg = cfg["signals"]
    windowing_cfg = cfg["windowing"]
    rules_cfg = cfg["rules"]
    fingerprint = cfg.get("fingerprint")

    validator = EventValidator(signals_cfg=signals_cfg, windowing_cfg=windowing_cfg)

    ordering_cfg = dict(windowing_cfg.get("ordering", {}))
    ordering = PerAhuOrderingBuffer(
        reorder_buffer_sec=int(ordering_cfg.get("reorder_buffer_sec", 0) or 0),
        enable_dedup=bool(ordering_cfg.get("enable_dedup", True)),
        dedup_key_fields=list(
            ordering_cfg.get("dedup_key_fields", ["ahu_id", "timestamp"])
        ),
    )

    win_cfg = dict(windowing_cfg.get("windowing", {}))
    window_mgr = WindowManager(
        window_type=str(win_cfg.get("window_type", "tumbling")),
        window_size_sec=int(win_cfg.get("window_size_sec", 300)),
        step_sec=win_cfg.get("step_sec"),
        align_to_epoch=bool(win_cfg.get("align_to_epoch", True)),
        signals_cfg=signals_cfg,
    )

    engine = RuleEngine(rules_cfg=rules_cfg, signals_cfg=signals_cfg)
    num_signals = len(dict(signals_cfg.get("signals", {})))

    rule_meta = dict(rules_cfg.get("rules", {}))

    emitted = 0

    # For relative-time alignment: remember the telemetry run's "t=0" per AHU
    # using the same alignment strategy as WindowManager.
    base_ts_by_ahu: Dict[str, datetime] = {}

    def _process_closed_window(window) -> None:
        nonlocal emitted
        features = extract_features(window, signals_cfg=signals_cfg)
        stats = dict(window.stats)
        stats["num_signals"] = num_signals
        anomalies = engine.evaluate(features, stats=stats)

        if gate_anomalies_to_scenario and scenario_episode_offsets is not None:
            base_ts = base_ts_by_ahu.get(str(window.ahu_id))
            if base_ts is None:
                anomalies = []
            else:
                offset_sec = (window.start - base_ts).total_seconds()
                if not _is_within_any_episode(offset_sec, scenario_episode_offsets):
                    anomalies = []

        # Optional annotation: tie symptom rules to likely fault hypotheses.
        # This is metadata for downstream interpretation only; it does not affect detection.
        for a in anomalies:
            rid = a.get("rule_id")
            meta = rule_meta.get(rid, {}) if rid else {}
            symptom = meta.get("symptom")
            if symptom:
                a.setdefault("symptom", symptom)
            fh = meta.get("fault_hypotheses")
            if isinstance(fh, list) and fh:
                a.setdefault("fault_hypotheses", sorted({str(x) for x in fh if x}))

        summary = build_window_summary(
            window=window,
            features=features,
            anomalies=anomalies,
            config_fingerprint=fingerprint,
        )
        sink.publish(summary)
        emitted += 1

    try:
        for raw in events:
            ev = validator.validate_and_normalize(raw)
            if ev is None:
                continue

            if str(ev.ahu_id) not in base_ts_by_ahu:
                if bool(win_cfg.get("align_to_epoch", True)):
                    base_ts_by_ahu[str(ev.ahu_id)] = _align_floor_epoch(
                        ev.timestamp,
                        window_size_sec=int(win_cfg.get("window_size_sec", 300)),
                    )
                else:
                    base_ts_by_ahu[str(ev.ahu_id)] = ev.timestamp.replace(microsecond=0)

            pushed = ordering.push(ev)
            if pushed.is_duplicate:
                for w in window_mgr.add_duplicate(
                    ahu_id=ev.ahu_id, timestamp=ev.timestamp
                ):
                    _process_closed_window(w)
                continue

            for _eid, ordered_ev in pushed.ready:
                for w in window_mgr.add_event(ordered_ev):
                    _process_closed_window(w)

        for _eid, ev2 in ordering.flush():
            for w in window_mgr.add_event(ev2):
                _process_closed_window(w)

        for w in window_mgr.flush():
            _process_closed_window(w)

        return emitted
    finally:
        sink.close()


def main(argv: List[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    p = argparse.ArgumentParser(
        description="Phase 3 telemetry pipeline: window summaries"
    )
    p.add_argument(
        "--config-dir",
        default=str(Path("telemetry_pipeline") / "config"),
        help="Config directory containing signals.yaml/windowing.yaml/rules.yaml",
    )

    p.add_argument("--mode", choices=["csv", "kafka"], default="csv")

    p.add_argument(
        "--csv",
        default=str(Path("data") / "generated" / "ahu_sim_run_001_telemetry.csv"),
    )

    p.add_argument("--bootstrap-servers", default="localhost:9092")
    p.add_argument("--topic", default="ahu.telemetry")
    p.add_argument("--group-id", default="ahu-phase3")
    p.add_argument("--from-beginning", action="store_true")

    p.add_argument("--sink", choices=["jsonl", "kafka"], default="jsonl")
    p.add_argument(
        "--out",
        default=str(Path("data") / "generated" / "window_summaries.jsonl"),
        help="Output JSONL path (sink=jsonl)",
    )
    p.add_argument(
        "--summary-topic",
        default="window_summaries",
        help="Kafka topic for summaries (sink=kafka)",
    )

    p.add_argument(
        "--scenario",
        default=None,
        help="Optional scenario JSON path (enables relative-time fault episode gating when used with --gate-to-scenario)",
    )
    p.add_argument(
        "--gate-to-scenario",
        action="store_true",
        help="If set, suppress anomalies outside the scenario's fault episode time spans (relative-time aligned)",
    )

    args = p.parse_args(argv)

    config_dir = Path(args.config_dir)

    base_sink = _build_sink(args)
    sink: SummarySink
    if str(args.sink) == "kafka":
        # Desired behavior: keep publishing to Kafka, but also overwrite and capture
        # the emitted window summaries to the JSONL file at --out (default path).
        jsonl_sink = JsonlSink(Path(args.out))

        class _TeeSink:
            def __init__(self, a: SummarySink, b: SummarySink) -> None:
                self._a = a
                self._b = b

            def publish(self, summary: Dict[str, Any]) -> None:
                self._a.publish(summary)
                self._b.publish(summary)

            def close(self) -> None:
                try:
                    self._a.close()
                finally:
                    self._b.close()

        sink = _TeeSink(base_sink, jsonl_sink)
    else:
        sink = base_sink

    if args.mode == "csv":
        events = _iter_events_from_csv(Path(args.csv))
    else:
        events = iter_telemetry_events(
            bootstrap_servers=str(args.bootstrap_servers),
            topic=str(args.topic),
            group_id=str(args.group_id),
            from_beginning=bool(args.from_beginning),
            poll_timeout_s=1.0,
            idle_timeout_s=None,
            min_interval_s=None,
        )

    scenario_episode_offsets: List[Dict[str, Any]] | None = None
    if bool(args.gate_to_scenario):
        if not args.scenario:
            raise SystemExit("--scenario is required when using --gate-to-scenario")
        scenario_episode_offsets = _load_fault_episode_offsets(Path(args.scenario))
        logger.info(
            "Scenario gating enabled (%d fault episodes)",
            len(scenario_episode_offsets),
        )

    emitted = run_pipeline(
        events,
        config_dir=config_dir,
        sink=sink,
        scenario_episode_offsets=scenario_episode_offsets,
        gate_anomalies_to_scenario=bool(args.gate_to_scenario),
    )
    logger.info("Emitted %d window summaries", emitted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

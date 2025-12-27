from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping

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


def run_pipeline(
    events: Iterable[Mapping[str, Any]], *, config_dir: Path, sink: SummarySink
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

    def _process_closed_window(window) -> None:
        nonlocal emitted
        features = extract_features(window, signals_cfg=signals_cfg)
        stats = dict(window.stats)
        stats["num_signals"] = num_signals
        anomalies = engine.evaluate(features, stats=stats)

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

    for raw in events:
        ev = validator.validate_and_normalize(raw)
        if ev is None:
            continue

        pushed = ordering.push(ev)
        if pushed.is_duplicate:
            for w in window_mgr.add_duplicate(ahu_id=ev.ahu_id, timestamp=ev.timestamp):
                _process_closed_window(w)
            continue

        for _eid, ordered_ev in pushed.ready:
            for w in window_mgr.add_event(ordered_ev):
                _process_closed_window(w)

    for _eid, ev in ordering.flush():
        for w in window_mgr.add_event(ev):
            _process_closed_window(w)

    for w in window_mgr.flush():
        _process_closed_window(w)

    sink.close()
    return emitted


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

    args = p.parse_args(argv)

    config_dir = Path(args.config_dir)
    sink = _build_sink(args)

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

    emitted = run_pipeline(events, config_dir=config_dir, sink=sink)
    logger.info("Emitted %d window summaries", emitted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

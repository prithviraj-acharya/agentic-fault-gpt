from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

from dotenv import load_dotenv

from app.utils import parse_iso8601
from dynamic_layer.config import Settings, load_settings

load_dotenv()

logger = logging.getLogger(__name__)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        try:
            if value != value:  # NaN
                return None
        except Exception:
            pass
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _coerce_int(value: Any) -> Optional[int]:
    f = _coerce_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except Exception:
        return None


def _compact_text(text: Any, limit: int) -> str:
    if text is None:
        return ""
    s = str(text).replace("\n", " ").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 3)] + "..."


def _build_doc_id(raw: Dict[str, Any]) -> str:
    window_id = str(raw.get("window_id") or "").strip()
    if window_id:
        return window_id

    ahu_id = str(raw.get("ahu_id") or "").strip()
    signature = str(raw.get("signature") or "").strip()
    time_obj = raw.get("time")
    t = time_obj if isinstance(time_obj, dict) else {}
    start = str(t.get("start") or "").strip()
    end = str(t.get("end") or "").strip()
    payload = f"{ahu_id}|{window_id}|{start}|{end}|{signature}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _extract_rule_ids(anomalies: Any) -> Tuple[List[str], Optional[float], List[str]]:
    if not isinstance(anomalies, list):
        return [], None, []

    rule_ids: List[str] = []
    max_sev: Optional[float] = None
    items: List[str] = []

    for item in anomalies:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or "").strip()
        if rule_id:
            rule_ids.append(rule_id)

        sev = _coerce_float(item.get("severity"))
        if sev is not None:
            max_sev = sev if max_sev is None else max(max_sev, sev)

        msg = (
            item.get("message")
            or item.get("symptom")
            or item.get("fault_hypotheses")
            or ""
        )
        msg = _compact_text(msg, 80)

        parts = []
        if rule_id:
            parts.append(rule_id)
        if sev is not None:
            parts.append(f"sev={sev:g}")
        if msg:
            parts.append(f"msg={msg}")
        if parts:
            items.append(" ".join(parts))

    return rule_ids, max_sev, items


def _extract_features(features: Any, limit: int = 8) -> List[Tuple[str, float]]:
    if not isinstance(features, dict):
        return []
    items: List[Tuple[str, float]] = []
    for k, v in features.items():
        fv = _coerce_float(v)
        if fv is None:
            continue
        items.append((str(k), fv))
    items.sort(key=lambda x: x[0])
    return items[:limit]


def _build_doc_text(raw: Dict[str, Any]) -> str:
    window_id = str(raw.get("window_id") or "").strip()
    ahu_id = str(raw.get("ahu_id") or "").strip()
    signature = str(raw.get("signature") or "").strip()

    time_obj = raw.get("time")
    t = time_obj if isinstance(time_obj, dict) else {}
    start = str(t.get("start") or "").strip()
    end = str(t.get("end") or "").strip()

    lines: List[str] = []
    lines.append(
        f"WINDOW: ahu={ahu_id} window_id={window_id} signature={signature} start={start} end={end}"
    )

    summary = _compact_text(raw.get("text_summary"), 300)
    if summary:
        lines.append(f"SUMMARY: {summary}")

    rule_ids, max_sev, anomaly_items = _extract_rule_ids(raw.get("anomalies"))
    if anomaly_items:
        lines.append(f"ANOMALIES: {' | '.join(anomaly_items[:5])}")
    elif rule_ids:
        lines.append(f"ANOMALIES: rule_ids={','.join(rule_ids)}")
    else:
        lines.append("ANOMALIES: none")

    feats = _extract_features(raw.get("features"), limit=8)
    if feats:
        feats_str = ", ".join(f"{k}={v:.4g}" for k, v in feats)
        lines.append(f"FEATURES: {feats_str}")

    stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
    stats_parts = []
    for key in ("sample_count", "missing_count", "late_count", "duplicate_count"):
        val = _coerce_int(stats.get(key)) if stats else None
        if val is not None:
            stats_parts.append(f"{key}={val}")
    if stats_parts:
        lines.append(f"STATS: {', '.join(stats_parts)}")

    provenance_obj = raw.get("provenance")
    provenance = provenance_obj if isinstance(provenance_obj, dict) else {}
    cfg_obj = provenance.get("config")
    cfg = cfg_obj if isinstance(cfg_obj, dict) else {}
    prov_sha = str(cfg.get("sha256") or "").strip()
    if prov_sha:
        lines.append(f"PROVENANCE: sha256={prov_sha}")

    if max_sev is not None:
        lines.append(f"MAX_SEVERITY: {max_sev:g}")

    return "\n".join(lines).strip()


def _build_metadata(raw: Dict[str, Any]) -> Dict[str, Any]:
    window_id = str(raw.get("window_id") or "").strip()
    ahu_id = str(raw.get("ahu_id") or "").strip()
    signature = str(raw.get("signature") or "").strip()

    time_obj = raw.get("time")
    t = time_obj if isinstance(time_obj, dict) else {}
    start = str(t.get("start") or "").strip()
    end = str(t.get("end") or "").strip()

    rule_ids, max_sev, _ = _extract_rule_ids(raw.get("anomalies"))

    stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
    sample_count = _coerce_int(stats.get("sample_count")) if stats else None
    missing_count = _coerce_int(stats.get("missing_count")) if stats else None
    late_count = _coerce_int(stats.get("late_count")) if stats else None
    duplicate_count = _coerce_int(stats.get("duplicate_count")) if stats else None

    provenance_obj = raw.get("provenance")
    provenance = provenance_obj if isinstance(provenance_obj, dict) else {}
    cfg_obj = provenance.get("config")
    cfg = cfg_obj if isinstance(cfg_obj, dict) else {}
    prov_sha = str(cfg.get("sha256") or "").strip()

    features = _extract_features(raw.get("features"), limit=8)
    feature_keys = [k for k, _ in features]

    metadata: Dict[str, Any] = {
        "ahu_id": ahu_id,
        "window_id": window_id,
        "signature": signature,
        "start": start,
        "end": end,
        "rule_ids": ",".join(rule_ids),
        "max_severity": max_sev,
        "sample_count": sample_count,
        "missing_count": missing_count,
        "late_count": late_count,
        "duplicate_count": duplicate_count,
        "feature_keys": ",".join(feature_keys),
        "provenance_sha256": prov_sha,
        "source": "window_history",
    }

    return {k: v for k, v in metadata.items() if v not in (None, "")}


def _validate_required(raw: Dict[str, Any]) -> bool:
    if not isinstance(raw, dict):
        return False

    window_id = raw.get("window_id")
    ahu_id = raw.get("ahu_id")
    signature = raw.get("signature")
    t = raw.get("time")

    if not isinstance(window_id, str) or not window_id.strip():
        return False
    if not isinstance(ahu_id, str) or not ahu_id.strip():
        return False
    if not isinstance(signature, str) or not signature.strip():
        return False
    if not isinstance(t, dict):
        return False
    start = t.get("start")
    end = t.get("end")
    if not isinstance(start, str) or not start.strip():
        return False
    if not isinstance(end, str) or not end.strip():
        return False
    if parse_iso8601(start) is None or parse_iso8601(end) is None:
        return False
    return True


def _create_consumer(settings: Settings, group_id: str, topics: Iterable[str]):
    try:
        from confluent_kafka import Consumer  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: confluent-kafka. Install with `pip install confluent-kafka`."
        ) from exc

    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": settings.kafka_offset_reset,
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe(list(topics))
    return consumer


def _get_collection(settings: Settings):
    try:
        import chromadb  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: chromadb. Install with `pip install chromadb`."
        ) from exc

    try:
        from static_layer.openai_embedder import OpenAIEmbeddingFunction
    except Exception:  # pragma: no cover
        from openai_embedder import OpenAIEmbeddingFunction

    client = chromadb.PersistentClient(
        path=str(Path(settings.chroma_persist_dir).resolve())
    )
    embed_fn = OpenAIEmbeddingFunction(model=settings.openai_embedding_model)
    collection = client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
        embedding_function=cast(Any, embed_fn),
    )
    return collection


def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    group_suffix = f"-{int(time.time())}" if settings.kafka_replay else ""
    group_id = f"{settings.kafka_group_prefix}{group_suffix}"

    collection = _get_collection(settings)
    consumer = _create_consumer(settings, group_id, settings.kafka_window_topics)

    counters = {"consumed": 0, "indexed": 0, "skipped": 0, "errors": 0}
    last_report = time.time()

    logger.info(
        "Window history indexer started (group_id=%s, topics=%s, collection=%s)",
        group_id,
        ",".join(settings.kafka_window_topics),
        settings.chroma_collection,
    )

    try:
        while True:
            msg = consumer.poll(0.5)
            if msg is None:
                continue
            if msg.error() is not None:
                counters["errors"] += 1
                logger.warning("Kafka error: %s", msg.error())
                continue

            counters["consumed"] += 1
            value = msg.value()
            if value is None:
                counters["skipped"] += 1
                continue

            try:
                raw = json.loads(value.decode("utf-8"))
            except Exception:
                counters["errors"] += 1
                logger.warning("Invalid JSON payload; skipping message")
                continue

            if not isinstance(raw, dict):
                counters["skipped"] += 1
                continue

            if not _validate_required(raw):
                counters["skipped"] += 1
                continue

            doc_id = _build_doc_id(raw)
            doc_text = _build_doc_text(raw)
            metadata = _build_metadata(raw)

            try:
                collection.upsert(
                    ids=[doc_id], documents=[doc_text], metadatas=[metadata]
                )
                consumer.commit(message=msg, asynchronous=False)
                counters["indexed"] += 1
            except Exception as exc:
                counters["errors"] += 1
                logger.error("Upsert failed (id=%s): %s", doc_id, exc)

            now = time.time()
            if counters["consumed"] % 100 == 0 or (now - last_report) > 60:
                logger.info(
                    "progress consumed=%d indexed=%d skipped=%d errors=%d",
                    counters["consumed"],
                    counters["indexed"],
                    counters["skipped"],
                    counters["errors"],
                )
                last_report = now
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        try:
            consumer.close()
        except Exception:
            pass
        logger.info(
            "Final counts consumed=%d indexed=%d skipped=%d errors=%d",
            counters["consumed"],
            counters["indexed"],
            counters["skipped"],
            counters["errors"],
        )


if __name__ == "__main__":
    run()

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


def _split_csv(value: str) -> List[str]:
    items = [v.strip() for v in str(value).split(",")]
    return [v for v in items if v]


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return default if raw is None else str(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return bool(default)
    s = str(raw).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap_servers: str
    kafka_window_topics: List[str]
    kafka_offset_reset: str
    kafka_group_prefix: str
    kafka_replay: bool

    chroma_persist_dir: str
    chroma_collection: str

    openai_embedding_model: str


def load_settings() -> Settings:
    bootstrap = _env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    window_topics = _split_csv(_env_str("KAFKA_WINDOW_TOPICS", "window_summaries"))

    offset_reset = _env_str("KAFKA_OFFSET_RESET", "earliest").strip().lower()
    if offset_reset not in {"earliest", "latest"}:
        offset_reset = "earliest"

    group_prefix = _env_str("KAFKA_GROUP_PREFIX", "window-history-indexer").strip()
    if not group_prefix:
        group_prefix = "window-history-indexer"

    replay = _env_bool("KAFKA_REPLAY", False)

    chroma_persist_dir = _env_str("CHROMA_PERSIST_DIR", "chroma_db").strip() or "chroma_db"
    chroma_collection = _env_str("CHROMA_COLLECTION", "window_history").strip()
    if not chroma_collection:
        chroma_collection = "window_history"

    embedding_model = _env_str(
        "OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"
    ).strip()
    if not embedding_model:
        embedding_model = "text-embedding-3-large"

    return Settings(
        kafka_bootstrap_servers=bootstrap,
        kafka_window_topics=window_topics,
        kafka_offset_reset=offset_reset,
        kafka_group_prefix=group_prefix,
        kafka_replay=replay,
        chroma_persist_dir=chroma_persist_dir,
        chroma_collection=chroma_collection,
        openai_embedding_model=embedding_model,
    )

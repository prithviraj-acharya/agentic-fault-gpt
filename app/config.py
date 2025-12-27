from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


def _split_csv(value: str) -> List[str]:
    items = [v.strip() for v in str(value).split(",")]
    return [v for v in items if v]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return int(default)
    return int(raw)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return default if raw is None else str(raw)


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap_servers: str
    kafka_telemetry_topics: List[str]
    kafka_window_topics: List[str]

    telemetry_retention_mins: int
    windows_maxlen: int
    online_threshold_secs: int
    max_points: int
    max_mins: int
    max_limit: int

    log_level: str
    cors_origins: List[str]


def load_settings() -> Settings:
    bootstrap = _env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    telemetry_topics = _split_csv(_env_str("KAFKA_TELEMETRY_TOPICS", "ahu.telemetry"))
    window_topics = _split_csv(_env_str("KAFKA_WINDOW_TOPICS", "window_summaries"))

    telemetry_retention_mins = _env_int("TELEMETRY_RETENTION_MINS", 30)
    windows_maxlen = _env_int("WINDOWS_MAXLEN", 500)
    online_threshold_secs = _env_int("ONLINE_THRESHOLD_SECS", 15)
    max_points = _env_int("MAX_POINTS", 2000)
    max_mins = _env_int("MAX_MINS", 120)
    max_limit = _env_int("MAX_LIMIT", 200)

    log_level = _env_str("LOG_LEVEL", "INFO")
    cors = _env_str("CORS_ORIGINS", "*")
    cors_origins = ["*"] if cors.strip() == "*" else _split_csv(cors)

    return Settings(
        kafka_bootstrap_servers=bootstrap,
        kafka_telemetry_topics=telemetry_topics,
        kafka_window_topics=window_topics,
        telemetry_retention_mins=int(telemetry_retention_mins),
        windows_maxlen=int(windows_maxlen),
        online_threshold_secs=int(online_threshold_secs),
        max_points=int(max_points),
        max_mins=int(max_mins),
        max_limit=int(max_limit),
        log_level=str(log_level),
        cors_origins=cors_origins,
    )

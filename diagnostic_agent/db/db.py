from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def get_db_path() -> str:
    env_path = os.getenv("TICKETS_DB_PATH")
    if env_path:
        return env_path
    return str(Path("diagnostic_agent") / "db" / "tickets.db")


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    _configure_connection(conn)
    return conn


def init_db(db_path: str | None = None) -> None:
    path = db_path or get_db_path()
    schema_path = Path(__file__).with_name("schema.sql")
    with schema_path.open("r", encoding="utf-8") as handle:
        schema_sql = handle.read()
    with connect(path) as conn:
        conn.executescript(schema_sql)

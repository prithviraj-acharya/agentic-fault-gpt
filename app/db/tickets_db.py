from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

_ALLOWED_JOURNAL_MODES = {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"}
_JOURNAL_MODE_LOCK = threading.Lock()
_JOURNAL_MODE_SET = False


def get_db_path() -> str:
    env_path = os.getenv("TICKETS_DB_PATH")
    if env_path:
        return str(env_path)
    return str(Path("/data") / "tickets.db")


def get_journal_mode() -> str:
    mode = str(os.getenv("TICKETS_SQLITE_JOURNAL_MODE", "WAL")).upper().strip()
    return mode if mode in _ALLOWED_JOURNAL_MODES else "WAL"


def _set_journal_mode_once(conn: sqlite3.Connection) -> None:
    global _JOURNAL_MODE_SET
    if _JOURNAL_MODE_SET:
        return
    with _JOURNAL_MODE_LOCK:
        if _JOURNAL_MODE_SET:
            return
        last_exc: Exception | None = None
        for _ in range(5):
            try:
                conn.execute(f"PRAGMA journal_mode={get_journal_mode()};")
                _JOURNAL_MODE_SET = True
                return
            except sqlite3.OperationalError as exc:
                last_exc = exc
                if "locked" not in str(exc).lower():
                    raise
                time.sleep(0.1)
        if last_exc is not None:
            raise last_exc


def _configure_connection(conn: sqlite3.Connection) -> None:
    # NOTE: WAL can be problematic on some Docker Desktop bind mounts (especially on Windows).
    # Make it configurable so deployments can switch to DELETE/TRUNCATE safely.
    conn.execute("PRAGMA busy_timeout=5000;")
    _set_journal_mode_once(conn)
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'"
    ).fetchone()
    if row is not None:
        # Lightweight online migrations for existing DBs.
        try:
            cols = conn.execute("PRAGMA table_info(tickets)").fetchall()
            existing = {str(c[1]) for c in cols if c and len(c) > 1}

            if "occurrence_count" not in existing:
                conn.execute(
                    "ALTER TABLE tickets ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 0"
                )
            if "last_window_id" not in existing:
                conn.execute("ALTER TABLE tickets ADD COLUMN last_window_id TEXT")
        except sqlite3.OperationalError:
            # If migrations fail (e.g., locked), let the caller retry via busy_timeout.
            pass
        return
    schema_path = Path(__file__).with_name("schema.sql")
    with schema_path.open("r", encoding="utf-8") as handle:
        schema_sql = handle.read()
    conn.executescript(schema_sql)


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    def _open() -> sqlite3.Connection:
        conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        _configure_connection(conn)
        _ensure_schema(conn)
        return conn

    try:
        return _open()
    except sqlite3.DatabaseError:
        # If the main DB is healthy but the WAL/SHM got out of sync (e.g., abrupt kill),
        # deleting them can allow SQLite to reopen cleanly.
        wal = f"{path}-wal"
        shm = f"{path}-shm"
        for sidecar in (wal, shm):
            try:
                if os.path.exists(sidecar):
                    os.remove(sidecar)
            except OSError:
                pass
        return _open()

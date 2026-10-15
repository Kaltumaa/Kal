"""SQLite connection helpers. The database is a single local file (data sovereignty anchor)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from crop_pilot import config


class DatabaseUnavailable(RuntimeError):
    """Raised when the local database is missing or corrupt."""


def db_path() -> Path:
    return config.DB_PATH


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = path or db_path()
    if not path.exists():
        raise DatabaseUnavailable(f"database file not found: {path.name}")
    try:
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.DatabaseError as exc:
        raise DatabaseUnavailable(str(exc)) from exc
    try:
        yield conn
        conn.commit()
    except sqlite3.DatabaseError as exc:
        conn.rollback()
        if isinstance(exc, sqlite3.IntegrityError):
            raise
        raise DatabaseUnavailable(str(exc)) from exc
    finally:
        conn.close()


def health_check(path: Path | None = None) -> dict:
    """Integrity check used by /health and the Task 8 recovery loop."""
    try:
        with connect(path) as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"plots", "pest_alerts", "weather_cache", "tool_calls", "pending_advisories", "dispatch_outbox"}
        missing = sorted(required - tables)
        ok = result == "ok" and not missing
        return {"ok": ok, "integrity": result, "missing_tables": missing}
    except (DatabaseUnavailable, sqlite3.DatabaseError) as exc:
        return {"ok": False, "integrity": "unreadable", "error": str(exc)[:200], "missing_tables": []}

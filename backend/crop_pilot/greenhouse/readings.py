"""Greenhouse readings: from a sensor (any device that can POST JSON) or typed by the farmer.

Readings only produce advice for the farmer. They are not advisory signals and the agent does not read them.
"""
from __future__ import annotations

import re

from crop_pilot.core import greenhouse, telemetry
from crop_pilot.database.db import connect

ID_RE = re.compile(r"^[A-Za-z0-9_\-]{2,40}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS greenhouse_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    greenhouse_id TEXT NOT NULL, source TEXT NOT NULL CHECK (source IN ('sensor','manual')),
    device_id TEXT, temp_c REAL NOT NULL CHECK (temp_c BETWEEN -5 AND 60),
    rh_pct REAL NOT NULL CHECK (rh_pct BETWEEN 0 AND 100), vpd_kpa REAL NOT NULL, status TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


def record(greenhouse_id: str, temp_c: float, rh_pct: float, source: str, device_id: str | None = None,
           crop: str | None = None) -> dict:
    if not ID_RE.match(greenhouse_id or ""):
        raise ValueError("greenhouse_id must be 2–40 letters, digits, '-' or '_'.")
    if device_id is not None and not ID_RE.match(device_id):
        raise ValueError("device_id must be 2–40 letters, digits, '-' or '_'.")
    result = greenhouse.assess(temp_c, rh_pct, crop)
    with connect() as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("INSERT INTO greenhouse_readings (greenhouse_id, source, device_id, temp_c, rh_pct, vpd_kpa,"
                           " status, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                           (greenhouse_id, source, device_id, temp_c, rh_pct, result["vpd_kpa"], result["status"],
                            telemetry.now_iso()))
    return {"reading_id": cur.lastrowid, "greenhouse_id": greenhouse_id, "source": source, **result}


def history(greenhouse_id: str | None = None, limit: int = 200) -> list[dict]:
    with connect() as conn:
        conn.executescript(SCHEMA)
        q = ("SELECT * FROM greenhouse_readings" + (" WHERE greenhouse_id = ?" if greenhouse_id else "")
             + " ORDER BY id DESC LIMIT ?")
        return [dict(r) for r in conn.execute(q, (greenhouse_id, limit) if greenhouse_id else (limit,))]

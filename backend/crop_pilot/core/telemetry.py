"""Append-only audit log for every tool call, model call and human decision."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from crop_pilot.database.db import DatabaseUnavailable, connect

log = logging.getLogger("crop_pilot.telemetry")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def estimate_tokens(*payloads: object) -> int:
    """~4 characters per token. Used when the model does not report its own count."""
    return sum(len(p if isinstance(p, str) else json.dumps(p, default=str)) for p in payloads) // 4


def record(run_id: str, server: str, tool: str, inputs: object, output: object, *,
           latency_ms: float, status: str = "ok", actor: str = "agent",
           token_count: int | None = None, approved_by: str | None = None) -> int | None:
    ts = now_iso()
    inputs_json = json.dumps(inputs, default=str, ensure_ascii=False)
    output_json = json.dumps(output, default=str, ensure_ascii=False)[:20_000]
    call_hash = hashlib.sha256(f"{run_id}|{server}|{tool}|{inputs_json}|{ts}".encode()).hexdigest()[:16]
    tokens = token_count if token_count is not None else estimate_tokens(inputs_json, output_json)
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO tool_calls (run_id, call_hash, ts, server, tool, actor, inputs_json, output_json,"
                " status, token_estimate, latency_ms, approved_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, call_hash, ts, server, tool, actor, inputs_json, output_json, status, tokens,
                 round(latency_ms, 1), approved_by))
            return cur.lastrowid
    except DatabaseUnavailable as exc:   # never let logging crash the run
        log.warning("telemetry write failed (%s): %s %s", exc, server, tool)
        return None

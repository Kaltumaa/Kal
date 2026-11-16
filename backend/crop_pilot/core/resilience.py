"""Retry + fallback helpers and the self-check recovery log.

Every failure the agent recovers from is written to `recovery_log` (what failed, what was done about it, which
degraded source was used instead) and mirrored to the `tool_calls` audit trail, so an officer can see that an
answer rests on a fallback.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from crop_pilot.core import telemetry
from crop_pilot.database.db import DatabaseUnavailable, connect


def log_recovery(run_id: str, component: str, failure: str, recovery_action: str,
                 degraded_source: str | None = None, attempts: int = 1) -> dict:
    event = {"component": component, "failure": failure[:300], "recovery_action": recovery_action,
             "degraded_source": degraded_source, "attempts": attempts, "ts": telemetry.now_iso()}
    try:
        with connect() as conn:
            conn.execute("INSERT INTO recovery_log (run_id, ts, component, failure, recovery_action, degraded_source, "
                         "attempts) VALUES (?,?,?,?,?,?,?)",
                         (run_id, event["ts"], component, event["failure"], recovery_action, degraded_source, attempts))
    except (DatabaseUnavailable, Exception):  # noqa: BLE001 - the log must never break the run it describes
        pass
    telemetry.record(run_id, "self_check", f"recovery:{component}", {"failure": event["failure"]},
                     {"recovery_action": recovery_action, "degraded_source": degraded_source, "attempts": attempts},
                     latency_ms=0, status="recovered" if recovery_action != "gave_up" else "error")
    return event


def recovery_events(run_id: str) -> list[dict]:
    try:
        with connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM recovery_log WHERE run_id = ? ORDER BY id", (run_id,))]
    except DatabaseUnavailable:
        return []


def with_retry(fn: Callable[[], Any], *, attempts: int, backoff_s: float = 0.4,
               retry_on: tuple[type[BaseException], ...] = (Exception,)) -> tuple[Any, int, list[str]]:
    """Call `fn` up to `attempts` times. Returns (result, attempts_used, errors). Re-raises the last error."""
    errors: list[str] = []
    for i in range(1, attempts + 1):
        try:
            return fn(), i, errors
        except retry_on as exc:
            errors.append(f"{type(exc).__name__}: {exc}"[:200])
            if i == attempts:
                raise
            time.sleep(backoff_s * i)
    raise RuntimeError("unreachable")

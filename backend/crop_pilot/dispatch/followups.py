"""Officer side of the desk's follow-up list: read it and close items (named officer required)."""
from __future__ import annotations

from crop_pilot.core import telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError, validate_signature
from crop_pilot.mcp_server.server import FOLLOWUP_SCHEMA


def list_followups(status: str | None = "OPEN") -> list[dict]:
    with connect() as conn:
        conn.executescript(FOLLOWUP_SCHEMA)
        q = "SELECT * FROM followups" + (" WHERE status = ?" if status else "") + " ORDER BY due_date, id"
        return [dict(r) for r in conn.execute(q, (status,) if status else ())]


def close(followup_id: int, officer_name: str) -> dict:
    officer = validate_signature(officer_name)
    with connect() as conn:
        conn.executescript(FOLLOWUP_SCHEMA)
        row = conn.execute("SELECT * FROM followups WHERE id=?", (followup_id,)).fetchone()
        if row is None or row["status"] != "OPEN":
            raise ApprovalError("Follow-up not found or already done.")
        conn.execute("UPDATE followups SET status='DONE', closed_by=?, closed_at=? WHERE id=?",
                     (officer, telemetry.now_iso(), followup_id))
    telemetry.record(row["run_id"], "officer", "close_followup", {"followup_id": followup_id}, {"status": "DONE"},
                     latency_ms=0, actor=officer)
    return {"followup_id": followup_id, "status": "DONE", "officer": officer}

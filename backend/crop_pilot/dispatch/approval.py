"""Named-officer approval and (simulated) outbound dispatch.

This module is the ONLY code that can move an advisory to APPROVED or write to dispatch_outbox.
It is called by the REST API when a human submits the Control Desk form. The agent package never
imports it (enforced by tests/test_boundaries.py) and no MCP tool wraps it.

Outbound is SIMULATED: a row in dispatch_outbox stands in for the SMS/USSD gateway, which a real
deployment would attach here, behind the officer signature.
"""
from __future__ import annotations

import json
import re
import time

from crop_pilot.core import agronomy, sanitizer, telemetry
from crop_pilot.database.db import connect

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\-.]+(?: [A-Za-z][A-Za-z'\-.]+)+$")


class ApprovalError(ValueError):
    pass


def validate_signature(officer_name: str) -> str:
    name = sanitizer.normalise_text(officer_name)
    if not (5 <= len(name) <= 80) or not NAME_RE.match(name):
        raise ApprovalError("Type your full name (first and last name, letters only) to sign.")
    if sanitizer.detect_injection(name):
        raise ApprovalError("Signature rejected.")
    return name


def _load(conn, advisory_id: int):
    row = conn.execute("SELECT * FROM pending_advisories WHERE id = ?", (advisory_id,)).fetchone()
    if row is None:
        raise ApprovalError(f"Advisory {advisory_id} not found.")
    return row


def forecast_change(conn, row) -> str | None:
    """Why the rainfall forecast behind a draft is out of date, or None if it still holds."""
    ev = json.loads(row["evidence_json"] or "{}")
    rain, zone = ev.get("rain") or {}, (ev.get("plot") or {}).get("zone_id")
    if not zone or not rain.get("forecast_issued_at"):
        return None
    current = conn.execute("SELECT * FROM weather_cache WHERE zone_id=?", (zone,)).fetchone()
    if current is None:
        return "the ward's forecast is no longer available"
    now = agronomy.rainfall_outlook(dict(current))
    reasons = []
    if str(current["issued_at"]) > str(rain["forecast_issued_at"]):
        reasons.append(f"a newer forecast was issued on {current['issued_at']}")
    if now["spray_band"] != rain.get("spray_band"):
        reasons.append(f"spraying went from {rain.get('spray_band')} to {now['spray_band']}")
    if now["washout_risk"] != rain.get("washout_risk"):
        reasons.append("washout risk changed")
    if abs(now["rain_7d_mm"] - float(rain.get("rain_7d_mm") or 0)) >= 10:
        reasons.append(f"7-day rain went from {rain.get('rain_7d_mm')} to {now['rain_7d_mm']} mm")
    return "; ".join(reasons) or None


def approve(advisory_id: int, officer_name: str, final_message: str | None = None) -> dict:
    started = time.perf_counter()
    officer = validate_signature(officer_name)
    with connect() as conn:
        row = _load(conn, advisory_id)
        if row["status"] != "PENDING_REVIEW":
            raise ApprovalError(f"Advisory is {row['status']}; only PENDING_REVIEW drafts can be approved. "
                                "Security-locked or incomplete drafts must be rejected and re-run.")
        changed = forecast_change(conn, row)
        if changed:
            raise ApprovalError(f"The rainfall forecast changed since this draft ({changed}). Re-run the agent for "
                                "this household and sign the new draft instead.")
        message = row["farmer_message"]
        if final_message is not None and final_message.strip():
            message, hits = sanitizer.scrub_free_text(final_message, 320)
            if hits:
                raise ApprovalError("Edited message contains instruction-like text; not sent.")
        ts = telemetry.now_iso()
        conn.execute("UPDATE pending_advisories SET status='APPROVED', officer_signature=?, reviewed_at=?,"
                     " transmitted_at=?, farmer_message=? WHERE id=?", (officer, ts, ts, message, advisory_id))
        cur = conn.execute("INSERT INTO dispatch_outbox (advisory_id, household_id, message, officer_signature,"
                           " queued_at) VALUES (?,?,?,?,?)", (advisory_id, row["household_id"], message, officer, ts))
        conn.execute("UPDATE tool_calls SET approved_by=? WHERE run_id=?", (officer, row["run_id"]))
        outbox_id = cur.lastrowid
    telemetry.record(row["run_id"], "officer", "approve_and_dispatch", {"advisory_id": advisory_id},
                     {"outbox_id": outbox_id, "channel": "SMS_SIMULATED", "message": message},
                     latency_ms=(time.perf_counter() - started) * 1000, actor=officer, approved_by=officer)
    return {"advisory_id": advisory_id, "run_id": row["run_id"], "status": "APPROVED", "officer": officer,
            "outbox_id": outbox_id, "message": message}


def reject(advisory_id: int, officer_name: str, reason: str = "") -> dict:
    started = time.perf_counter()
    officer = validate_signature(officer_name)
    note, _ = sanitizer.scrub_free_text(reason, 300)
    with connect() as conn:
        row = _load(conn, advisory_id)
        if row["status"] in ("APPROVED", "REJECTED"):
            raise ApprovalError(f"Advisory already {row['status']}.")
        conn.execute("UPDATE pending_advisories SET status='REJECTED', officer_signature=?, reviewed_at=?,"
                     " review_note=? WHERE id=?", (officer, telemetry.now_iso(), note, advisory_id))
    telemetry.record(row["run_id"], "officer", "reject", {"advisory_id": advisory_id, "reason": note},
                     {"status": "REJECTED"}, latency_ms=(time.perf_counter() - started) * 1000, actor=officer)
    return {"advisory_id": advisory_id, "run_id": row["run_id"], "status": "REJECTED", "officer": officer}


def list_advisories(status: str | None = None) -> list[dict]:
    with connect() as conn:
        q = "SELECT * FROM pending_advisories" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC"
        rows = conn.execute(q, (status,) if status else ()).fetchall()
        changes = {r["id"]: forecast_change(conn, r) for r in rows if r["status"] == "PENDING_REVIEW"}
    out = []
    for r in rows:
        d = dict(r)
        d["forecast_changed"] = changes.get(r["id"])
        for key in ("evidence_json", "sources_json", "flags_json"):
            d[key.replace("_json", "")] = json.loads(d.pop(key) or "null")
        out.append(d)
    return out


def outbox() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM dispatch_outbox ORDER BY id DESC")]

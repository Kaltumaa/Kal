"""Human-in-the-loop escalation queue: the agent was not sure, so it asks the sub-county extension officer.

Shared by the MCP write tool `escalate_to_officer` and the institution dashboard. It never contacts anyone: it adds
a row to `escalations`, assigned to the officer with the fewest open escalations in that farm's sub-county.
"""
from __future__ import annotations

import json

from crop_pilot import config
from crop_pilot.core import sanitizer
from crop_pilot.core.telemetry import now_iso
from crop_pilot.database.db import connect


def officer_covers(officer: dict, zone_id: str | None) -> bool:
    """Does this officer serve this ward? Their own ward list if they have one, else their whole sub-county."""
    zone = sanitizer.normalise_zone(zone_id)
    if not zone:
        return False
    wards = {w for w in (officer.get("wards") or "").split(",") if w}
    if wards:
        return zone in wards
    county, sub_county = config.ward_location(zone)
    return (sub_county or "").lower() == (officer.get("sub_county") or "").lower() and \
        (county or "").lower() == (officer.get("county") or "").lower()


def pick_officer(conn, zone_id: str | None) -> dict | None:
    officers = [dict(r) for r in conn.execute(
        "SELECT u.*, (SELECT COUNT(*) FROM escalations e WHERE e.assigned_officer_id = u.id AND e.status='OPEN') "
        "AS open_load FROM users u WHERE u.role = 'extension_officer' AND u.active = 1 ORDER BY open_load, u.id")]
    return next((o for o in officers if officer_covers(o, zone_id)), None)


def escalate(run_id: str, household_id: str, reasons: list[str], question: str,
             advisory_id: int | None = None) -> dict:
    hid = sanitizer.normalise_text(household_id).upper()[:32]
    clean_reasons = [sanitizer.scrub_free_text(r, 200)[0] for r in reasons if r][:12]
    if not clean_reasons:
        return {"ok": False, "error": "an escalation needs at least one reason"}
    text, _ = sanitizer.scrub_free_text(question, 600)
    with connect() as conn:
        existing = conn.execute("SELECT * FROM escalations WHERE run_id = ?", (run_id,)).fetchone()
        if existing:
            return {"ok": True, "escalation_id": existing["id"], "assigned_officer_id": existing["assigned_officer_id"],
                    "idempotent_replay": True}
        plot = conn.execute("SELECT zone_id FROM plots WHERE upper(household_id) = ?", (hid,)).fetchone()
        zone = sanitizer.normalise_zone(plot["zone_id"]) if plot else None
        county, sub_county = config.ward_location(zone)
        officer = pick_officer(conn, zone)
        cur = conn.execute("INSERT INTO escalations (run_id, household_id, advisory_id, county, sub_county, "
                           "assigned_officer_id, reasons_json, question, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                           (run_id, hid, advisory_id, county, sub_county, officer and officer["id"],
                            json.dumps(clean_reasons), text, now_iso()))
    return {"ok": True, "escalation_id": cur.lastrowid, "sub_county": sub_county,
            "assigned_officer": officer and {"id": officer["id"], "full_name": officer["full_name"]},
            "note": "Queued for the sub-county extension officer. Nothing was sent to the farmer."}


def officer_corrections(household_id: str, limit: int = 3) -> list[dict]:
    """The most recent drafts an officer REJECTED for this farm: what the agent advised, when, and why it was wrong.
    The agent reads these before advising again so it can admit a past mistake instead of repeating it."""
    hid = sanitizer.normalise_text(household_id).upper()[:32]
    with connect() as conn:
        rows = conn.execute("SELECT id, verdict, rule_verdict, reviewed_at, officer_signature, review_note "
                            "FROM pending_advisories WHERE household_id = ? AND status = 'REJECTED' "
                            "ORDER BY reviewed_at DESC LIMIT ?", (hid, int(limit))).fetchall()
    return [{"advisory_id": r["id"], "verdict": r["verdict"] or r["rule_verdict"],
             "reviewed_at": (r["reviewed_at"] or "")[:10], "officer": r["officer_signature"],
             "reason": sanitizer.scrub_free_text(r["review_note"] or "", 200)[0]} for r in rows]

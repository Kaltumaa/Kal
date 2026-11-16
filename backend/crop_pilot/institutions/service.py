"""Institution management: onboard officers (paid seats), designate Lead Farmers, officer analytics, bulk alerts,
and the officer's side of the human-in-the-loop escalation queue.

Gates: onboarding an officer and sending a bulk alert both need an ACTIVE paid subscription that covers the
sub-county (crop_pilot.payments.subscriptions.require_active).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from crop_pilot import config
from crop_pilot.accounts import service as accounts
from crop_pilot.core import escalation, sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch import sms
from crop_pilot.dispatch.approval import ApprovalError
from crop_pilot.payments import subscriptions

PENDING_STATUSES = ("PENDING_REVIEW", "NEEDS_DATA")
MAX_BULK_MESSAGE = 320


def _same_county(institution_id: int, county: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT county FROM institutions WHERE id = ?", (int(institution_id),)).fetchone()
    if row is None:
        raise ApprovalError("Institution not found.")
    if row["county"].lower() != (county or "").strip().lower():
        raise ApprovalError(f"This institution works in {row['county']} County only.")


def onboard_officer(institution_user: dict, email: str, password: str, full_name: str, county: str, sub_county: str,
                    wards: list[str] | None = None, phone: str | None = None) -> dict:
    inst = institution_user["institution_id"]
    _same_county(inst, county)
    subscriptions.require_active(inst)
    officer = accounts.create_officer(inst, email, password, full_name, county, sub_county, wards, phone)
    telemetry.record(f"inst-{inst}", "institution", "onboard_officer", {"sub_county": sub_county, "wards": wards},
                     {"officer_id": officer["id"]}, latency_ms=0, actor=institution_user["full_name"])
    return officer


def _officers(conn, institution_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM users WHERE role = 'extension_officer' AND institution_id = ? "
                                          "AND approval_status = 'approved' ORDER BY sub_county, full_name",
                                          (int(institution_id),))]


def pending_officers(institution_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users WHERE role = 'extension_officer' AND institution_id = ? "
                            "AND approval_status = 'pending' ORDER BY created_at", (int(institution_id),)).fetchall()
    return [accounts.public(r) for r in rows]


def decide_officer(institution_user: dict, officer_id: int, approve: bool) -> dict:
    """Approve (uses a paid seat; needs an active subscription) or reject an officer's self sign-up."""
    inst = institution_user["institution_id"]
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND role = 'extension_officer' AND institution_id = ?",
                           (int(officer_id), inst)).fetchone()
    if row is None:
        raise ApprovalError("Officer sign-up not found.")
    if row["approval_status"] != "pending":
        raise ApprovalError(f"This sign-up was already {row['approval_status']}.")
    if approve:
        subscriptions.require_active(inst)
    with connect() as conn:
        conn.execute("UPDATE users SET approval_status = ?, active = ?, approved_by = ? WHERE id = ?",
                     ("approved" if approve else "rejected", 1 if approve else 0, institution_user["full_name"],
                      row["id"]))
        out = accounts.public(conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone())
    telemetry.record(f"inst-{inst}", "institution", "approve_officer" if approve else "reject_officer",
                     {"officer_id": row["id"]}, {"status": out["approval_status"]}, latency_ms=0,
                     actor=institution_user["full_name"])
    return out


def _minutes(start: str | None, end: str | None) -> float | None:
    try:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    if (a.tzinfo is None) != (b.tzinfo is None):
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return max(0.0, (b - a).total_seconds() / 60)


def officer_analytics(institution_id: int) -> dict:
    """Per officer: caseload, pending approvals, response time, resolved vs escalated; and per sub-county workload."""
    with connect() as conn:
        officers = _officers(conn, institution_id)
        plots = [dict(r) for r in conn.execute("SELECT household_id, zone_id, active_crop FROM plots")]
        advisories = [dict(r) for r in conn.execute(
            "SELECT id, household_id, status, created_at, reviewed_at, officer_signature FROM pending_advisories")]
        escalations = [dict(r) for r in conn.execute("SELECT * FROM escalations")]
    by_household = defaultdict(list)
    for a in advisories:
        by_household[a["household_id"]].append(a)

    rows = []
    for o in officers:
        caseload = [p for p in plots if escalation.officer_covers(o, p["zone_id"])]
        hids = {p["household_id"] for p in caseload}
        pending_adv = [a for h in hids for a in by_household[h] if a["status"] in PENDING_STATUSES]
        mine = [e for e in escalations if e["assigned_officer_id"] == o["id"]]
        open_esc = [e for e in mine if e["status"] == "OPEN"]
        name = o["full_name"]
        reviewed = [a for a in advisories if a["officer_signature"] == name and a["status"] in ("APPROVED", "REJECTED")]
        resolved_esc = [e for e in escalations if e["status"] == "RESOLVED" and e["resolved_by"] == name]
        times = [m for m in ([_minutes(a["created_at"], a["reviewed_at"]) for a in reviewed]
                             + [_minutes(e["created_at"], e["resolved_at"]) for e in resolved_esc]) if m is not None]
        rows.append({
            "officer_id": o["id"], "full_name": name, "county": o["county"], "sub_county": o["sub_county"],
            "wards": [w for w in (o["wards"] or "").split(",") if w] or "all wards in sub-county",
            "active": bool(o["active"]),
            "active_caseload": {"households": len(hids),
                                "with_active_crop": sum(1 for p in caseload if (p["active_crop"] or "").strip())},
            "pending_approvals": {"advisories": len(pending_adv), "escalations": len(open_esc),
                                  "total": len(pending_adv) + len(open_esc)},
            "avg_response_minutes": round(sum(times) / len(times), 1) if times else None,
            "cases": {"resolved": len(reviewed) + len(resolved_esc), "advisories_signed": len(reviewed),
                      "escalations_resolved": len(resolved_esc), "escalated_to_officer": len(mine),
                      "escalations_open": len(open_esc)},
        })

    workload: dict[str, dict] = {}
    for r in rows:
        w = workload.setdefault(r["sub_county"], {"sub_county": r["sub_county"], "county": r["county"], "officers": 0,
                                                  "households": 0, "pending_approvals": 0, "open_escalations": 0})
        w["officers"] += 1
        w["pending_approvals"] += r["pending_approvals"]["total"]
        w["open_escalations"] += r["cases"]["escalations_open"]
    for sc, w in workload.items():
        sc_households = {p["household_id"] for p in plots if config.ward_location(sanitizer.normalise_zone(p["zone_id"]))[1] == sc}
        w["households"] = len(sc_households)
        w["households_per_officer"] = round(w["households"] / w["officers"], 1) if w["officers"] else None
    unassigned = [e for e in escalations if e["assigned_officer_id"] is None and e["status"] == "OPEN"]
    return {"institution_id": int(institution_id), "officers": rows,
            "sub_county_workload": sorted(workload.values(), key=lambda w: w["sub_county"] or ""),
            "unassigned_open_escalations": len(unassigned),
            "pending_officer_signups": len(pending_officers(institution_id)),
            "subscription": subscriptions.entitlement(institution_id), "generated_at": telemetry.now_iso()}


def farmers(institution_id: int) -> dict:
    """Farmer accounts in the institution's county: the ones it pays for, and the ones still waiting for a seat."""
    with connect() as conn:
        county = conn.execute("SELECT county FROM institutions WHERE id = ?", (int(institution_id),)).fetchone()
        rows = [dict(r) for r in conn.execute(
            "SELECT u.*, i.name AS sponsor_name FROM users u LEFT JOIN institutions i ON i.id = u.sponsor_institution_id "
            "WHERE u.role = 'farmer' AND (u.sponsor_institution_id = ? OR (u.sponsor_institution_id IS NULL "
            "AND lower(COALESCE(u.county, '')) = lower(?))) ORDER BY u.created_at", (int(institution_id),
                                                                                  county["county"] if county else ""))]
    out = {"covered": [], "waiting": []}
    for r in rows:
        item = accounts.public(r) | {"sponsor": r["sponsor_name"]}
        out["covered" if r["sponsor_institution_id"] == int(institution_id) else "waiting"].append(item)
    out["entitlement"] = subscriptions.entitlement(institution_id)
    return out


def designate_lead_farmer(institution_user: dict, household_id: str) -> dict:
    out = accounts.designate_lead_farmer(institution_user["institution_id"], household_id)
    telemetry.record(f"inst-{institution_user['institution_id']}", "institution", "designate_lead_farmer",
                     {"household_id": household_id}, {"cells": out["cells"]}, latency_ms=0,
                     actor=institution_user["full_name"])
    return out


def bulk_alert(user: dict, sub_county: str, message: str, wards: list[str] | None = None) -> dict:
    """A named institution user or officer sends one alert to every farm with a phone in a sub-county (by SMS).
    Human-written and signed by the account holder; the agent has no route here."""
    inst = user["institution_id"]
    subscriptions.require_active(inst, sub_county=sub_county)
    if user["role"] == "extension_officer" and (user["sub_county"] or "").lower() != sub_county.strip().lower():
        raise ApprovalError("Officers can only alert farms in their own sub-county.")
    text, hits = sanitizer.scrub_free_text(message, MAX_BULK_MESSAGE)
    if hits:
        raise ApprovalError("The alert contains instruction-like text.")
    if len(text) < 10:
        raise ApprovalError("Write the alert (at least 10 characters).")
    target_wards = {sanitizer.normalise_zone(w) for w in wards or [] if sanitizer.normalise_zone(w)}
    with connect() as conn:
        farms = [dict(r) for r in conn.execute("SELECT household_id, zone_id, phone FROM plots")]
    targets = [f for f in farms
               if (config.ward_location(sanitizer.normalise_zone(f["zone_id"]))[1] or "").lower()
               == sub_county.strip().lower()
               and (not target_wards or sanitizer.normalise_zone(f["zone_id"]) in target_wards) and f["phone"]]
    sender = user["full_name"]
    ids = [sms.queue_out(f["household_id"], f"{text} - {sender}", "bulk_alert", None, sender) for f in targets]
    telemetry.record(f"bulk-{inst}-{telemetry.now_iso()}", "institution", "bulk_alert",
                     {"sub_county": sub_county, "wards": sorted(target_wards), "message": text},
                     {"sms_ids": ids, "households": [f["household_id"] for f in targets]}, latency_ms=0,
                     actor=sender, approved_by=sender)
    return {"queued": len(ids), "sms_ids": ids, "sub_county": sub_county, "sent_by": sender, "channel": "SMS"}


# --- the officer's escalation queue ---------------------------------------------------------------------------------
def _visible(user: dict, e: dict) -> bool:
    if user["role"] == "extension_officer":
        return e["assigned_officer_id"] == user["id"] or (
            e["assigned_officer_id"] is None and (e["sub_county"] or "").lower() == (user["sub_county"] or "").lower())
    with connect() as conn:   # institution: escalations assigned to its officers or open in sub-counties it serves
        mine = {r[0] for r in conn.execute("SELECT id FROM users WHERE institution_id = ?", (user["institution_id"],))}
    return e["assigned_officer_id"] in mine


def list_escalations(user: dict, status: str | None = "OPEN") -> list[dict]:
    with connect() as conn:
        q = "SELECT * FROM escalations" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC"
        rows = [dict(r) for r in conn.execute(q, (status,) if status else ())]
    out = []
    for r in rows:
        if _visible(user, r):
            r["reasons"] = json.loads(r.pop("reasons_json") or "[]")
            out.append(r)
    return out


def resolve_escalation(officer: dict, escalation_id: int, diagnosis: str) -> dict:
    """The officer's manual diagnosis closes the escalation. Advice to the farmer still goes through approval."""
    text, hits = sanitizer.scrub_free_text(diagnosis, 1200)
    if hits:
        raise ApprovalError("The diagnosis contains instruction-like text.")
    if len(text) < 5:
        raise ApprovalError("Write your diagnosis.")
    with connect() as conn:
        e = conn.execute("SELECT * FROM escalations WHERE id = ?", (int(escalation_id),)).fetchone()
        if e is None or not _visible(officer, dict(e)):
            raise ApprovalError("Escalation not found.")
        if e["status"] != "OPEN":
            raise ApprovalError("Escalation already resolved.")
        conn.execute("UPDATE escalations SET status='RESOLVED', resolved_by=?, resolved_at=?, diagnosis=?, "
                     "assigned_officer_id=COALESCE(assigned_officer_id, ?) WHERE id=?",
                     (officer["full_name"], telemetry.now_iso(), text, officer["id"], e["id"]))
    telemetry.record(e["run_id"], "officer", "resolve_escalation", {"escalation_id": e["id"], "diagnosis": text},
                     {"status": "RESOLVED"}, latency_ms=0, actor=officer["full_name"], approved_by=officer["full_name"])
    return {"escalation_id": e["id"], "status": "RESOLVED", "resolved_by": officer["full_name"], "diagnosis": text}

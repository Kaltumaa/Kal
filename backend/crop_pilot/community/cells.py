"""Nyumba Kumi cells: up to ten neighbouring households, one lead farmer with a smartphone.

The lead farmer takes photos for neighbours who have no smartphone or data. The photo goes to the officer exactly
like the neighbour's own would (filed under the neighbour's farm, marked as sent by the lead). The lead sees only
what any farmer sees: waiting / the officer's finding. Never the AI's guess. Results reach the neighbour by SMS and,
if the officer chooses, by a voice call.
"""
from __future__ import annotations

import re

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch import voice_calls
from crop_pilot.dispatch.approval import ApprovalError, validate_signature
from crop_pilot.fieldscan import service as fieldscan

PHONE_TYPES = ("smartphone", "feature")


def _hid(value: str) -> str:
    return sanitizer.normalise_text(value).upper()[:32]


def list_cells() -> list[dict]:
    with connect() as conn:
        cells = [dict(r) for r in conn.execute("SELECT * FROM nyumba_cells ORDER BY cell_id")]
        for c in cells:
            c["members"] = [dict(r) for r in conn.execute(
                "SELECT household_id, farmer_name, phone_type, active_crop FROM plots WHERE cell_id = ? "
                "ORDER BY household_id = ? DESC, household_id", (c["cell_id"], c["lead_household_id"]))]
    return cells


def cell_for(household_id: str) -> dict | None:
    hid = _hid(household_id)
    return next((c for c in list_cells() if any(m["household_id"] == hid for m in c["members"])), None)


def lead_view(household_id: str) -> dict:
    """What the lead farmer's phone shows: their neighbours, each one's photos (officer findings only), and calls."""
    hid = _hid(household_id)
    cell = cell_for(hid)
    if cell is None:
        return {"role": "none", "cell": None}
    if cell["lead_household_id"] != hid:
        lead = next(m for m in cell["members"] if m["household_id"] == cell["lead_household_id"]) \
            if any(m["household_id"] == cell["lead_household_id"] for m in cell["members"]) else {}
        return {"role": "member", "cell": {k: cell[k] for k in ("cell_id", "name", "zone_id")},
                "lead": {"household_id": cell["lead_household_id"], "farmer_name": lead.get("farmer_name")}}
    calls = voice_calls.list_calls(cell_id=cell["cell_id"])
    neighbours = []
    for m in cell["members"]:
        if m["household_id"] == hid:
            continue
        photos = [p for p in fieldscan.farmer_view(m["household_id"]) if p.get("submitted_by") == hid]
        mine = [c for c in calls if c["household_id"] == m["household_id"]]
        neighbours.append(m | {"photos": photos[:5], "waiting": sum(p["waiting"] for p in photos),
                               "visit_requested": any(c["status"] == "VISIT_REQUESTED" for c in mine),
                               "last_call": ({k: mine[0][k] for k in ("status", "updated_at", "kind")} if mine else None)})
    return {"role": "lead", "cell": {k: cell[k] for k in ("cell_id", "name", "zone_id")}, "neighbours": neighbours,
            "visit_requests": [{"household_id": c["household_id"], "when": c["updated_at"], "call_id": c["id"]}
                               for c in calls if c["status"] == "VISIT_REQUESTED"]}


def submit_for_neighbour(lead_household_id: str, neighbour_household_id: str, image_b64: str) -> dict:
    lead, nb = _hid(lead_household_id), _hid(neighbour_household_id)
    cell = cell_for(nb)
    if cell is None or cell["lead_household_id"] != lead:
        raise ApprovalError("You can send photos only for households in the Nyumba Kumi cell you lead.")
    if nb == lead:
        raise ApprovalError("For your own farm, use AI Scan.")
    receipt = fieldscan.submit_for_review(image_b64, nb, submitted_by=lead)
    telemetry.record(f"cell-{cell['cell_id']}", "farmer", "lead_photo_for_neighbour",
                     {"lead": lead, "neighbour": nb}, {"scan_id": receipt["scan_id"]}, latency_ms=0, actor=lead)
    name = next((m["farmer_name"] for m in cell["members"] if m["household_id"] == nb), nb)
    return receipt | {"message": f"Sent to the extension officer for {name}. They will get the result by SMS "
                                 "(and a phone call if the officer chooses). You will see it here too."}


def set_contact(household_id: str, officer_name: str, phone: str | None, phone_type: str | None,
                cell_id: str | None) -> dict:
    """Officer records a farmer's phone and cell (from a visit or the chief's Nyumba Kumi register)."""
    officer = validate_signature(officer_name)
    hid = _hid(household_id)
    phone = re.sub(r"[\s\-()]", "", phone or "")
    if phone.startswith("07") or phone.startswith("01"):
        phone = "+254" + phone[1:]
    if phone and not voice_calls.PHONE_RE.match(phone):
        raise ApprovalError("Phone must be a Kenyan mobile number, e.g. 0712 345 678 or +254712345678.")
    if phone_type and phone_type not in PHONE_TYPES:
        raise ApprovalError("Phone type must be smartphone or feature.")
    with connect() as conn:
        if conn.execute("SELECT 1 FROM plots WHERE household_id = ?", (hid,)).fetchone() is None:
            raise ApprovalError("Household not found.")
        if cell_id:
            if conn.execute("SELECT 1 FROM nyumba_cells WHERE cell_id = ?", (cell_id,)).fetchone() is None:
                raise ApprovalError("Unknown Nyumba Kumi cell.")
            size = conn.execute("SELECT COUNT(*) FROM plots WHERE cell_id = ? AND household_id != ?",
                                (cell_id, hid)).fetchone()[0]
            if size >= config.NYUMBA_KUMI_MAX:
                raise ApprovalError(f"That cell already has {config.NYUMBA_KUMI_MAX} households.")
        # None = keep what is on file; an empty cell_id takes the farm out of its cell.
        cur = dict(conn.execute("SELECT phone, phone_type, cell_id FROM plots WHERE household_id = ?", (hid,)).fetchone())
        phone = phone or cur["phone"]
        phone_type = phone_type or cur["phone_type"]
        cell_id = cur["cell_id"] if cell_id is None else (cell_id or None)
        conn.execute("UPDATE plots SET phone = ?, phone_type = ?, cell_id = ? WHERE household_id = ?",
                     (phone, phone_type, cell_id, hid))
    telemetry.record(f"contact-{hid}", "officer", "set_contact",
                     {"household_id": hid, "phone_type": phone_type, "cell_id": cell_id},
                     {"phone_set": bool(phone)}, latency_ms=0, actor=officer)
    return {"household_id": hid, "phone": phone, "phone_type": phone_type, "cell_id": cell_id}

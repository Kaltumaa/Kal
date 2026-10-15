"""Plot history log: field actions entered by the officer or reported by the farmer.

A PLANTING entry also updates the farm's record (crop and planting date), so the agent's crop calendar uses it.
Entries are data, not advice: nothing here contacts anyone.
"""
from __future__ import annotations

from datetime import date

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError, validate_signature

ACTIONS = ["PLANTING", "VARIETY", "FERTILISER", "IRRIGATION", "WEEDING", "SPRAYING", "HARVEST", "OBSERVATION"]


def list_actions(household_id: str) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM plot_actions WHERE household_id = ? ORDER BY action_date DESC, id DESC", (household_id,))]


def log_action(household_id: str, action: str, action_date: str, crop: str | None, details: str,
               role: str, name: str | None) -> dict:
    action = (action or "").upper()
    if action not in ACTIONS:
        raise ApprovalError(f"Action must be one of {ACTIONS}.")
    try:
        when = date.fromisoformat(action_date)
    except ValueError as exc:
        raise ApprovalError("Use a date like 2026-10-15.") from exc
    if when > config.today():
        raise ApprovalError("The date cannot be in the future.")
    text, hits = sanitizer.scrub_free_text(details, 300)
    if hits:
        raise ApprovalError("The note contains instruction-like text and was not saved.")
    crop_name = sanitizer.normalise_crop(crop) if crop else None
    if action == "PLANTING" and not crop_name:
        raise ApprovalError("Choose the crop that was planted.")
    with connect() as conn:
        farm = conn.execute("SELECT * FROM plots WHERE household_id = ?", (household_id,)).fetchone()
        if farm is None:
            raise ApprovalError("Farm not found.")
        if role == "officer":
            who = validate_signature(name or "")
        elif role == "farmer":
            who = farm["farmer_name"] or household_id          # the logged-in farmer, from their own record
        else:
            raise ApprovalError("Unknown role.")
        cur = conn.execute("INSERT INTO plot_actions (household_id, action, action_date, crop, details, "
                           "entered_by_role, entered_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                           (household_id, action, when.isoformat(), crop_name, text, role, who, telemetry.now_iso()))
        if action == "PLANTING":
            conn.execute("UPDATE plots SET active_crop = ?, planting_date = ?, days_since_planting = NULL, "
                         "growth_stage = NULL WHERE household_id = ?", (crop_name, when.isoformat(), household_id))
    telemetry.record(f"plot-{household_id}", role, "log_plot_action",
                     {"household_id": household_id, "action": action, "date": when.isoformat(), "crop": crop_name},
                     {"action_id": cur.lastrowid}, latency_ms=0, actor=who)
    return {"action_id": cur.lastrowid, "action": action, "entered_by": who, "updated_record": action == "PLANTING"}

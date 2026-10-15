"""Farmer's own reminders. Creating one is private and not logged; ticking it done adds a field-log entry
(which writes an audit line), so the plot history shows what was actually done."""
from __future__ import annotations

from datetime import date

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError
from crop_pilot.plots import actions

REMINDER_ACTIONS = ["WEEDING", "FERTILISER", "IRRIGATION", "SPRAYING", "OBSERVATION", "HARVEST", "VARIETY"]


def list_reminders(household_id: str) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM farmer_reminders WHERE household_id = ? ORDER BY done, due_date, id", (household_id,))]


def create(household_id: str, due_date: str, action: str, note: str) -> dict:
    action = (action or "").upper()
    if action not in REMINDER_ACTIONS:
        raise ApprovalError(f"Reminder must be one of {REMINDER_ACTIONS}.")
    try:
        due = date.fromisoformat(due_date)
    except ValueError as exc:
        raise ApprovalError("Pick a date.") from exc
    text, hits = sanitizer.scrub_free_text(note, 200)
    if hits:
        raise ApprovalError("The note contains instruction-like text and was not saved.")
    with connect() as conn:
        if conn.execute("SELECT 1 FROM plots WHERE household_id = ?", (household_id,)).fetchone() is None:
            raise ApprovalError("Farm not found.")
        cur = conn.execute("INSERT INTO farmer_reminders (household_id, due_date, action, note, created_at)"
                           " VALUES (?,?,?,?,?)", (household_id, due.isoformat(), action, text, telemetry.now_iso()))
    return {"reminder_id": cur.lastrowid, "due_date": due.isoformat(), "action": action}


def mark_done(reminder_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM farmer_reminders WHERE id = ?", (reminder_id,)).fetchone()
    if row is None or row["done"]:
        raise ApprovalError("Reminder not found or already done.")
    entry = actions.log_action(row["household_id"], row["action"], config.today().isoformat(), None,
                               (row["note"] or "") + f" (reminder due {row['due_date']})", "farmer", None)
    with connect() as conn:
        conn.execute("UPDATE farmer_reminders SET done = 1, done_at = ?, field_log_id = ? WHERE id = ?",
                     (telemetry.now_iso(), entry["action_id"], reminder_id))
    return {"reminder_id": reminder_id, "done": True, "field_log_id": entry["action_id"]}

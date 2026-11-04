"""Community discussion board for farmers and officers (pests, weather, soil, greenhouse).

Posts are untrusted text. They are scrubbed, and anything instruction-like is held back for moderation.
The advisory agent never reads this board: chat posts are not verified signals.
"""
from __future__ import annotations

import re

from crop_pilot import config
from crop_pilot.core import agronomy, sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError, validate_signature

TOPICS = ["Pests & diseases", "Weather & rain", "Soil & weeds", "Greenhouse", "General"]
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z '\-.]{1,39}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS forum_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL, author TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'farmer',
    body TEXT NOT NULL, created_at TEXT NOT NULL, held INTEGER NOT NULL DEFAULT 0, hold_reason TEXT,
    zone_id TEXT, household_id TEXT, source TEXT DEFAULT 'app',
    review_status TEXT,            -- NULL (not reviewed) | CONFIRMED | NOT_CONFIRMED: officer, for pest reports
    reviewed_by TEXT, reviewed_at TEXT, pest_alert_id INTEGER
);
"""

SEED = [
    ("Pests & diseases", "Mama Njeri", "farmer", "Seeing small holes and sawdust in my maize whorls near Mutu-ini. Anyone else?"),
    ("Pests & diseases", "Officer Otieno", "officer", "Fall Armyworm is confirmed around Mutu-ini this week. Scout 20 plants in a W; "
     "spray only if 10% show fresh damage, early morning, and not before rain."),
    ("Weather & rain", "Kamau W.", "farmer", "Got about 12 mm last night in Riruta. Is it enough to plant beans?"),
    ("Weather & rain", "Officer Otieno", "officer", "Wait until about 25 mm is expected over the week. The desk will send a PLANT advisory per household."),
    ("Greenhouse", "Achieng", "farmer", "My greenhouse tomatoes have white mould in the mornings. Too humid?"),
    ("Soil & weeds", "Mutua", "farmer", "Striga is taking over my maize plot. Desmodium worked for my neighbour."),
]


REVIEW_COLUMNS = ("zone_id", "household_id", "source", "review_status", "reviewed_by", "reviewed_at", "pest_alert_id")


def _ensure(conn) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(forum_posts)")}
    for col in REVIEW_COLUMNS:
        if col not in cols:
            conn.execute(f"ALTER TABLE forum_posts ADD COLUMN {col} {'INTEGER' if col == 'pest_alert_id' else 'TEXT'}")
    # The seeded armyworm question names its ward in the text.
    conn.execute("UPDATE forum_posts SET zone_id='MUTUINI' WHERE zone_id IS NULL AND body LIKE '%Mutu-ini%' "
                 "AND role='farmer'")
    if conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0] == 0:
        conn.executemany("INSERT INTO forum_posts (topic, author, role, body, created_at) VALUES (?,?,?,?,?)",
                         [(t, a, r, b, telemetry.now_iso()) for t, a, r, b in SEED])


def list_posts(topic: str | None = None) -> list[dict]:
    with connect() as conn:
        _ensure(conn)
        q = "SELECT * FROM forum_posts" + (" WHERE topic = ?" if topic else "") + " ORDER BY id DESC LIMIT 200"
        rows = [dict(r) for r in conn.execute(q, (topic,) if topic else ())]
    for r in rows:
        if r["held"]:
            r["body"] = "[Held for moderation: this post contained instruction-like text.]"
    return rows


def post(author: str, topic: str, body: str, zone_id: str | None = None, household_id: str | None = None,
         source: str = "app") -> dict:
    name = sanitizer.normalise_text(author)
    if not NAME_RE.match(name):
        raise ValueError("Use a display name of 2–40 letters.")
    if topic not in TOPICS:
        raise ValueError(f"Topic must be one of {TOPICS}.")
    text, hits = sanitizer.scrub_free_text(body, 800)
    if hits:
        text = sanitizer.normalise_text(body)[:800]       # stored for the moderator, never displayed
    if len(text.strip()) < 3:
        raise ValueError("Write a message first.")
    zone = sanitizer.normalise_zone(zone_id) if zone_id else None
    if zone and zone not in config.DAGORETTI_SOUTH_WARDS:
        raise ValueError("Pick a ward in Dagoretti South.")
    with connect() as conn:
        _ensure(conn)
        cur = conn.execute("INSERT INTO forum_posts (topic, author, role, body, created_at, held, hold_reason, zone_id,"
                           " household_id, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (topic, name, "farmer", text, telemetry.now_iso(), int(bool(hits)),
                            "instruction-like text" if hits else None, zone, household_id, source))
    return {"id": cur.lastrowid, "held": bool(hits)}


def pending_reports() -> list[dict]:
    """Farmer posts about pests that an officer has not confirmed or rejected yet."""
    return [p for p in list_posts("Pests & diseases") if p["role"] == "farmer" and not p["held"]
            and not p.get("review_status")]


def review_report(post_id: int, officer_name: str, decision: str, pest: str | None = None, severity: str = "MEDIUM",
                  zone_id: str | None = None, note: str = "") -> dict:
    """Officer confirms (-> a verified pest alert the agent uses, plus the ward's spray-safety advice) or rejects a
    community report. The officer's answer is posted on the board and, if the farmer reported by SMS, texted back."""
    from crop_pilot.dispatch import sms           # local import: sms imports this module

    officer = validate_signature(officer_name)
    if decision not in ("CONFIRMED", "NOT_CONFIRMED"):
        raise ApprovalError("Decision must be CONFIRMED or NOT_CONFIRMED.")
    if severity not in ("LOW", "MEDIUM", "HIGH"):
        raise ApprovalError("Severity must be LOW, MEDIUM or HIGH.")
    note_clean, hits = sanitizer.scrub_free_text(note, 400)
    if hits:
        raise ApprovalError("The note contains instruction-like text.")
    with connect() as conn:
        _ensure(conn)
        row = conn.execute("SELECT * FROM forum_posts WHERE id = ?", (post_id,)).fetchone()
        if row is None or row["role"] != "farmer" or row["held"] or row["review_status"]:
            raise ApprovalError("Report not found, held, or already reviewed.")
        zone = sanitizer.normalise_zone(zone_id or row["zone_id"])
        alert_id, safety = None, None
        if decision == "CONFIRMED":
            pest_name = sanitizer.normalise_text(pest)[:60]
            if not pest_name:
                raise ApprovalError("Name the pest or disease you confirmed.")
            if zone not in config.DAGORETTI_SOUTH_WARDS:
                raise ApprovalError("Pick the ward the report is from.")
            w = conn.execute("SELECT * FROM weather_cache WHERE zone_id = ?", (zone,)).fetchone()
            alert_id = conn.execute(
                "INSERT INTO pest_alerts (zone_id, pest, lat, lon, distance_km, severity, verified, reported_at, source)"
                " VALUES (?,?,?,?,?,?,1,?,?)", (zone, pest_name, w["centroid_lat"] if w else None,
                                                 w["centroid_lon"] if w else None, None, severity,
                                                 config.today().isoformat(),
                                                 f"Community report #{post_id} confirmed by {officer}")).lastrowid
            safety = spray_safety(dict(w)) if w else None
            reply = (f"Confirmed: {pest_name} in {zone.title()} (checked by the extension officer). "
                     + (f"Spraying today: {safety['label']} (spray-safety score {safety['index']:.0f}/100). "
                        if safety else "")
                     + "Scout your own plants before spraying.")
        else:
            reply = "Checked by the extension officer: not confirmed as a pest problem."
        if note_clean:
            reply += f" {note_clean}"
        conn.execute("UPDATE forum_posts SET review_status=?, reviewed_by=?, reviewed_at=?, pest_alert_id=?, zone_id=? "
                     "WHERE id=?", (decision, officer, telemetry.now_iso(), alert_id, zone, post_id))
        conn.execute("INSERT INTO forum_posts (topic, author, role, body, created_at, zone_id) VALUES (?,?,?,?,?,?)",
                     (row["topic"], officer[:40], "officer", f"Re: {row['author']}. {reply}", telemetry.now_iso(), zone))
    sms_id = sms.queue_out(row["household_id"], reply, "community_result", post_id, officer) \
        if row["household_id"] else None
    telemetry.record(f"community-{post_id}", "officer", "review_community_report",
                     {"post_id": post_id, "decision": decision, "pest": pest, "zone_id": zone},
                     {"pest_alert_id": alert_id, "sms_id": sms_id}, latency_ms=0, actor=officer, approved_by=officer)
    return {"post_id": post_id, "status": decision, "pest_alert_id": alert_id, "spray_safety": safety,
            "reply": reply, "sms_id": sms_id}


def spray_safety(weather_row: dict) -> dict:
    """The ward's spray-safety reading today, as the officer's advice after confirming a pest."""
    r = agronomy.rainfall_outlook(weather_row)
    return {"index": r["spray_safety_index"], "band": r["spray_band"], "status": r["spray_status"],
            "label": r["spray_label"]}

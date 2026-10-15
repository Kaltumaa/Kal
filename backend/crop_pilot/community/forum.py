"""Community discussion board for farmers and officers (pests, weather, soil, greenhouse).

Posts are untrusted text. They are scrubbed, and anything instruction-like is held back for moderation.
The advisory agent never reads this board: chat posts are not verified signals.
"""
from __future__ import annotations

import re

from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect

TOPICS = ["Pests & diseases", "Weather & rain", "Soil & weeds", "Greenhouse", "General"]
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z '\-.]{1,39}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS forum_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL, author TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'farmer',
    body TEXT NOT NULL, created_at TEXT NOT NULL, held INTEGER NOT NULL DEFAULT 0, hold_reason TEXT
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


def _ensure(conn) -> None:
    conn.executescript(SCHEMA)
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


def post(author: str, topic: str, body: str) -> dict:
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
    with connect() as conn:
        _ensure(conn)
        cur = conn.execute("INSERT INTO forum_posts (topic, author, role, body, created_at, held, hold_reason)"
                           " VALUES (?,?,?,?,?,?,?)", (topic, name, "farmer", text, telemetry.now_iso(),
                                                      int(bool(hits)), "instruction-like text" if hits else None))
    return {"id": cur.lastrowid, "held": bool(hits)}

"""Camera field scans: photo -> LOCAL vision model -> symptom match -> UNVERIFIED report -> officer verifies.

A scan never becomes a pest signal on its own. Only `verify()` (called by the API when a named officer
submits the form) turns it into a verified pest_alert that the advisory agent will then use.
The agent package never imports this module (enforced by tests/test_boundaries.py).
"""
from __future__ import annotations

import base64
import binascii
import json
import time

import httpx

from crop_pilot import config
from crop_pilot.core import knowledge, sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError, validate_signature

VISION_MODEL = config.VISION_MODEL
SCAN_DIR = config.DATA_DIR / "scans"
MAX_IMAGE_BYTES = 6_000_000
# Neutral, natural questions on purpose. A leading prompt ("describe the holes...") made the small model invent
# damage, it returns nothing for "answer with one word", and its weed/crop answer flips with word order, so we ask
# three phrasings and take the majority. Damage is judged only by "Do the leaves look healthy?".
CAPTION_PROMPT = "What plant is shown in this photo, and what condition is it in?"
SUBJECT_PROMPTS = ["Is this plant a weed or a crop?", "Is this plant a crop or a weed?",
                   "Is this a cultivated crop plant growing on purpose, or a wild weed?"]
HEALTH_PROMPT = "Do the leaves look healthy?"

SCHEMA = """
CREATE TABLE IF NOT EXISTS field_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT, crop TEXT, image_file TEXT NOT NULL, model TEXT,
    description TEXT, candidates_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (status IN ('UNVERIFIED','VERIFIED','DISMISSED')),
    created_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, pest_alert_id INTEGER,
    officer_finding TEXT, officer_note TEXT,
    CHECK (status = 'UNVERIFIED' OR reviewed_by IS NOT NULL)
);
"""


def _ensure(conn) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(field_scans)")}
    for col in ("officer_finding", "officer_note"):
        if col not in cols:
            conn.execute(f"ALTER TABLE field_scans ADD COLUMN {col} TEXT")   # fixed names, no user input


class ScanError(ValueError):
    pass


def _ask(image_b64: str, prompt: str, max_tokens: int) -> tuple[str, dict]:
    started = time.perf_counter()
    with httpx.Client(timeout=config.LLM_TIMEOUT_S * 2) as client:
        r = client.post(f"{config.OLLAMA_HOST}/api/generate", json={
            "model": VISION_MODEL, "prompt": prompt, "images": [image_b64], "stream": False,
            "options": {"temperature": 0, "num_predict": max_tokens}})
        r.raise_for_status()
        data = r.json()
    return data.get("response", "").strip(), {"latency_ms": (time.perf_counter() - started) * 1000,
                                              "tokens": int(data.get("prompt_eval_count", 0))
                                              + int(data.get("eval_count", 0))}


def _describe(image_b64: str) -> tuple[str, dict]:
    text, meta = _ask(image_b64, CAPTION_PROMPT, 110)
    if "." in text and not text.rstrip().endswith("."):
        text = text[: text.rfind(".") + 1]          # drop a sentence cut off by the token limit
    return text, meta


def _classify(image_b64: str) -> tuple[dict, dict]:
    answers, latency, tokens = [], 0.0, 0
    for prompt in SUBJECT_PROMPTS + [HEALTH_PROMPT]:
        text, m = _ask(image_b64, prompt, 24)
        answers.append(text)
        latency, tokens = latency + m["latency_ms"], tokens + m["tokens"]
    return {"subjects": answers[:-1], "healthy": answers[-1]}, {"latency_ms": latency, "tokens": tokens}


def analyse(image_b64: str, household_id: str | None, crop: str | None) -> dict:
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ScanError("Image could not be read.") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ScanError("Image is empty or larger than 6 MB.")
    if not (raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n"):
        raise ScanError("Only JPEG or PNG photos are accepted.")

    hid = sanitizer.normalise_text(household_id).upper()[:32] or None
    crop = sanitizer.normalise_crop(crop) if crop else None
    with connect() as conn:
        _ensure(conn)
        if hid and not crop:
            row = conn.execute("SELECT active_crop FROM plots WHERE upper(household_id)=?", (hid,)).fetchone()
            crop = sanitizer.normalise_crop(row["active_crop"]) if row else None

    run_id = f"scan-{int(time.time() * 1000)}"
    model_used = VISION_MODEL
    try:
        description, meta = _describe(image_b64)
        answers, meta2 = _classify(image_b64)
        meta = {"latency_ms": meta["latency_ms"] + meta2["latency_ms"], "tokens": meta["tokens"] + meta2["tokens"]}
        status = "ok"
    except (httpx.HTTPError, ValueError) as exc:
        description, answers, status = "", {"subjects": [], "healthy": ""}, "error"
        meta = {"latency_ms": 0, "tokens": 0, "error": str(exc)[:200]}
        model_used = None
    # Model output about an untrusted photo: treat it as data and scrub it.
    description, hits = sanitizer.scrub_free_text(description, 1200)
    subjects = [sanitizer.scrub_free_text(a, 160)[0] for a in answers.get("subjects", [])]
    healthy, _ = sanitizer.scrub_free_text(answers.get("healthy"), 160)
    verdict = knowledge.classify_photo(description, subjects, healthy, crop) if not hits else \
        {"category": "unclear", "votes": [], "signs": None, "candidates": []}
    candidates = verdict["candidates"]
    signs_label = {True: "yes", False: "no", None: "unclear"}[verdict["signs"]]
    description = (f"{description} [AI checks: main subject = {verdict['category']} "
                   f"(votes: {', '.join(verdict['votes']) or 'none'}); damage = {signs_label}]")
    telemetry.record(run_id, "ollama", f"vision:{VISION_MODEL}", {"household_id": hid, "crop": crop, "bytes": len(raw)},
                     {"description": description, "candidates": candidates}, latency_ms=meta["latency_ms"],
                     token_count=meta.get("tokens"), status=status)

    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    ext = "png" if raw[:4] == b"\x89PNG" else "jpg"
    with connect() as conn:
        cur = conn.execute("INSERT INTO field_scans (household_id, crop, image_file, model, description, "
                           "candidates_json, created_at) VALUES (?,?,?,?,?,?,?)",
                           (hid, crop, "pending", model_used, description, json.dumps(candidates), telemetry.now_iso()))
        scan_id = cur.lastrowid
        name = f"scan_{scan_id}.{ext}"
        (SCAN_DIR / name).write_bytes(raw)
        conn.execute("UPDATE field_scans SET image_file=? WHERE id=?", (name, scan_id))
    return {"scan_id": scan_id, "household_id": hid, "crop": crop, "description": description,
            "plant_seen": knowledge.plant_seen(description), "category": verdict["category"],
            "damage_signs": verdict["signs"],
            "candidates": candidates, "model": model_used, "status": "UNVERIFIED",
            "vision_available": status == "ok", "injection_flag": bool(hits)}


def list_scans() -> list[dict]:
    with connect() as conn:
        _ensure(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM field_scans ORDER BY id DESC LIMIT 50")]
    for r in rows:
        r["candidates"] = json.loads(r.pop("candidates_json") or "[]")
    return rows


def image_bytes(scan_id: int) -> bytes | None:
    with connect() as conn:
        _ensure(conn)
        row = conn.execute("SELECT image_file FROM field_scans WHERE id=?", (scan_id,)).fetchone()
    if not row:
        return None
    path = SCAN_DIR / row["image_file"]
    return path.read_bytes() if path.exists() and path.parent == SCAN_DIR else None


def farmer_view(household_id: str) -> list[dict]:
    """What a farmer may see about their own photos: status and the OFFICER's finding only, never the AI's guess."""
    with connect() as conn:
        _ensure(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT s.id, s.created_at, s.status, s.reviewed_by, s.reviewed_at, s.officer_finding, s.officer_note, "
            "a.pest AS alert_pest FROM field_scans s LEFT JOIN pest_alerts a ON a.id = s.pest_alert_id "
            "WHERE s.household_id = ? ORDER BY s.id DESC", (household_id,))]
    for r in rows:
        r["waiting"] = r["status"] == "UNVERIFIED"
        if not r["waiting"] and not r["officer_finding"]:     # reviews made before findings were stored as text
            r["officer_finding"] = r["alert_pest"] or ("No problem found" if r["status"] == "DISMISSED"
                                                        else "Confirmed by your officer")
        r.pop("alert_pest")
    return rows


def submit_for_review(image_b64: str, household_id: str) -> dict:
    """Farmer submission: the photo is analysed for the officer, but the farmer only gets a receipt."""
    res = analyse(image_b64, household_id, None)
    return {"scan_id": res["scan_id"], "status": "WAITING_FOR_OFFICER",
            "message": "Sent to your extension officer for review. You will see the result in Notifications."}


def review(scan_id: int, officer_name: str, decision: str, pest: str | None = None, severity: str = "MEDIUM",
           note: str = "") -> dict:
    """Named officer verifies (-> verified pest_alert used by the agent) or dismisses a scan."""
    officer = validate_signature(officer_name)
    if decision not in ("VERIFIED", "DISMISSED"):
        raise ApprovalError("Decision must be VERIFIED or DISMISSED.")
    if severity not in ("LOW", "MEDIUM", "HIGH"):
        raise ApprovalError("Severity must be LOW, MEDIUM or HIGH.")
    alert_id = None
    with connect() as conn:
        _ensure(conn)
        scan = conn.execute("SELECT * FROM field_scans WHERE id=?", (scan_id,)).fetchone()
        if scan is None or scan["status"] != "UNVERIFIED":
            raise ApprovalError("Scan not found or already reviewed.")
        if decision == "VERIFIED":
            pest_name = sanitizer.normalise_text(pest)[:60]
            if not pest_name:
                raise ApprovalError("Name the pest or disease you confirmed.")
            plot = conn.execute("SELECT * FROM plots WHERE upper(household_id)=?",
                                (scan["household_id"] or "",)).fetchone()
            clean = sanitizer.scrub_plot(dict(plot)) if plot else {}
            zone = clean.get("zone_id")
            if not zone:
                raise ApprovalError("Scan is not linked to a household with a known zone; cannot place the alert.")
            if clean.get("lat") is None:
                w = conn.execute("SELECT centroid_lat, centroid_lon FROM weather_cache WHERE zone_id=?", (zone,)).fetchone()
                lat, lon = (w["centroid_lat"], w["centroid_lon"]) if w else (None, None)
            else:
                lat, lon = clean["lat"], clean["lon"]
            cur = conn.execute(
                "INSERT INTO pest_alerts (zone_id, pest, lat, lon, distance_km, severity, verified, reported_at, source)"
                " VALUES (?,?,?,?,?,?,1,?,?)",
                (zone, pest_name, lat, lon, None, severity, config.today().isoformat(),
                 f"Field scan #{scan_id} verified by {officer}"))
            alert_id = cur.lastrowid
        finding = sanitizer.normalise_text(pest)[:60] if decision == "VERIFIED" else "No problem found"
        note_clean, note_hits = sanitizer.scrub_free_text(note, 1200)
        if note_hits:
            raise ApprovalError("The note to the farmer contains instruction-like text.")
        conn.execute("UPDATE field_scans SET officer_finding=?, officer_note=? WHERE id=?",
                     (finding, note_clean, scan_id))
        conn.execute("UPDATE field_scans SET status=?, reviewed_by=?, reviewed_at=?, pest_alert_id=? WHERE id=?",
                     (decision, officer, telemetry.now_iso(), alert_id, scan_id))
    telemetry.record(f"scan-review-{scan_id}", "officer", "review_field_scan",
                     {"scan_id": scan_id, "decision": decision, "pest": pest, "severity": severity},
                     {"pest_alert_id": alert_id}, latency_ms=0, actor=officer, approved_by=officer)
    return {"scan_id": scan_id, "status": decision, "officer": officer, "pest_alert_id": alert_id}

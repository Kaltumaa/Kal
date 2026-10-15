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
VISION_PROMPT = ("Describe this crop photo for an agricultural extension officer. Name the plant if you can, then "
                 "describe any visible damage: holes, chewed edges, spots, lesions, discoloration, yellowing, mould, "
                 "insects or caterpillars. Be specific and brief.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS field_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT, crop TEXT, image_file TEXT NOT NULL, model TEXT,
    description TEXT, candidates_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (status IN ('UNVERIFIED','VERIFIED','DISMISSED')),
    created_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, pest_alert_id INTEGER,
    CHECK (status = 'UNVERIFIED' OR reviewed_by IS NOT NULL)
);
"""


class ScanError(ValueError):
    pass


def _describe(image_b64: str) -> tuple[str, dict]:
    started = time.perf_counter()
    with httpx.Client(timeout=config.LLM_TIMEOUT_S * 2) as client:
        r = client.post(f"{config.OLLAMA_HOST}/api/generate", json={
            "model": VISION_MODEL, "prompt": VISION_PROMPT, "images": [image_b64], "stream": False,
            "options": {"temperature": 0.2}})
        r.raise_for_status()
        data = r.json()
    meta = {"latency_ms": (time.perf_counter() - started) * 1000,
            "tokens": int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0))}
    return data.get("response", ""), meta


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
        conn.executescript(SCHEMA)
        if hid and not crop:
            row = conn.execute("SELECT active_crop FROM plots WHERE upper(household_id)=?", (hid,)).fetchone()
            crop = sanitizer.normalise_crop(row["active_crop"]) if row else None

    run_id = f"scan-{int(time.time() * 1000)}"
    model_used = VISION_MODEL
    try:
        description, meta = _describe(image_b64)
        status = "ok"
    except (httpx.HTTPError, ValueError) as exc:
        description, meta, status = "", {"latency_ms": 0, "tokens": 0, "error": str(exc)[:200]}, "error"
        model_used = None
    # The caption is model output about an untrusted photo: treat it as data and scrub it.
    description, hits = sanitizer.scrub_free_text(description, 1200)
    candidates = knowledge.match_symptoms(description, crop) if not hits else []
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
            "candidates": candidates, "model": model_used, "status": "UNVERIFIED",
            "vision_available": status == "ok", "injection_flag": bool(hits)}


def list_scans() -> list[dict]:
    with connect() as conn:
        conn.executescript(SCHEMA)
        rows = [dict(r) for r in conn.execute("SELECT * FROM field_scans ORDER BY id DESC LIMIT 50")]
    for r in rows:
        r["candidates"] = json.loads(r.pop("candidates_json") or "[]")
    return rows


def image_bytes(scan_id: int) -> bytes | None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT image_file FROM field_scans WHERE id=?", (scan_id,)).fetchone()
    if not row:
        return None
    path = SCAN_DIR / row["image_file"]
    return path.read_bytes() if path.exists() and path.parent == SCAN_DIR else None


def review(scan_id: int, officer_name: str, decision: str, pest: str | None = None, severity: str = "MEDIUM") -> dict:
    """Named officer verifies (-> verified pest_alert used by the agent) or dismisses a scan."""
    officer = validate_signature(officer_name)
    if decision not in ("VERIFIED", "DISMISSED"):
        raise ApprovalError("Decision must be VERIFIED or DISMISSED.")
    if severity not in ("LOW", "MEDIUM", "HIGH"):
        raise ApprovalError("Severity must be LOW, MEDIUM or HIGH.")
    alert_id = None
    with connect() as conn:
        conn.executescript(SCHEMA)
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
        conn.execute("UPDATE field_scans SET status=?, reviewed_by=?, reviewed_at=?, pest_alert_id=? WHERE id=?",
                     (decision, officer, telemetry.now_iso(), alert_id, scan_id))
    telemetry.record(f"scan-review-{scan_id}", "officer", "review_field_scan",
                     {"scan_id": scan_id, "decision": decision, "pest": pest, "severity": severity},
                     {"pest_alert_id": alert_id}, latency_ms=0, actor=officer, approved_by=officer)
    return {"scan_id": scan_id, "status": decision, "officer": officer, "pest_alert_id": alert_id}

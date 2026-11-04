"""Camera field scans: photo -> LOCAL vision model -> symptom match -> UNVERIFIED report -> officer verifies.

A scan never becomes a pest signal on its own. Only `verify()` (called by the API when a named officer
submits the form) turns it into a verified pest_alert that the advisory agent will then use.
The agent package never imports this module (enforced by tests/test_boundaries.py).
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import time

import httpx
from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

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
PRESENT_PROMPT = "Is there a plant, a leaf or an insect in this photo? Answer yes or no."

# What the officer can record when a photo has nothing to diagnose (status DISMISSED, with this finding).
DISMISS_FINDINGS = ["No problem found", "Not a plant or pest: advice not applicable",
                    "Photo unclear: field visit needed"]
FINDINGS_SW = {"No problem found": "Hakuna tatizo lililoonekana.",
               "Not a plant or pest: advice not applicable": "Picha haionyeshi mmea wala mdudu, kwa hiyo hakuna ushauri.",
               "Photo unclear: field visit needed": "Picha haikuwa wazi. Afisa atakupigia simu au kukutembelea."}
# Photos grouped for one signed review must be clear and have at least this symptom-match score (not a probability).
GROUP_MIN_SCORE = 0.5

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
    for col in ("officer_finding", "officer_note", "image_quality", "submitted_by", "cloud_json", "ai_draft_json"):
        if col not in cols:
            conn.execute(f"ALTER TABLE field_scans ADD COLUMN {col} TEXT")   # fixed names, no user input


class ScanError(ValueError):
    pass


# Measured on real farmer photos vs blurred/darkened copies: sharp photos scored 300-5000, blurred 22-43;
# normal brightness 130-160, darkened 26-31. See tests/test_hub.py.
BLUR_MIN_SHARPNESS = 60.0
DARK_MAX_BRIGHTNESS = 40.0
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


def image_quality(raw: bytes) -> dict:
    """Blurry or dark photos make any AI suggestion unreliable; flag them for the officer (no model involved)."""
    try:
        g = Image.open(io.BytesIO(raw)).convert("L")
    except (UnidentifiedImageError, OSError):
        return {"issues": ["unreadable"], "sharpness": None, "brightness": None}
    g.thumbnail((640, 640))
    w, h = g.size
    g = g.crop((w // 10, h // 10, w - w // 10, h - h // 10)) if min(w, h) >= 20 else g
    sharp = round(ImageStat.Stat(g.filter(_LAPLACIAN)).var[0], 1)
    bright = round(ImageStat.Stat(g).mean[0], 1)
    issues = (["blurry"] if sharp < BLUR_MIN_SHARPNESS else []) + (["dark"] if bright < DARK_MAX_BRIGHTNESS else [])
    return {"issues": issues, "sharpness": sharp, "brightness": bright}


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
    for prompt in SUBJECT_PROMPTS + [HEALTH_PROMPT, PRESENT_PROMPT]:
        text, m = _ask(image_b64, prompt, 24)
        answers.append(text)
        latency, tokens = latency + m["latency_ms"], tokens + m["tokens"]
    return ({"subjects": answers[:-2], "healthy": answers[-2], "present": answers[-1]},
            {"latency_ms": latency, "tokens": tokens})


def _yes_no(text: str | None) -> bool | None:
    t = (text or "").strip().lower()
    return True if t.startswith("yes") else False if t.startswith("no") else None


def analyse(image_b64: str, household_id: str | None, crop: str | None, submitted_by: str | None = None) -> dict:
    """Local vision model (and DeepLeaf, if configured) -> UNVERIFIED scan for the officer.
    `submitted_by` = the lead farmer's household when they send a photo for a Nyumba Kumi neighbour."""
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

    quality = image_quality(raw)
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
    # "No plant, leaf or insect" only counts when nothing else in the AI's answers points to one.
    present = _yes_no(sanitizer.scrub_free_text(answers.get("present"), 40)[0]) if status == "ok" else None
    quality["subject_present"] = False if (present is False and verdict["category"] == "unclear"
                                           and not knowledge.plant_seen(description)
                                           and not verdict["candidates"]) else present
    candidates = verdict["candidates"]
    signs_label = {True: "yes", False: "no", None: "unclear"}[verdict["signs"]]
    description = (f"{description} [AI checks: main subject = {verdict['category']} "
                   f"(votes: {', '.join(verdict['votes']) or 'none'}); damage = {signs_label}]")
    telemetry.record(run_id, "ollama", f"vision:{VISION_MODEL}", {"household_id": hid, "crop": crop, "bytes": len(raw)},
                     {"description": description, "candidates": candidates}, latency_ms=meta["latency_ms"],
                     token_count=meta.get("tokens"), status=status)

    from crop_pilot.fieldscan import deepleaf          # optional cloud second opinion, for the officer only
    cloud = deepleaf.second_opinion(raw, hid, crop)
    # Qwen turns the best diagnosis text into the officer's draft and a Kiswahili call script (both drafts).
    from crop_pilot.fieldscan import voice_draft
    diagnosis = cloud["officer_draft"] if cloud and cloud.get("status") == "ok" else description
    ai_draft = voice_draft.draft(diagnosis, crop, candidates[0]["pest"] if candidates else None) \
        if (status == "ok" or (cloud and cloud.get("status") == "ok")) and not hits else None

    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    ext = "png" if raw[:4] == b"\x89PNG" else "jpg"
    with connect() as conn:
        cur = conn.execute("INSERT INTO field_scans (household_id, crop, image_file, model, description, "
                           "candidates_json, created_at, image_quality, submitted_by, cloud_json, ai_draft_json) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (hid, crop, "pending", model_used, description, json.dumps(candidates), telemetry.now_iso(),
                            json.dumps(quality), submitted_by, json.dumps(cloud) if cloud else None,
                            json.dumps(ai_draft) if ai_draft else None))
        scan_id = cur.lastrowid
        name = f"scan_{scan_id}.{ext}"
        (SCAN_DIR / name).write_bytes(raw)
        conn.execute("UPDATE field_scans SET image_file=? WHERE id=?", (name, scan_id))
    return {"scan_id": scan_id, "household_id": hid, "crop": crop, "description": description,
            "plant_seen": knowledge.plant_seen(description), "category": verdict["category"],
            "damage_signs": verdict["signs"],
            "candidates": candidates, "model": model_used, "status": "UNVERIFIED",
            "vision_available": status == "ok", "injection_flag": bool(hits), "image_quality": quality,
            "inconclusive": bool(quality["issues"]), "not_a_plant": quality["subject_present"] is False,
            "cloud": cloud, "ai_draft": ai_draft, "submitted_by": submitted_by}


def list_scans() -> list[dict]:
    with connect() as conn:
        _ensure(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM field_scans ORDER BY id DESC LIMIT 50")]
    for r in rows:
        r["candidates"] = json.loads(r.pop("candidates_json") or "[]")
        r["image_quality"] = json.loads(r.get("image_quality") or "{}")
        r["inconclusive"] = bool(r["image_quality"].get("issues"))          # blurry, dark or unreadable
        r["not_a_plant"] = r["image_quality"].get("subject_present") is False
        r["cloud"] = json.loads(r.pop("cloud_json", None) or "null")
        r["ai_draft"] = json.loads(r.pop("ai_draft_json", None) or "null")
    return rows


def review_groups(scans: list[dict] | None = None) -> list[dict]:
    """Waiting photos that can be reviewed together: clear, same ward, same top AI suggestion, at least 2.
    The officer still sees every photo and signs once; each photo gets its own review record."""
    scans = scans if scans is not None else list_scans()
    with connect() as conn:
        zones = {r["household_id"]: sanitizer.normalise_zone(r["zone_id"])
                 for r in conn.execute("SELECT household_id, zone_id FROM plots")}
    groups: dict[tuple, list[int]] = {}
    for s in scans:
        top = s["candidates"][0] if s["candidates"] else None
        if s["status"] != "UNVERIFIED" or s["inconclusive"] or s["not_a_plant"] or not top \
                or top["score"] < GROUP_MIN_SCORE or not zones.get(s["household_id"]):
            continue
        groups.setdefault((zones[s["household_id"]], top["pest"]), []).append(s["id"])
    return [{"zone_id": z, "pest": p, "scan_ids": ids} for (z, p), ids in sorted(groups.items()) if len(ids) >= 2]


def review_batch(scan_ids: list[int], officer_name: str, pest: str, severity: str = "MEDIUM", note: str = "") -> dict:
    """One signed decision for a group the officer looked at. Refuses photos that are not clear and waiting."""
    officer = validate_signature(officer_name)
    ids = list(dict.fromkeys(int(i) for i in scan_ids))
    if not 2 <= len(ids) <= 50:
        raise ApprovalError("A group review needs 2 to 50 photos.")
    by_id = {s["id"]: s for s in list_scans()}
    bad = [i for i in ids if i not in by_id or by_id[i]["status"] != "UNVERIFIED" or by_id[i]["inconclusive"]
           or by_id[i]["not_a_plant"]]
    if bad:
        raise ApprovalError(f"These photos cannot be reviewed as a group (unclear, not waiting, or no plant): {bad}")
    done = [review(i, officer, "VERIFIED", pest, severity, note) for i in ids]
    return {"verified": [d["scan_id"] for d in done], "officer": officer, "pest": pest}


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
            "s.submitted_by, "
            "a.pest AS alert_pest FROM field_scans s LEFT JOIN pest_alerts a ON a.id = s.pest_alert_id "
            "WHERE s.household_id = ? ORDER BY s.id DESC", (household_id,))]
    for r in rows:
        r["waiting"] = r["status"] == "UNVERIFIED"
        if not r["waiting"] and not r["officer_finding"]:     # reviews made before findings were stored as text
            r["officer_finding"] = r["alert_pest"] or ("No problem found" if r["status"] == "DISMISSED"
                                                        else "Confirmed by your officer")
        r.pop("alert_pest")
    return rows


def submit_for_review(image_b64: str, household_id: str, submitted_by: str | None = None) -> dict:
    """Farmer submission: the photo is analysed for the officer, but the farmer only gets a receipt."""
    res = analyse(image_b64, household_id, None, submitted_by)
    issues = [i for i in res["image_quality"]["issues"] if i != "unreadable"]
    tip = (f" Tip: the photo looks {' and '.join(issues)}; if you can, send another one in daylight, held steady "
           "and close to the leaf.") if issues else ""
    return {"scan_id": res["scan_id"], "status": "WAITING_FOR_OFFICER",
            "message": "Sent to your extension officer for review. You will see the result in Notifications." + tip}


def voice_script(finding: str, note: str, language: str) -> str:
    """Starting text for the officer's call script about a photo (the officer edits it before signing)."""
    if language == "sw":           # Kiswahili only: the English note goes by SMS, not into the spoken Kiswahili
        from crop_pilot.fieldscan import voice_draft
        said = FINDINGS_SW.get(finding) or f"Huenda shamba lako lina tatizo la {voice_draft._sw_name(finding)}."
        return f"Habari. Afisa wako wa kilimo ameangalia picha ya shamba lako. {said} Maelezo kamili yametumwa kwa SMS."
    return (f"Your officer has checked the photo of your farm. Result: {finding}. {note}").strip()


def review(scan_id: int, officer_name: str, decision: str, pest: str | None = None, severity: str = "MEDIUM",
           note: str = "", finding: str | None = None, call: bool = False, call_script: str | None = None,
           call_language: str = "sw") -> dict:
    """Named officer verifies (-> verified pest_alert used by the agent) or dismisses a scan."""
    officer = validate_signature(officer_name)
    if decision not in ("VERIFIED", "DISMISSED"):
        raise ApprovalError("Decision must be VERIFIED or DISMISSED.")
    if severity not in ("LOW", "MEDIUM", "HIGH"):
        raise ApprovalError("Severity must be LOW, MEDIUM or HIGH.")
    if finding is not None and (decision != "DISMISSED" or finding not in DISMISS_FINDINGS):
        raise ApprovalError(f"A dismiss finding must be one of {DISMISS_FINDINGS}.")
    if call:
        from crop_pilot.dispatch import voice_calls
        with connect() as conn:
            _ensure(conn)
            row = conn.execute("SELECT household_id FROM field_scans WHERE id=?", (scan_id,)).fetchone()
        if not row or not row["household_id"]:
            raise ApprovalError("This photo is not linked to a farm, so there is nobody to call.")
        voice_calls.check_phone(row["household_id"])          # refuse before signing, not after
        if (call_script or "").strip():
            voice_calls.check(row["household_id"], call_script, call_language)
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
        finding = sanitizer.normalise_text(pest)[:60] if decision == "VERIFIED" else (finding or "No problem found")
        note_clean, note_hits = sanitizer.scrub_free_text(note, 1200)
        if note_hits:
            raise ApprovalError("The note to the farmer contains instruction-like text.")
        conn.execute("UPDATE field_scans SET officer_finding=?, officer_note=? WHERE id=?",
                     (finding, note_clean, scan_id))
        conn.execute("UPDATE field_scans SET status=?, reviewed_by=?, reviewed_at=?, pest_alert_id=? WHERE id=?",
                     (decision, officer, telemetry.now_iso(), alert_id, scan_id))
    sms_id = None
    if scan["household_id"]:
        # The officer's answer also goes by SMS, so a farmer without data still gets the advice.
        from crop_pilot.dispatch import sms
        sms_id = sms.queue_out(scan["household_id"], f"Mkulima Hub, photo #{scan_id}: {finding}. {note_clean}".strip(),
                               "photo_result", scan_id, officer)
    call_id = None
    if call and scan["household_id"]:
        # A voice call for farmers who cannot read an SMS. The officer's own script, under the same signature.
        from crop_pilot.dispatch import voice_calls
        script = call_script if (call_script or "").strip() else voice_script(finding, note_clean, call_language)
        call_id = voice_calls.queue_call(scan["household_id"], script, call_language, "photo_result", scan_id,
                                         officer)["call_id"]
    telemetry.record(f"scan-review-{scan_id}", "officer", "review_field_scan",
                     {"scan_id": scan_id, "decision": decision, "pest": pest, "severity": severity},
                     {"pest_alert_id": alert_id, "sms_id": sms_id, "call_id": call_id}, latency_ms=0, actor=officer,
                     approved_by=officer)
    return {"scan_id": scan_id, "status": decision, "officer": officer, "pest_alert_id": alert_id, "sms_id": sms_id,
            "call_id": call_id}

"""REST API: the only door between the frontend and the backend.

Run:  uvicorn crop_pilot.api.main:app --port 8000   (with PYTHONPATH=backend)
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Response
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from crop_pilot import config
from crop_pilot.agent import llm
from crop_pilot.agent.workflow import build_graph, resume_run, start_run
from crop_pilot.community import cells, forum
from crop_pilot.core import agronomy, greenhouse, history, knowledge, sanitizer, telemetry, weather_patterns
from crop_pilot.database.db import DatabaseUnavailable, connect, health_check
from crop_pilot.database.init_db import ensure_schema, seed_missing
from crop_pilot.dispatch import approval
from crop_pilot.dispatch import followups as desk_followups
from crop_pilot.dispatch import sms, voice_calls
from crop_pilot.fieldscan import deepleaf
from crop_pilot.fieldscan import service as fieldscan
from crop_pilot.greenhouse import readings as gh_readings
from crop_pilot.plots import actions as plot_actions
from crop_pilot.plots import reminders as farm_reminders
from crop_pilot.voice import speech


logging.basicConfig(level=logging.WARNING, format="%(message)s")
logging.getLogger("crop_pilot.audit").setLevel(logging.INFO)   # audit trail in the backend terminal


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:   # add new tables/columns to an existing database; a corrupt one is handled by /health instead
        with connect() as conn:
            ensure_schema(conn)
            if conn.execute("SELECT COUNT(*) FROM plots").fetchone()[0]:   # only top up a seeded demo database
                seed_missing(conn)
    except Exception:  # noqa: BLE001
        pass
    async with AsyncSqliteSaver.from_conn_string(str(config.CHECKPOINT_DB_PATH)) as saver:
        app.state.graph = build_graph(saver)
        yield


app = FastAPI(title="Mkulima Hub Extension Co-Pilot API", version="1.0.0", lifespan=lifespan)
# Carrier webhooks (/voice/callback): also served here so the internal telephony simulator can post to them.
from crop_pilot.api.voice_hooks import router as voice_webhooks  # noqa: E402
app.include_router(voice_webhooks)


class RunRequest(BaseModel):
    household_id: str = Field(..., max_length=32)
    officer_note: str = Field("", max_length=300)


class ApproveRequest(BaseModel):
    officer_name: str = Field(..., max_length=80)
    final_message: str | None = Field(None, max_length=320)
    final_message_sw: str | None = Field(None, max_length=320)
    languages: list[str] = Field(["en"], min_length=1, max_length=2)   # "en" and/or "sw", one signature for both
    citation: str = Field(..., max_length=600)
    call: bool = False                 # also phone the farmer and read the signed message (feature phones)


class RejectRequest(BaseModel):
    officer_name: str = Field(..., max_length=80)
    reason: str = Field("", max_length=300)


class ManualEntry(BaseModel):
    officer_name: str = Field(..., max_length=80)
    household_id: str = Field(..., max_length=32)
    verdict: str = Field(..., pattern="^(PLANT|SPRAY|HOLD)$")
    note: str = Field("", max_length=500)


def _require_db() -> None:
    status = health_check()
    if not status["ok"]:
        raise HTTPException(503, detail={"error": "database_unavailable", "health": status,
                                         "recovery": "use the manual backup form (POST /fallback/manual)"})


@app.get("/health")
async def health():
    db = health_check()
    return {"ok": db["ok"], "database": db, "llm_model": config.OLLAMA_MODEL,
            "llm_available": await llm.is_available(), "npx_available": shutil.which("npx") is not None,
            "mode": "normal" if db["ok"] else "degraded_manual_fallback", "today": config.today().isoformat()}


@app.get("/households")
def households():
    _require_db()
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT household_id FROM plots ORDER BY household_id")]


@app.get("/farms")
def farms():
    """Farms with their (invented) farmer names, for pickers and labels."""
    _require_db()
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM plots ORDER BY household_id")]
    out = []
    for r in rows:
        c = sanitizer.scrub_plot(r)
        out.append({"household_id": r["household_id"], "farmer_name": r.get("farmer_name") or r["household_id"],
                    "zone_id": c.get("zone_id"), "crop": c.get("active_crop"), "cell_id": r.get("cell_id"),
                    "phone_type": r.get("phone_type"), "has_phone": bool(r.get("phone"))})
    return out


@app.post("/runs")
async def create_run(req: RunRequest):
    _require_db()
    try:
        return await start_run(app.state.graph, req.household_id, req.officer_note)
    except DatabaseUnavailable as exc:
        raise HTTPException(503, detail={"error": "database_unavailable", "detail": str(exc)[:200]})


@app.post("/wards/{zone_id}/runs")
async def run_ward(zone_id: str):
    """Draft advice for every household in a ward (a household cluster), one after another, and time it."""
    _require_db()
    zone = sanitizer.normalise_zone(zone_id)
    with connect() as conn:
        plots = [dict(r) for r in conn.execute("SELECT * FROM plots ORDER BY household_id")]
    members = [p["household_id"] for p in plots if sanitizer.scrub_plot(p).get("zone_id") == zone]
    if not members:
        raise HTTPException(404, detail=f"No households found in ward {zone_id!r}")
    started = time.perf_counter()
    results = []
    for hid in members:
        try:
            r = await start_run(app.state.graph, hid, f"Ward batch for {zone}")
            results.append({"household_id": hid, "run_id": r["run_id"], "status": r["advisory"].get("status"),
                            "verdict": r["advisory"].get("verdict"), "elapsed_s": r["elapsed_s"]})
        except Exception as exc:  # noqa: BLE001 - one bad household must not stop the ward
            results.append({"household_id": hid, "status": "ERROR", "error": str(exc)[:200]})
    total = round(time.perf_counter() - started, 1)
    telemetry.record(f"ward-{zone}-{int(time.time())}", "graph", "ward_batch", {"zone_id": zone, "households": members},
                     {"results": results, "total_s": total}, latency_ms=total * 1000)
    return {"zone_id": zone, "households": len(members), "total_s": total, "results": results}


@app.get("/advisories")
def advisories(status: str | None = Query(None, pattern="^(PENDING_REVIEW|SECURITY_LOCK|NEEDS_DATA|APPROVED|REJECTED)$")):
    _require_db()
    return approval.list_advisories(status)


@app.post("/advisories/{advisory_id}/approve")
async def approve(advisory_id: int, req: ApproveRequest):
    _require_db()
    try:
        result = approval.approve(advisory_id, req.officer_name, req.final_message, req.citation,
                                  req.final_message_sw, req.languages, req.call)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))
    result["graph"] = await resume_run(app.state.graph, result["run_id"], "APPROVED", result["officer"])
    return result


@app.post("/advisories/{advisory_id}/reject")
async def reject(advisory_id: int, req: RejectRequest):
    _require_db()
    try:
        result = approval.reject(advisory_id, req.officer_name, req.reason)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))
    result["graph"] = await resume_run(app.state.graph, result["run_id"], "REJECTED", result["officer"])
    return result


@app.get("/telemetry")
def telemetry_log(run_id: str | None = None, limit: int = Query(300, le=2000)):
    _require_db()
    with connect() as conn:
        q = "SELECT * FROM tool_calls" + (" WHERE run_id = ?" if run_id else "") + " ORDER BY id DESC LIMIT ?"
        rows = conn.execute(q, (run_id, limit) if run_id else (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/outbox")
def outbox():
    _require_db()
    return approval.outbox()


# --- Task 8: recovery loop. Works even when the database is corrupt. ------------------------------
@app.post("/fallback/manual")
def manual_fallback(entry: ManualEntry):
    try:
        officer = approval.validate_signature(entry.officer_name)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))
    note, hits = sanitizer.scrub_free_text(entry.note, 500)
    record = {"ts": telemetry.now_iso(), "officer": officer,
              "household_id": sanitizer.normalise_text(entry.household_id).upper(),
              "verdict": entry.verdict, "note": note, "injection_flag": bool(hits),
              "status": "MANUAL_PENDING_SYNC"}
    config.FALLBACK_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.FALLBACK_QUEUE_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


@app.get("/fallback/manual")
def manual_fallback_list():
    if not config.FALLBACK_QUEUE_PATH.exists():
        return []
    lines = config.FALLBACK_QUEUE_PATH.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# --- Overview: zones, alerts, households for the dashboard ------------------------------------------
@app.get("/overview")
def overview():
    _require_db()
    with connect() as conn:
        zones = [dict(r) for r in conn.execute("SELECT * FROM weather_cache ORDER BY zone_id")]
        alerts = [dict(r) for r in conn.execute("SELECT * FROM pest_alerts ORDER BY reported_at DESC")]
        plots = [dict(r) for r in conn.execute("SELECT * FROM plots ORDER BY household_id")]
    centroids = {z["zone_id"]: (z["centroid_lat"], z["centroid_lon"]) for z in zones}
    households = []
    for p in plots:
        c = sanitizer.scrub_plot(p)
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None and c.get("zone_id") in centroids:
            lat, lon = centroids[c["zone_id"]]
        households.append({"household_id": c.get("household_id"), "farmer_name": c.get("farmer_name"),
                           "zone_id": c.get("zone_id"), "lat": lat, "lon": lon,
                           "crop": c.get("active_crop"), "stage": c.get("growth_stage"),
                           "days": c.get("days_since_planting"), "flagged": c.get("injection_detected")})
    outlooks = [agronomy.rainfall_outlook(z) for z in zones]
    today = config.today()
    for a in alerts:
        # Map fields: how far the report reaches (action radius), its age, and whether it still counts.
        if a["lat"] is None and a["zone_id"] in centroids:
            a["lat"], a["lon"] = centroids[a["zone_id"]]
            a["placed_at"] = "ward centre"
        try:
            a["age_days"] = (today - date.fromisoformat(str(a["reported_at"])[:10])).days
        except ValueError:
            a["age_days"] = None
        a["action_radius_km"] = config.PEST_RADIUS_KM.get(a["pest"].lower(), config.DEFAULT_PEST_RADIUS_KM)
        a["active"] = bool(a["verified"]) and a["age_days"] is not None and 0 <= a["age_days"] <= config.PEST_MAX_AGE_DAYS
    return {"zones": [{**o, "lat": z["centroid_lat"], "lon": z["centroid_lon"],
                       "plant_now": agronomy.crops_plantable_now(o["rain_7d_mm"], o["washout_risk"]),
                       "pattern": weather_patterns.assess(z["zone_id"], o["rain_7d_mm"])}
                      for o, z in zip(outlooks, zones)],
            "alerts": alerts, "households": households, "today": config.today().isoformat()}


# --- Knowledge hub ---------------------------------------------------------------------------------
class SuitabilityRequest(BaseModel):
    season_rain_mm: float = Field(..., ge=0, le=3000)
    mean_temp_c: float = Field(..., ge=0, le=45)
    soil: str | None = Field(None, max_length=40)
    greenhouse: bool = False
    rain_7d_mm: float | None = Field(None, ge=0, le=1500)


@app.get("/knowledge")
def knowledge_topics():
    return knowledge.list_topics()


@app.get("/knowledge/crops")
def knowledge_crops():
    return knowledge.crops()


@app.get("/knowledge/season")
def knowledge_season():
    return knowledge.season_outlook()


@app.post("/knowledge/suitability")
def knowledge_suitability(req: SuitabilityRequest):
    return knowledge.suitability(req.season_rain_mm, req.mean_temp_c, req.soil, req.greenhouse, req.rain_7d_mm)


@app.get("/knowledge/spray-groups")
def spray_groups():
    """Mode-of-action groups a farmer can pick when logging a spray (the same list log_action validates)."""
    return config.CHEM_GROUPS


@app.get("/knowledge/terrain")
def terrain_options():
    return {"slopes": list(config.SLOPES), "soils": config.SOILS,
            "companions": sorted(agronomy.CEREALS | agronomy.LEGUMES)}


@app.get("/knowledge/problem")
def knowledge_problem(name: str = Query(..., max_length=60)):
    """What a pest, disease or weed is, how to fix it and prevent it: the message a farmer receives."""
    return {"name": name, "info": knowledge.problem_info(name), "farmer_message": knowledge.farmer_explainer(name)}


@app.get("/knowledge/{slug}")
def knowledge_topic(slug: str):
    text = knowledge.read_topic(slug)
    if text is None:
        raise HTTPException(404, detail="Unknown topic")
    return {"slug": slug, "markdown": text}


# --- Field scans (camera) ---------------------------------------------------------------------------
class ScanRequest(BaseModel):
    image_b64: str = Field(..., max_length=9_000_000)
    household_id: str | None = Field(None, max_length=32)
    crop: str | None = Field(None, max_length=40)


class ScanReview(BaseModel):
    officer_name: str = Field(..., max_length=80)
    decision: str = Field(..., pattern="^(VERIFIED|DISMISSED)$")
    pest: str | None = Field(None, max_length=60)
    severity: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH)$")
    note: str = Field("", max_length=1200)
    finding: str | None = Field(None, max_length=60)      # DISMISSED only: no problem / not a plant / field visit
    call: bool = False                                     # also phone the farmer with the result
    call_script: str | None = Field(None, max_length=600)  # what they will hear (officer-written or edited)
    call_language: str = Field("sw", pattern="^(en|sw)$")


class ScanBatchReview(BaseModel):
    scan_ids: list[int] = Field(..., min_length=2, max_length=50)
    officer_name: str = Field(..., max_length=80)
    pest: str = Field(..., max_length=60)
    severity: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH)$")
    note: str = Field("", max_length=1200)


@app.get("/scans/groups")
def scan_groups():
    _require_db()
    return fieldscan.review_groups()


@app.post("/scans/review-batch")
def review_scan_batch(req: ScanBatchReview):
    _require_db()
    try:
        return fieldscan.review_batch(req.scan_ids, req.officer_name, req.pest, req.severity, req.note)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


@app.post("/scans")
def create_scan(req: ScanRequest):
    _require_db()
    try:
        return fieldscan.analyse(req.image_b64, req.household_id, req.crop)
    except fieldscan.ScanError as exc:
        raise HTTPException(400, detail=str(exc))


@app.get("/scans")
def scans():
    _require_db()
    return fieldscan.list_scans()


@app.get("/scans/{scan_id}/image")
def scan_image(scan_id: int):
    data = fieldscan.image_bytes(scan_id)
    if data is None:
        raise HTTPException(404, detail="No image")
    return Response(content=data, media_type="image/png" if data[:4] == b"\x89PNG" else "image/jpeg")


@app.post("/scans/{scan_id}/review")
def review_scan(scan_id: int, req: ScanReview):
    _require_db()
    try:
        return fieldscan.review(scan_id, req.officer_name, req.decision, req.pest, req.severity, req.note,
                                req.finding, req.call, req.call_script, req.call_language)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


# --- Community board -------------------------------------------------------------------------------
class ForumPost(BaseModel):
    author: str = Field(..., max_length=40)
    topic: str = Field(..., max_length=40)
    body: str = Field(..., max_length=800)
    zone_id: str | None = Field(None, max_length=20)
    household_id: str | None = Field(None, max_length=32)


class ReportReview(BaseModel):
    officer_name: str = Field(..., max_length=80)
    decision: str = Field(..., pattern="^(CONFIRMED|NOT_CONFIRMED)$")
    pest: str | None = Field(None, max_length=60)
    severity: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH)$")
    zone_id: str | None = Field(None, max_length=20)
    note: str = Field("", max_length=400)


@app.get("/community/reports")
def community_reports():
    _require_db()
    return forum.pending_reports()


@app.post("/community/reports/{post_id}/review")
def review_community_report(post_id: int, req: ReportReview):
    _require_db()
    try:
        return forum.review_report(post_id, req.officer_name, req.decision, req.pest, req.severity, req.zone_id,
                                   req.note)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


class VoiceNote(BaseModel):
    audio_b64: str = Field(..., max_length=14_000_000)
    language: str | None = Field(None, pattern="^(en|sw)$")     # None = detect automatically


@app.get("/speech/status")
def speech_status():
    return {"available": speech.available(), "model": f"whisper-{speech.MODEL_SIZE}", "languages": speech.LANGUAGES}


@app.post("/speech/transcribe")
def speech_transcribe(req: VoiceNote):
    """A farmer's voice note as text (local Whisper). A draft only: the farmer checks it before saving."""
    try:
        audio = base64.b64decode(req.audio_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, detail="The recording could not be read.")
    try:
        return speech.transcribe(audio, req.language)
    except speech.SpeechUnavailable as exc:
        raise HTTPException(503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    except Exception as exc:                                   # undecodable audio from the browser, model errors
        raise HTTPException(400, detail=f"Could not turn the recording into text ({type(exc).__name__}).")


# --- Nyumba Kumi cells and voice calls ------------------------------------------------------------------------
@app.get("/cells")
def nyumba_cells():
    _require_db()
    return cells.list_cells()


@app.get("/farms/{household_id}/cell")
def farm_cell(household_id: str):
    """For the lead farmer: neighbours, their photo results (officer findings only) and visit requests."""
    _require_db()
    return cells.lead_view(household_id)


class NeighbourPhoto(BaseModel):
    neighbour_id: str = Field(..., max_length=32)
    image_b64: str = Field(..., max_length=9_000_000)


@app.post("/farms/{household_id}/cell/photos")
def cell_photo(household_id: str, req: NeighbourPhoto):
    """Lead farmer sends a photo for a neighbour in their cell. Receipt only, like the farmer's own upload."""
    _require_db()
    try:
        return cells.submit_for_neighbour(household_id, req.neighbour_id, req.image_b64)
    except approval.ApprovalError as exc:
        raise HTTPException(403, detail=str(exc))
    except fieldscan.ScanError as exc:
        raise HTTPException(400, detail=str(exc))


class Contact(BaseModel):
    officer_name: str = Field(..., max_length=80)
    phone: str | None = Field(None, max_length=20)
    phone_type: str | None = Field(None, pattern="^(smartphone|feature)$")
    cell_id: str | None = Field(None, max_length=16)


@app.post("/farms/{household_id}/contact")
def set_contact(household_id: str, req: Contact):
    _require_db()
    try:
        return cells.set_contact(household_id, req.officer_name, req.phone, req.phone_type, req.cell_id)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


@app.get("/integrations")
def integrations():
    """Which optional outside services are switched on (keys are never returned)."""
    return {"deepleaf": deepleaf.status(), "voice": voice_calls.status()}


@app.get("/voice/calls")
def calls(household_id: str | None = None):
    _require_db()
    return voice_calls.list_calls(household_id)


@app.post("/voice/calls/{call_id}/retry")
def retry_call(call_id: int):
    _require_db()
    try:
        return voice_calls.place(call_id)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


class SimulatedAnswer(BaseModel):
    answer: bool = True
    digit: str | None = Field(None, pattern="^[0-9]$")


@app.post("/voice/calls/{call_id}/simulate")
def simulate_call(call_id: int, req: SimulatedAnswer):
    """Demo: play the farmer's phone for a SIMULATED call (same handlers as the Africa's Talking webhooks)."""
    _require_db()
    try:
        return voice_calls.simulate(call_id, req.answer, req.digit)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


class InboundSms(BaseModel):
    household_id: str = Field(..., max_length=32)    # a real gateway maps the sender's phone number to this
    text: str = Field(..., max_length=480)


@app.post("/sms/inbound")
def sms_inbound(req: InboundSms):
    """A farmer's SMS command (simulated gateway): log field work, set a reminder or report a problem offline."""
    _require_db()
    try:
        return sms.receive(req.household_id, req.text)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


@app.get("/sms")
def sms_messages(household_id: str | None = None):
    _require_db()
    return sms.list_messages(household_id)


@app.get("/forum/topics")
def forum_topics():
    return forum.TOPICS


@app.get("/forum")
def forum_list(topic: str | None = None):
    _require_db()
    return forum.list_posts(topic)


@app.post("/forum")
def forum_post(req: ForumPost):
    _require_db()
    try:
        return forum.post(req.author, req.topic, req.body, req.zone_id, req.household_id)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


# --- Greenhouse check (VPD) -------------------------------------------------------------------------
class GreenhouseReading(BaseModel):
    greenhouse_id: str = Field("GH-1", max_length=40)
    temp_c: float = Field(..., ge=-5, le=60)
    rh_pct: float = Field(..., ge=0, le=100)
    device_id: str | None = Field(None, max_length=40)
    crop: str | None = Field(None, max_length=40)


@app.post("/greenhouse/assess")
def greenhouse_assess(req: GreenhouseReading):
    """Compute VPD and advice only; nothing is stored."""
    try:
        return greenhouse.assess(req.temp_c, req.rh_pct, req.crop)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


@app.post("/greenhouse/check")
def greenhouse_check(req: GreenhouseReading):
    """Typed readings: compute VPD and advice, and keep the reading in the greenhouse's history."""
    _require_db()
    try:
        return gh_readings.record(req.greenhouse_id, req.temp_c, req.rh_pct, "manual", None, req.crop)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


@app.post("/greenhouse/readings")
def greenhouse_sensor(req: GreenhouseReading):
    """Sensor endpoint: any device on the local network (e.g. ESP32 + DHT22) can POST readings here."""
    _require_db()
    try:
        return gh_readings.record(req.greenhouse_id, req.temp_c, req.rh_pct, "sensor", req.device_id, req.crop)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


@app.get("/greenhouse/readings")
def greenhouse_history(greenhouse_id: str | None = None, limit: int = Query(200, le=2000)):
    _require_db()
    return gh_readings.history(greenhouse_id, limit)


# --- Desk follow-ups (scheduled by the agent, closed by a named officer) ---------------------------------
class CloseFollowup(BaseModel):
    officer_name: str = Field(..., max_length=80)


@app.get("/followups")
def followups(status: str | None = Query("OPEN", pattern="^(OPEN|DONE)$")):
    _require_db()
    return desk_followups.list_followups(status)


@app.post("/followups/{followup_id}/done")
def close_followup(followup_id: int, req: CloseFollowup):
    _require_db()
    try:
        return desk_followups.close(followup_id, req.officer_name)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


# --- Household profile: plot history against the crop calendar -----------------------------------------
def _calendar(crop: str | None) -> list[dict]:
    stages, start = [], 0
    for upper, stage in config.CROP_STAGES.get(crop or "", []):
        end = min(upper, start + 60) if upper >= 10_000 else upper
        pests = sorted(p.title() for p, crops in config.PEST_SUSCEPTIBILITY.items() if stage in crops.get(crop, set()))
        stages.append({"stage": stage, "start_day": start, "end_day": end, "pests_to_watch": pests})
        start = upper + 1
    return stages


@app.get("/households/{household_id}/profile")
def household_profile(household_id: str):
    _require_db()
    hid = sanitizer.normalise_text(household_id).upper()[:32]
    with connect() as conn:
        row = conn.execute("SELECT * FROM plots WHERE upper(trim(household_id)) = ?", (hid,)).fetchone()
        weather = {r["zone_id"]: dict(r) for r in conn.execute("SELECT * FROM weather_cache")}
    if row is None:
        raise HTTPException(404, detail="Household not found")
    plot = sanitizer.scrub_plot(dict(row))
    crop = plot.get("active_crop")
    stages = _calendar(crop)
    # Every crop growing on the plot now, each with its own planting date, calendar and stage today.
    growing = history.crops_growing(plot, plot_actions.list_actions(row["household_id"]))
    calendars = {g["crop"]: {"stages": _calendar(g["crop"]), "stage_now": g["stage"], "days": g["days"],
                             "planted": g["planted"], "main": g["main"], "harvested": g.get("harvested")}
                 for g in growing}
    zone = plot.get("zone_id")
    rain = agronomy.rainfall_outlook(weather[zone]) if zone in weather else None
    advs = [a for a in approval.list_advisories() if a["household_id"].upper() == hid]
    return {"plot": plot, "rotation": history.rotation_for_plot(plot), "calendar": stages,
            "calendars": calendars, "growing": growing,
            "rain": rain, "pattern": weather_patterns.assess(zone, rain["rain_7d_mm"] if rain else None) if zone else None,
            "advisories": advs[:10],
            "followups": [f for f in desk_followups.list_followups(None) if f["household_id"].upper() == hid]}


# --- New forecast arrives (data feed or officer) --------------------------------------------------------
class ForecastUpdate(BaseModel):
    rain_24h_mm: float = Field(..., ge=0, le=500)
    rain_72h_mm: float = Field(..., ge=0, le=800)
    rain_7d_mm: float = Field(..., ge=0, le=1500)
    storm_risk: str = Field(..., pattern="^(LOW|MODERATE|HIGH)$")
    source: str = Field("Forecast update", max_length=80)
    peak_rain_mm_h: float | None = Field(None, ge=0, le=300)   # heaviest hour of rain (intensity)
    peak_rain_date: str | None = Field(None, max_length=10)     # past = observed, today or later = forecast
    dry_hours_ahead: float | None = Field(None, ge=0, le=240)   # hours until the next rain (spray rain-fastness)


@app.post("/weather/{zone_id}")
def update_forecast(zone_id: str, req: ForecastUpdate):
    """Record a newer forecast for a ward. Drafts built on the old one can no longer be signed until re-run."""
    _require_db()
    zone = sanitizer.normalise_zone(zone_id)
    issued = telemetry.now_iso()
    with connect() as conn:
        cur = conn.execute("UPDATE weather_cache SET rain_24h_mm=?, rain_72h_mm=?, rain_7d_mm=?, storm_risk=?, source=?,"
                           " issued_at=? WHERE zone_id=?", (req.rain_24h_mm, req.rain_72h_mm, req.rain_7d_mm,
                                                            req.storm_risk, sanitizer.normalise_text(req.source)[:80],
                                                            issued, zone))
        if cur.rowcount == 0:
            raise HTTPException(404, detail=f"Unknown ward {zone_id!r}")
        if req.dry_hours_ahead is not None:
            conn.execute("UPDATE weather_cache SET dry_hours_ahead=? WHERE zone_id=?", (req.dry_hours_ahead, zone))
        if req.peak_rain_mm_h is not None:
            peak_date = sanitizer.parse_date(req.peak_rain_date) if req.peak_rain_date else config.today()
            if peak_date is None:
                raise HTTPException(400, detail="peak_rain_date must be a date like 2026-10-16")
            conn.execute("UPDATE weather_cache SET peak_rain_mm_h=?, peak_rain_at=? WHERE zone_id=?",
                         (req.peak_rain_mm_h, peak_date.isoformat(), zone))
    telemetry.record(f"forecast-{zone}", "feed", "update_forecast", {"zone_id": zone, **req.model_dump()},
                     {"issued_at": issued}, latency_ms=0, actor="data feed")
    stale = [a["id"] for a in approval.list_advisories("PENDING_REVIEW") if a.get("forecast_changed")]
    return {"zone_id": zone, "issued_at": issued, "drafts_now_out_of_date": stale}


# --- Plot terrain (officer, from a field visit) ----------------------------------------------------------
class Terrain(BaseModel):
    slope: str = Field(..., max_length=20)
    soil: str = Field(..., max_length=20)
    intercrop: str | None = Field(None, max_length=40)    # companion crop in the same plot; None = grown alone
    officer_name: str = Field(..., min_length=5, max_length=80)


@app.post("/farms/{household_id}/terrain")
def set_terrain(household_id: str, req: Terrain):
    """Record a plot's slope, soil and companion crop. Planting advice uses them (how to plant on a slope,
    waterlogging on clay, intercrop layout)."""
    _require_db()
    hid = sanitizer.normalise_text(household_id).upper()[:32]
    slope, soil = req.slope.strip().lower(), req.soil.strip().lower()
    if slope not in config.SLOPES or soil not in config.SOILS:
        raise HTTPException(400, detail=f"Slope must be one of {list(config.SLOPES)}; soil one of {config.SOILS}")
    intercrop = sanitizer.normalise_crop(req.intercrop) if req.intercrop and req.intercrop.strip() else None
    if req.intercrop and req.intercrop.strip() and intercrop is None:
        raise HTTPException(400, detail=f"Companion crop {req.intercrop!r} not recognised")
    officer = sanitizer.normalise_text(req.officer_name)[:80]
    if len(officer) < 5:
        raise HTTPException(400, detail="A named officer must record the terrain")
    with connect() as conn:
        cur = conn.execute("UPDATE plots SET slope = ?, soil = ?, intercrop = ? WHERE upper(trim(household_id)) = ?",
                           (slope, soil, intercrop, hid))
        if cur.rowcount == 0:
            raise HTTPException(404, detail="Household not found")
    telemetry.record(f"terrain-{hid}", "officer", "set_terrain", {"household_id": hid, "slope": slope, "soil": soil,
                                                             "intercrop": intercrop}, {"ok": True}, latency_ms=0, actor=officer)
    return {"household_id": hid, "slope": slope, "soil": soil, "intercrop": intercrop}


# --- Plot history log ------------------------------------------------------------------------------------
class PlotAction(BaseModel):
    action: str = Field(..., max_length=20)
    action_date: str = Field(..., max_length=10)
    crop: str | None = Field(None, max_length=40)
    details: str = Field("", max_length=300)
    role: str = Field(..., pattern="^(officer|farmer)$")
    name: str | None = Field(None, max_length=80)
    chem_group: str | None = Field(None, max_length=60)
    needs_weeding: bool | None = None
    soil_moist: bool | None = None
    seed_check: str | None = Field(None, pattern="^(VERIFIED|FAILED|NOT_CHECKED)$")
    as_intercrop: bool = False          # PLANTING only: planted alongside the main crop


@app.get("/farms/{household_id}/actions")
def farm_actions(household_id: str):
    _require_db()
    return plot_actions.list_actions(household_id)


@app.post("/farms/{household_id}/actions")
def log_farm_action(household_id: str, req: PlotAction):
    _require_db()
    try:
        return plot_actions.log_action(household_id, req.action, req.action_date, req.crop, req.details,
                                       req.role, req.name, req.chem_group, req.needs_weeding, req.soil_moist,
                                       req.seed_check, req.as_intercrop)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


# --- Farmer reminders ------------------------------------------------------------------------------------
class ReminderRequest(BaseModel):
    due_date: str = Field(..., max_length=10)
    action: str = Field(..., max_length=20)
    note: str = Field("", max_length=200)


@app.get("/farms/{household_id}/reminders")
def reminders(household_id: str):
    _require_db()
    return farm_reminders.list_reminders(household_id)


@app.post("/farms/{household_id}/reminders")
def create_reminder(household_id: str, req: ReminderRequest):
    _require_db()
    try:
        return farm_reminders.create(household_id, req.due_date, req.action, req.note)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


@app.post("/reminders/{reminder_id}/done")
def reminder_done(reminder_id: int):
    _require_db()
    try:
        return farm_reminders.mark_done(reminder_id)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


# --- Every farm's plan (rule preview, no model) -----------------------------------------------------------
HARVEST_STAGES = {"MATURITY", "HARVEST_READY", "HARVEST", "POD_FILL_MATURITY", "TUBER_BULKING"}


@app.get("/farms/plan")
def farms_plan():
    """For every farm: what the safety rules say right now (plant / spray / hold / ready for harvest) and why,
    from its own plot history, crop stage, area rainfall and verified pests, plus its draft status. No model call."""
    _require_db()
    with connect() as conn:
        plots = [dict(r) for r in conn.execute("SELECT * FROM plots ORDER BY household_id")]
        zones = {r["zone_id"]: dict(r) for r in conn.execute("SELECT * FROM weather_cache")}
        alerts = [dict(r) for r in conn.execute("SELECT * FROM pest_alerts")]
        logs: dict[str, list[dict]] = {}
        for r in conn.execute("SELECT id, household_id, action, action_date, details, chem_group, needs_weeding, "
                              "soil_moist, seed_check FROM plot_actions"):
            logs.setdefault(r["household_id"], []).append(dict(r))
    advs = approval.list_advisories()
    out = []
    for row in plots:
        plot = sanitizer.scrub_plot(row)
        zone = zones.get(plot.get("zone_id"))
        if plot.get("lat") is None and zone:
            plot["lat"], plot["lon"] = zone["centroid_lat"], zone["centroid_lon"]
        rain = agronomy.rainfall_outlook(zone) if zone else None
        pests = agronomy.score_pest_alerts(alerts, plot.get("lat"), plot.get("lon"), plot.get("active_crop"),
                                           plot.get("growth_stage")) if plot.get("found") else None
        pat = weather_patterns.assess(zone["zone_id"], rain["rain_7d_mm"]) if zone and rain else {}
        decision = agronomy.decide(plot, rain, pests, pattern=pat, field_log=logs.get(row["household_id"], []))
        rot = history.rotation_for_plot(plot)
        plan = decision["verdict"] if decision["status"] == "PENDING_REVIEW" else decision["status"]
        if decision["verdict"] in (None, "HOLD") and plot.get("growth_stage") in HARVEST_STAGES \
                and decision["status"] == "PENDING_REVIEW":
            plan = "HARVEST"
        mine = [a for a in advs if a["household_id"] == row["household_id"]]
        latest = mine[0] if mine else None
        notes = [] if decision["status"] != "PENDING_REVIEW" else [n for n in (
            rot.get("sms_tip") if rot.get("risk") in ("ELEVATED", "HIGH") else None,
            "False-start risk: plant in two batches" if pat.get("onset") == "FALSE_START_RISK" and plan == "PLANT"
            else None,
            agronomy.intercrop_tip(plot, pat) if plot.get("growth_stage") == "PRE_PLANTING" else None) if n]
        out.append({"household_id": row["household_id"], "farmer_name": row.get("farmer_name"),
                    "zone_id": plot.get("zone_id"), "crop": plot.get("active_crop"),
                    "stage": plot.get("growth_stage"), "days": plot.get("days_since_planting"),
                    "plan": plan, "why": decision["reasons"][0] if decision["reasons"] else "",
                    "notes": notes, "rule": decision["rule"], "title": decision.get("title"),
                    "slope": plot.get("slope"), "soil": plot.get("soil"), "intercrop": plot.get("intercrop"),
                    "draft_status": latest["status"] if latest else None,
                    "advisory_id": latest["id"] if latest else None})
    return out


# --- Farmer side: photo submissions and notifications ---------------------------------------------------------
class FarmerPhoto(BaseModel):
    image_b64: str = Field(..., max_length=9_000_000)


@app.post("/farms/{household_id}/photos")
def farmer_submit_photo(household_id: str, req: FarmerPhoto):
    """Farmer upload. Returns a receipt only: the AI's suggestion goes to the officer, never to the farmer."""
    _require_db()
    with connect() as conn:
        if conn.execute("SELECT 1 FROM plots WHERE household_id = ?", (household_id,)).fetchone() is None:
            raise HTTPException(404, detail="Farm not found")
    try:
        return fieldscan.submit_for_review(req.image_b64, household_id)
    except fieldscan.ScanError as exc:
        raise HTTPException(400, detail=str(exc))


@app.get("/farms/{household_id}/photos")
def farmer_photos(household_id: str):
    _require_db()
    return fieldscan.farmer_view(household_id)


class LanguagePref(BaseModel):
    language: str = Field(..., pattern="^(en|sw|both)$")


@app.post("/farms/{household_id}/language")
def set_language(household_id: str, req: LanguagePref):
    """The farmer's preferred message language. The officer's send boxes start from it."""
    _require_db()
    hid = sanitizer.normalise_text(household_id).upper()[:32]
    with connect() as conn:
        if conn.execute("UPDATE plots SET language = ? WHERE upper(trim(household_id)) = ?",
                        (req.language, hid)).rowcount == 0:
            raise HTTPException(404, detail="Household not found")
    return {"household_id": hid, "language": req.language}


@app.get("/farms/{household_id}/notifications")
def farmer_notifications(household_id: str, seen: bool = False):
    """Everything an officer has sent this farmer, newest first: signed advice and photo results.
    Plus the farmer's own reminders that are due. Never drafts or AI output. `seen` = the farmer opened the app."""
    _require_db()
    if seen:
        with connect() as conn:
            conn.execute("UPDATE plots SET farmer_last_seen = ? WHERE household_id = ?",
                         (telemetry.now_iso(), household_id))
    items = []
    advs = {a["id"]: a for a in approval.list_advisories("APPROVED")}
    sent: dict[int, list[dict]] = {}
    for o in approval.outbox():
        if o["household_id"] == household_id:
            sent.setdefault(o["advisory_id"], []).append(o)
    for advisory_id, rows in sent.items():
        rows.sort(key=lambda o: approval.LANGUAGES.index(o.get("language") or "en"))
        adv = advs.get(advisory_id) or {}
        threat = (adv.get("evidence") or {}).get("pest_threat") or {}
        steps = knowledge.advice_steps(adv.get("verdict"), threat.get("pest"))
        info = knowledge.problem_info(threat.get("pest")) or {}
        # Only the language(s) the officer signed; both carry the same signature.
        messages = [{"language": o.get("language") or "en", "text": o["message"]} for o in rows]
        items.append({"when": rows[0]["queued_at"], "kind": "advice", "title": "Advice from your extension officer",
                      "body": messages[0]["text"], "messages": messages, "from": rows[0]["officer_signature"],
                      "steps": steps, "what": info.get("what")})
    for sc in fieldscan.farmer_view(household_id):
        if not sc["waiting"]:
            body = sc["officer_note"] or f"Result: {sc['officer_finding']}."
            items.append({"when": sc["reviewed_at"], "kind": "photo",
                          "title": f"Your photo #{sc['id']}: {sc['officer_finding']}",
                          "body": body, "from": sc["reviewed_by"]})
    today = config.today().isoformat()
    for r in farm_reminders.list_reminders(household_id):
        if not r["done"] and r["due_date"] <= today:
            items.append({"when": r["due_date"], "kind": "reminder", "title": "Reminder due",
                          "body": f"{r['action'].title()}" + (f": {r['note']}" if r["note"] else ""), "from": "you"})
    return sorted(items, key=lambda x: x["when"] or "", reverse=True)


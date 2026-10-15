"""REST API: the only door between the frontend and the backend.

Run:  uvicorn crop_pilot.api.main:app --port 8000   (with PYTHONPATH=backend)
"""
from __future__ import annotations

import json
import shutil
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Response
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from crop_pilot import config
from crop_pilot.agent import llm
from crop_pilot.agent.workflow import build_graph, resume_run, start_run
from crop_pilot.community import forum
from crop_pilot.core import agronomy, greenhouse, knowledge, sanitizer, telemetry
from crop_pilot.database.db import DatabaseUnavailable, connect, health_check
from crop_pilot.dispatch import approval
from crop_pilot.fieldscan import service as fieldscan
from crop_pilot.greenhouse import readings as gh_readings


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(config.CHECKPOINT_DB_PATH)) as saver:
        app.state.graph = build_graph(saver)
        yield


app = FastAPI(title="Crop-Pilot Extension Co-Pilot API", version="1.0.0", lifespan=lifespan)


class RunRequest(BaseModel):
    household_id: str = Field(..., max_length=32)
    officer_note: str = Field("", max_length=300)


class ApproveRequest(BaseModel):
    officer_name: str = Field(..., max_length=80)
    final_message: str | None = Field(None, max_length=320)


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
            "mode": "normal" if db["ok"] else "degraded_manual_fallback"}


@app.get("/households")
def households():
    _require_db()
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT household_id FROM plots ORDER BY household_id")]


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
        result = approval.approve(advisory_id, req.officer_name, req.final_message)
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
        households.append({"household_id": c.get("household_id"), "zone_id": c.get("zone_id"), "lat": lat, "lon": lon,
                           "crop": c.get("active_crop"), "stage": c.get("growth_stage"),
                           "days": c.get("days_since_planting"), "flagged": c.get("injection_detected")})
    return {"zones": [{**agronomy.rainfall_outlook(z), "lat": z["centroid_lat"], "lon": z["centroid_lon"]} for z in zones],
            "alerts": alerts, "households": households, "today": config.today().isoformat()}


# --- Knowledge hub ---------------------------------------------------------------------------------
class SuitabilityRequest(BaseModel):
    season_rain_mm: float = Field(..., ge=0, le=3000)
    mean_temp_c: float = Field(..., ge=0, le=45)
    soil: str | None = Field(None, max_length=40)
    greenhouse: bool = False


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
    return knowledge.suitability(req.season_rain_mm, req.mean_temp_c, req.soil, req.greenhouse)


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
        return fieldscan.review(scan_id, req.officer_name, req.decision, req.pest, req.severity)
    except approval.ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


# --- Community board -------------------------------------------------------------------------------
class ForumPost(BaseModel):
    author: str = Field(..., max_length=40)
    topic: str = Field(..., max_length=40)
    body: str = Field(..., max_length=800)


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
        return forum.post(req.author, req.topic, req.body)
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

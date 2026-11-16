"""Plant AI orchestration API (FastAPI, CORS on) for the frontend.

It connects two MCP servers over stdio and keeps them open for the life of the app:
* plant-ai (ours, mcp_server.py): diagnose_crop_leaf, check_regional_outbreak, draft_extension_advisory
* weather (external, open source): open-meteo-mcp-server, pinned to a release, keyless (Open-Meteo)

Flow for POST /api/diagnose (agent.py): Plan -> Execute -> Self-check -> Recover, and it says when it doesn't know:
    diagnose_crop_leaf -> check_regional_outbreak -> weather (Open-Meteo + Visual Crossing, cross-checked)
    -> draft_extension_advisory -> self-check -> recover / admit uncertainty
    -> an unsure case is queued for an officer; a regional SPIKE creates an outbreak alert as PENDING_APPROVAL.
Weather: Open-Meteo through the external MCP server (direct API if that server is down) and Visual Crossing
(VISUAL_CROSSING_API_KEY), each retried, failing over to the other and then to a cached forecast.
Human in the loop: an alert is dispatched only after a named officer approves it (POST /api/alerts/{id}/approve).
Nothing in the pipeline can approve or dispatch; the database refuses an approved/dispatched row without a name.

Run:  cd backend/plant_ai && ../../.venv-plantai/bin/uvicorn agent_api:app --port 8010
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shlex
import shutil
import sqlite3
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic import BaseModel, Field

import agent
import mcp_server as plant
import weather as wx

HERE = Path(__file__).resolve().parent
log = logging.getLogger("plant_ai.api")
WEATHER_MCP_PACKAGE = "open-meteo-mcp-server@2.5.6"    # github.com/cmer81/open-meteo-mcp (MIT), published 2026-10-31
WEATHER_MCP_COMMAND = os.environ.get("WEATHER_MCP_COMMAND", "")   # override, e.g. "node /path/to/dist/index.js"
CORS_ORIGINS = [o.strip() for o in os.environ.get("PLANT_AI_CORS_ORIGINS", "*").split(",") if o.strip()]
OFFICER_RE = re.compile(r"^[A-Za-z][A-Za-z'\-.]+(?: [A-Za-z][A-Za-z'\-.]+)+$")
TOOL_TIMEOUT_S = 60


# --- MCP connections ----------------------------------------------------------------------------------------------
class Hub:
    """Both MCP clients, opened once. A server that fails to start is recorded and the API degrades around it."""

    def __init__(self):
        self.plant: Client | None = None
        self.weather: Client | None = None
        self.weather_tool: str | None = None
        self.weather_params: set[str] = set()
        self.status: dict[str, Any] = {}
        self._stack = AsyncExitStack()

    async def start(self, plant_client: Client | None = None, weather_client: Client | None = None) -> None:
        env = dict(os.environ, PYTHONPATH=str(HERE) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        plant_client = plant_client or Client(StdioTransport(command=sys.executable, args=[str(HERE / "mcp_server.py")],
                                                             env=env, cwd=str(HERE)))
        try:
            self.plant = await self._stack.enter_async_context(plant_client)
            self.status["plant_ai"] = {"ok": True, "tools": sorted(t.name for t in await self.plant.list_tools())}
        except Exception as exc:  # noqa: BLE001
            self.plant, self.status["plant_ai"] = None, {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        if weather_client is None:
            cmd = shlex.split(WEATHER_MCP_COMMAND) if WEATHER_MCP_COMMAND else (
                [shutil.which("npx"), "-y", WEATHER_MCP_PACKAGE] if shutil.which("npx") else None)
            if cmd is None:
                self.status["weather"] = {"ok": False, "error": "npx not found (install Node.js) and "
                                                                "WEATHER_MCP_COMMAND not set"}
                return
            weather_client = Client(StdioTransport(command=cmd[0], args=cmd[1:], env=dict(os.environ)))
        try:
            self.weather = await self._stack.enter_async_context(weather_client)
            tools = await self.weather.list_tools()
            # Prefer the general forecast tool; the package also exposes model-specific and marine tools.
            pick = next((t for t in tools if t.name == "weather_forecast"), None) or \
                next((t for t in tools if "forecast" in t.name), None)
            self.weather_tool = pick.name if pick else None
            self.weather_params = set((getattr(pick, "input_schema", None) or getattr(pick, "inputSchema", None) or {}).get("properties", {})) if pick else set()
            self.status["weather"] = {"ok": pick is not None, "server": WEATHER_MCP_PACKAGE, "tool": self.weather_tool,
                                      "tools": sorted(t.name for t in tools)}
        except Exception as exc:  # noqa: BLE001
            self.weather, self.status["weather"] = None, {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}

    async def stop(self) -> None:
        await self._stack.aclose()


hub = Hub()


def _data(result) -> Any:
    """A tool result as plain JSON, whichever way the server returned it."""
    if getattr(result, "structured_content", None):
        sc = result.structured_content
        return sc["result"] if set(sc) == {"result"} else sc
    if getattr(result, "data", None) is not None:
        return result.data
    text = "".join(getattr(c, "text", "") for c in result.content or [])
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


async def call_plant(tool: str, args: dict) -> dict:
    if hub.plant is None:
        raise HTTPException(503, detail={"error": "plant_ai_mcp_unavailable", "status": hub.status.get("plant_ai")})
    started = time.perf_counter()
    try:
        out = _data(await hub.plant.call_tool(tool, args, timeout=TOOL_TIMEOUT_S, raise_on_error=False))
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    if isinstance(out, dict):
        out["_ms"] = round((time.perf_counter() - started) * 1000)
    return out


async def open_meteo_via_mcp(lat: float, lon: float) -> list[dict]:
    """Open-Meteo through the external MCP server; straight from the Open-Meteo API if that server is not up."""
    if hub.weather is None or not hub.weather_tool:
        return await wx.open_meteo_http(lat, lon)
    wanted = {"latitude": lat, "longitude": lon, "hourly": ["precipitation", "precipitation_probability",
                                                            "relative_humidity_2m", "wind_speed_10m"],
              "forecast_days": 3, "timezone": "Africa/Nairobi"}
    args = {k: v for k, v in wanted.items() if not hub.weather_params or k in hub.weather_params}
    try:
        raw = _data(await hub.weather.call_tool(hub.weather_tool, args, timeout=TOOL_TIMEOUT_S, raise_on_error=False))
        return wx.hours_from_open_meteo(raw)
    except Exception:  # noqa: BLE001 - MCP server fault: same data, straight from the API
        return await wx.open_meteo_http(lat, lon)


def weather_providers() -> dict:
    custom = getattr(app.state, "weather_providers", None)     # tests inject fakes here
    if custom:
        return custom
    providers = {wx.OPEN_METEO: open_meteo_via_mcp}
    if wx.visual_crossing_key():
        providers[wx.VISUAL_CROSSING] = wx.visual_crossing_http
    return providers


async def forecast(lat: float, lon: float) -> dict:
    with plant.db() as conn:
        out = await wx.dual_forecast(lat, lon, weather_providers(), conn)
    out["source"] = " + ".join(out.get("sources") or {}) or "none"
    if not wx.visual_crossing_key() and not getattr(app.state, "weather_providers", None):
        out["note"] = "Visual Crossing is off (no VISUAL_CROSSING_API_KEY): forecasts are not cross-checked."
    return out


# --- app ----------------------------------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    with plant.db():
        pass                                              # create tables before the first request
    _ensure_outbox()
    # Tests (or another host) can hand in ready-made MCP clients via app.state.mcp_clients.
    global hub
    hub = Hub()
    await hub.start(**(getattr(app.state, "mcp_clients", None) or {}))
    yield
    await hub.stop()


app = FastAPI(title="Plant AI Agent API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["*"])

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id    INTEGER NOT NULL REFERENCES outbreak_alerts(id),
    region      TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'SMS_SIMULATED',
    message     TEXT NOT NULL,
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) >= 5),
    queued_at   TEXT NOT NULL
);
"""


def _ensure_outbox() -> None:
    with plant.db() as conn:
        conn.executescript(OUTBOX_SCHEMA)


class DiagnoseRequest(BaseModel):
    image_base64: str = Field(..., max_length=12_000_000)
    region: str = Field(..., min_length=2, max_length=80, description="county / sub-county / ward")
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    crop: str | None = Field(None, max_length=40)


@app.get("/api/health")
def health():
    model_ok = plant.MODEL_PATH.exists()
    return {"ok": bool((hub.status.get("plant_ai") or {}).get("ok")) and model_ok, "model_file": model_ok,
            "mcp": hub.status, "confidence_threshold": plant.CONFIDENCE_MIN}


async def run_pipeline(req: DiagnoseRequest) -> dict:
    run_id = f"dx-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex()}"
    result = await agent.run_diagnosis(req, call_plant, forecast, run_id)
    if result["answer_status"] == "FAILED":
        raise HTTPException(503 if not result["fixable_by_user"] else 400,
                            detail={k: result[k] for k in ("message", "error", "plan", "trace", "recovery")})
    dx, outbreak = result["diagnosis"], result["outbreak"]
    alert = None
    if outbreak.get("spike") and dx["confident"]:
        alert = create_alert(req.region, dx, outbreak, result["weather"], result["advisory"])
        result["trace"].append({"step": len(result["trace"]) + 1, "tool": "HUMAN_GATE", "ok": True, "ms": None,
                                "note": f"alert #{alert['id']} waits for a named officer; nothing was sent"})
        for p in result["plan"]:
            if p["id"] == "human_gate":
                p["status"], p["note"] = "waiting", f"outbreak alert #{alert['id']} needs a named officer"
    elif not result["review_request"]:
        for p in result["plan"]:
            if p["id"] == "human_gate":
                p["status"] = "not_needed"
    result["alert"] = alert
    result["human_review_required"] = bool(alert) or result["answer_status"] == "UNCERTAIN"
    return result


@app.post("/api/diagnose")
async def diagnose(req: DiagnoseRequest):
    """Leaf photo (base64) + region (+ GPS) -> diagnosis, outbreak check, weather, draft advice, maybe an alert."""
    return await run_pipeline(req)


@app.post("/api/diagnose/upload")
async def diagnose_upload(image: UploadFile = File(...), region: str = Form(...), lat: float | None = Form(None),
                          lon: float | None = Form(None), crop: str | None = Form(None)):
    """Same as /api/diagnose, as a multipart form (field `image`)."""
    raw = await image.read(plant.MAX_IMAGE_BYTES + 1)
    if len(raw) > plant.MAX_IMAGE_BYTES:
        raise HTTPException(413, detail="image larger than 8 MB")
    return await run_pipeline(DiagnoseRequest(image_base64=base64.b64encode(raw).decode(), region=region, lat=lat,
                                              lon=lon, crop=crop))


@app.get("/api/weather")
async def weather(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    return await forecast(lat, lon)


@app.get("/api/outbreaks")
async def outbreaks(region: str | None = Query(None, max_length=80), days: int = Query(7, ge=1, le=90)):
    """Case counts per region and disease over the last `days` days."""
    since = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat()
    q = ("SELECT region, disease, COUNT(*) AS cases, MAX(reported_at) AS last_case FROM cases WHERE reported_at >= ?"
         + (" AND region = ?" if region else "") + " GROUP BY region, disease ORDER BY cases DESC")
    with plant.db() as conn:
        rows = [dict(r) for r in conn.execute(q, (since, plant._norm(region)) if region else (since,))]
    return {"days": days, "regions": rows}


# --- human-in-the-loop alerts ------------------------------------------------------------------------------------
def _alert(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["evidence"] = json.loads(d["evidence"] or "{}")
    return d


def create_alert(region: str, dx: dict, outbreak: dict, weather: dict, advisory: dict) -> dict:
    disease = dx["label"].replace("__", " ").replace("_", " ")
    message = (f"Outbreak alert ({region}): {outbreak['cases_last_7d']} cases of {disease} in the last 7 days. "
               f"Scout your {dx['crop'].replace('_', ' ')} now and report signs to your extension officer.")
    evidence = {"diagnosis": {k: dx.get(k) for k in ("label", "confidence", "predictions", "image_quality")},
                "outbreak": outbreak, "weather": weather.get("summary"), "weather_source": weather.get("source"),
                "advisory": advisory.get("message")}
    with plant.db() as conn:
        # One open alert per region and disease: a new spike updates the evidence instead of piling up alerts.
        open_row = conn.execute("SELECT id FROM outbreak_alerts WHERE region=? AND disease=? AND "
                                "status='PENDING_APPROVAL'", (plant._norm(region), dx["label"])).fetchone()
        if open_row:
            conn.execute("UPDATE outbreak_alerts SET message=?, evidence=? WHERE id=?",
                         (message, json.dumps(evidence), open_row["id"]))
            alert_id = open_row["id"]
        else:
            alert_id = conn.execute("INSERT INTO outbreak_alerts (region, disease, message, evidence, created_at) "
                                    "VALUES (?,?,?,?,?)", (plant._norm(region), dx["label"], message,
                                                           json.dumps(evidence), plant.now_iso())).lastrowid
        return _alert(conn.execute("SELECT * FROM outbreak_alerts WHERE id=?", (alert_id,)).fetchone())


class Decision(BaseModel):
    officer_name: str = Field(..., max_length=80)
    note: str = Field("", max_length=500)
    message: str | None = Field(None, max_length=320, description="optional edited alert text")


def _officer(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip()
    if not (5 <= len(name) <= 80) or not OFFICER_RE.match(name):
        raise HTTPException(400, detail="Sign with your full name (first and last name, letters only).")
    return name


@app.get("/api/alerts")
def alerts(status: str | None = Query(None, pattern="^(PENDING_APPROVAL|APPROVED|REJECTED|DISPATCHED)$")):
    q = "SELECT * FROM outbreak_alerts" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT 200"
    with plant.db() as conn:
        return [_alert(r) for r in conn.execute(q, (status,) if status else ())]


@app.get("/api/alerts/{alert_id}")
def alert(alert_id: int):
    with plant.db() as conn:
        row = _alert(conn.execute("SELECT * FROM outbreak_alerts WHERE id=?", (alert_id,)).fetchone())
        if row:
            row["outbox"] = [dict(r) for r in conn.execute("SELECT * FROM alert_outbox WHERE alert_id=?", (alert_id,))]
    if row is None:
        raise HTTPException(404, detail="Alert not found.")
    return row


@app.post("/api/alerts/{alert_id}/approve")
def approve_alert(alert_id: int, d: Decision):
    """The human gate. A named officer approves; only then is the alert dispatched (simulated SMS outbox)."""
    officer = _officer(d.officer_name)
    with plant.db() as conn:
        row = conn.execute("SELECT * FROM outbreak_alerts WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            raise HTTPException(404, detail="Alert not found.")
        if row["status"] != "PENDING_APPROVAL":
            raise HTTPException(409, detail=f"Alert is already {row['status']}.")
        message = re.sub(r"\s+", " ", d.message).strip() if d.message else row["message"]
        now = plant.now_iso()
        conn.execute("UPDATE outbreak_alerts SET status='APPROVED', decided_by=?, decided_at=?, decision_note=?, "
                     "message=? WHERE id=?", (officer, now, d.note.strip(), message, alert_id))
        # Dispatch happens only here, after the approval above, in the same transaction.
        conn.execute("INSERT INTO alert_outbox (alert_id, region, message, approved_by, queued_at) VALUES (?,?,?,?,?)",
                     (alert_id, row["region"], message, officer, now))
        conn.execute("UPDATE outbreak_alerts SET status='DISPATCHED', dispatched_at=?, recipients=? WHERE id=?",
                     (now, 1, alert_id))
    return alert(alert_id)


@app.post("/api/alerts/{alert_id}/reject")
def reject_alert(alert_id: int, d: Decision):
    officer = _officer(d.officer_name)
    with plant.db() as conn:
        row = conn.execute("SELECT status FROM outbreak_alerts WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            raise HTTPException(404, detail="Alert not found.")
        if row["status"] != "PENDING_APPROVAL":
            raise HTTPException(409, detail=f"Alert is already {row['status']}.")
        conn.execute("UPDATE outbreak_alerts SET status='REJECTED', decided_by=?, decided_at=?, decision_note=? "
                     "WHERE id=?", (officer, plant.now_iso(), d.note.strip(), alert_id))
    return alert(alert_id)


# --- cases the agent was unsure about ------------------------------------------------------------------------------
class Review(BaseModel):
    officer_name: str = Field(..., max_length=80)
    diagnosis: str = Field(..., min_length=3, max_length=500)


@app.get("/api/reviews")
def reviews(status: str | None = Query("OPEN", pattern="^(OPEN|DONE)$")):
    """Cases where the agent said "I'm not sure" and asked an extension officer."""
    with plant.db() as conn:
        conn.executescript(agent.SCHEMA)
        rows = [dict(r) for r in conn.execute("SELECT * FROM review_requests" + (" WHERE status = ?" if status else "")
                                              + " ORDER BY id DESC LIMIT 200", (status,) if status else ())]
    for r in rows:
        r["reasons"] = json.loads(r["reasons"] or "[]")
    return rows


@app.post("/api/reviews/{review_id}/resolve")
def resolve_review(review_id: int, r: Review):
    officer = _officer(r.officer_name)
    with plant.db() as conn:
        conn.executescript(agent.SCHEMA)
        row = conn.execute("SELECT status FROM review_requests WHERE id=?", (review_id,)).fetchone()
        if row is None:
            raise HTTPException(404, detail="Review request not found.")
        if row["status"] != "OPEN":
            raise HTTPException(409, detail="Already reviewed.")
        conn.execute("UPDATE review_requests SET status='DONE', reviewed_by=?, diagnosis=? WHERE id=?",
                     (officer, r.diagnosis.strip(), review_id))
    return {"id": review_id, "status": "DONE", "reviewed_by": officer}


@app.get("/api/recovery")
def recovery(run_id: str | None = Query(None, max_length=60), limit: int = Query(100, le=1000)):
    """The self-check audit log: every failure the agent recovered from, how, and what it used instead."""
    with plant.db() as conn:
        conn.executescript(agent.SCHEMA)
        q = "SELECT * FROM recovery_log" + (" WHERE run_id = ?" if run_id else "") + " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in conn.execute(q, (run_id, limit) if run_id else (limit,))]

"""REST API: the only door between the frontend and the backend.

Run:  uvicorn crop_pilot.api.main:app --port 8000   (with PYTHONPATH=backend)
"""
from __future__ import annotations

import json
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from crop_pilot import config
from crop_pilot.agent import llm
from crop_pilot.agent.workflow import build_graph, resume_run, start_run
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import DatabaseUnavailable, connect, health_check
from crop_pilot.dispatch import approval


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

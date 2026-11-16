"""Dual-weather cross-verification and failover, and the Plan -> Execute -> Self-Verify -> Recover loop."""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

NOW = datetime(2026, 10, 15, 6, 0)


def _hours(rain_at=None, mm=0.0, prob=10, wind=8.0, humidity=70):
    """168 hourly rows from NOW; `rain_at` = hour offsets that get `mm` of rain."""
    rain_at = set(rain_at or [])
    return [{"time": (NOW + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"), "precip_mm": mm if i in rain_at else 0.0,
             "prob": prob, "humidity": humidity, "wind_kmh": wind} for i in range(168)]


@pytest.fixture()
def live(monkeypatch, temp_db):
    from crop_pilot import config
    monkeypatch.setattr(config, "LIVE_WEATHER", True)
    monkeypatch.setattr(config, "WEATHER_RETRIES", 2)
    monkeypatch.setattr("crop_pilot.core.resilience.time.sleep", lambda s: None)
    return temp_db


def _recoveries(db, run_id):
    return [dict(zip(("component", "action", "source"), r)) for r in sqlite3.connect(db).execute(
        "SELECT component, recovery_action, degraded_source FROM recovery_log WHERE run_id=? ORDER BY id", (run_id,))]


# --- dual weather ---------------------------------------------------------------------------------------------------
def test_forecasts_that_agree_are_cross_verified(live):
    from crop_pilot.core import weather_sources as ws
    out = ws.dual_forecast("RIRUTA", run_id="w1", now=NOW, fetchers={
        ws.PRIMARY: lambda lat, lon: _hours(rain_at=[30], mm=2.0),
        ws.SECONDARY: lambda lat, lon: (_hours(rain_at=[31], mm=2.5), [])})
    assert out["agreement"] == "AGREE" and out["cross_verified"] and not out["degraded"]
    assert out["consensus"]["dry_hours_ahead"] == 30 and out["consensus"]["spray_window_ok"]
    assert out["citation"].startswith("live_weather:RIRUTA@")
    assert _recoveries(live, "w1") == []


def test_forecasts_that_disagree_on_spray_window_are_flagged(live):
    from crop_pilot.core import weather_sources as ws
    out = ws.dual_forecast("RIRUTA", run_id="w2", now=NOW, fetchers={
        ws.PRIMARY: lambda lat, lon: _hours(rain_at=[2, 3, 4], mm=8.0, prob=90),
        ws.SECONDARY: lambda lat, lon: (_hours(), [])})
    assert out["agreement"] == "DISAGREE" and not out["cross_verified"]
    assert any("spray window" in d for d in out["disagreements"])
    assert any("72-hour rain" in d for d in out["disagreements"])
    assert out["consensus"]["spray_window_ok"] is False        # the cautious reading wins


def test_primary_timeout_is_retried_then_fails_over(live):
    from crop_pilot.core import weather_sources as ws
    calls = {"n": 0}

    def flaky(lat, lon):
        calls["n"] += 1
        raise httpx.ConnectTimeout("Open-Meteo timed out")
    out = ws.dual_forecast("RIRUTA", run_id="w3", now=NOW, fetchers={
        ws.PRIMARY: flaky, ws.SECONDARY: lambda lat, lon: (_hours(), [{"event": "x", "headline": "y"}])})
    assert calls["n"] == 2                                      # retried before failing over
    assert out["agreement"] == "SINGLE_SOURCE" and out["degraded_source"] == "Visual Crossing only"
    assert _recoveries(live, "w3") == [{"component": "open_meteo", "action": "failover:visual_crossing",
                                        "source": "Visual Crossing"}]


def test_a_retry_that_works_is_logged(live):
    from crop_pilot.core import weather_sources as ws
    state = {"n": 0}

    def once_flaky(lat, lon):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ReadTimeout("slow")
        return _hours()
    out = ws.dual_forecast("RIRUTA", run_id="w4", now=NOW, fetchers={
        ws.PRIMARY: once_flaky, ws.SECONDARY: lambda lat, lon: (_hours(), [])})
    assert out["agreement"] == "AGREE"
    assert _recoveries(live, "w4")[0]["action"] == "retried"


def test_both_down_uses_cached_live_then_climate_baseline(live):
    from crop_pilot.core import weather_sources as ws

    def down(lat, lon):
        raise httpx.ConnectError("offline")
    out = ws.dual_forecast("MUTUINI", run_id="w5", now=NOW, fetchers={ws.PRIMARY: down, ws.SECONDARY: down})
    assert out["agreement"] == "BASELINE_ONLY" and out["degraded_source"] == "cached sub-county climate baseline"
    assert out["citation"].startswith("weather_cache:MUTUINI@") and out["consensus"]["rain_7d_mm"] == 18.0
    assert _recoveries(live, "w5")[-1]["action"] == "fallback:baseline"

    ws.dual_forecast("MUTUINI", run_id="w6", now=NOW, fetchers={ws.PRIMARY: lambda a, b: _hours(),
                                                                ws.SECONDARY: down})
    out = ws.dual_forecast("MUTUINI", run_id="w7", now=NOW, fetchers={ws.PRIMARY: down, ws.SECONDARY: down})
    assert out["agreement"] == "SINGLE_SOURCE" and out["degraded_source"].startswith("cached live forecast")
    assert _recoveries(live, "w7")[-1]["action"] == "fallback:forecast_cache"


def test_offline_mode_uses_baseline_without_network(temp_db):
    from crop_pilot.core import weather_sources as ws
    out = ws.dual_forecast("RIRUTA", run_id="w8")
    assert out["agreement"] == "BASELINE_ONLY" and "switched off" in out["provider_errors"]["Open-Meteo"]


def test_severe_alerts():
    from crop_pilot.core import weather_sources as ws
    s = ws.summarise(_hours(rain_at=range(0, 12), mm=5.0, wind=45, humidity=95), now=NOW)
    events = {a["event"] for a in s["alerts"]}
    assert {"WASHOUT_RISK", "HEAVY_RAIN", "DAMAGING_WIND", "DISEASE_WEATHER"} <= events


# --- self-verify: admitting uncertainty -----------------------------------------------------------------------------
def test_uncertainty_rules():
    from crop_pilot.agent.workflow import assess_uncertainty
    leaf = {"found": True, "scan_id": 7, "vision_available": True, "confidence": 0.6, "image_issues": [],
            "candidates": [{"pest": "late blight", "score": 0.6}]}
    codes = lambda d, e: [u["code"] for u in assess_uncertainty(d, e)]   # noqa: E731
    assert codes({"verdict": "HOLD"}, {"leaf": leaf}) == ["low_confidence"]
    assert codes({"verdict": "HOLD"}, {"leaf": dict(leaf, confidence=0.9)}) == []
    assert codes({"verdict": "HOLD"}, {"leaf": dict(leaf, confidence=0.9, image_issues=["blurry"])}) == ["photo_quality"]
    disagree = {"agreement": "DISAGREE", "disagreements": ["spray window: open vs closed"]}
    assert codes({"verdict": "SPRAY"}, {"live_weather": disagree}) == ["weather_disagreement"]
    assert codes({"verdict": "HOLD"}, {"live_weather": disagree}) == []          # only sprays need the cross-check
    closed = {"agreement": "AGREE", "consensus": {"spray_window_ok": False}}
    assert codes({"verdict": "SPRAY"}, {"live_weather": closed}) == ["live_forecast_closes_spray_window"]


def _scan(db, hid, quality, candidates, model="moondream"):
    from crop_pilot.database.db import connect
    from crop_pilot.fieldscan import service
    with connect() as conn:
        service._ensure(conn)
        return conn.execute("INSERT INTO field_scans (household_id, crop, image_file, model, description, "
                            "candidates_json, created_at, image_quality) VALUES (?,?,?,?,?,?,?,?)",
                            (hid, "Maize", "x.jpg", model, "leaf", json.dumps(candidates), "2026-10-14T09:00:00",
                             json.dumps(quality))).lastrowid


def test_leaf_scan_tool_reports_quality_and_confidence(temp_db):
    from crop_pilot.mcp_server import server
    assert server.get_leaf_scan("HH-DS-003")["found"] is False
    sid = _scan(temp_db, "HH-DS-003", {"issues": ["blurry"], "sharpness": 30}, [{"pest": "fall armyworm",
                                                                               "score": 0.9}])
    out = server.get_leaf_scan("HH-DS-003")
    assert out["scan_id"] == sid and out["image_issues"] == ["blurry"] and out["confident"] is False
    _scan(temp_db, "HH-DS-010", {"issues": []}, [], model=None)      # vision model was down at upload
    out = server.get_leaf_scan("HH-DS-010", run_id="r-v")
    assert out["vision_available"] is False and out["confidence"] == 0.0
    row = sqlite3.connect(temp_db).execute("SELECT component, recovery_action FROM recovery_log "
                                           "WHERE run_id='r-v'").fetchone()
    assert row == ("vision", "fallback:image_quality_only")


def test_outbreak_cluster_counts_the_sub_county(temp_db):
    from crop_pilot.mcp_server import server
    conn = sqlite3.connect(temp_db)
    for zone in ("RIRUTA", "WAITHAKA", "UTHIRU"):
        conn.execute("INSERT INTO pest_alerts (zone_id, pest, severity, verified, reported_at, source) "
                     "VALUES (?, 'Late Blight', 'MEDIUM', 0, '2026-10-13', 'test')", (zone,))
    conn.commit()
    out = server.get_outbreak_cluster("NGANDO")
    blight = next(c for c in out["clusters"] if c["pest"] == "late blight")
    assert out["sub_county"] == "Dagoretti South" and blight["cluster"] and blight["reports"] >= 3


def test_toolbox_retries_a_failed_mcp_call_and_logs_it(temp_db, monkeypatch):
    from crop_pilot import config
    from crop_pilot.agent.toolbox import Toolbox
    monkeypatch.setattr(config, "TOOL_RETRIES", 2)
    state = {"n": 0}

    class Session:
        async def call_tool(self, tool, args):
            state["n"] += 1
            if state["n"] == 1:
                raise ConnectionResetError("pipe closed")
            return SimpleNamespace(structuredContent={"ok": True, "value": 1}, isError=False, content=[])
    tb = Toolbox("run-retry")
    tb.sessions["crop-pilot"] = Session()
    tb.tools["get_plot_context"] = ("crop-pilot", {})
    out = asyncio.run(tb.call("get_plot_context", {"household_id": "HH-DS-001"}))
    assert out["ok"] and state["n"] == 2
    assert tb.recoveries[0]["recovery_action"] == "retried"


# --- the whole loop -------------------------------------------------------------------------------------------------
def test_unsure_photo_escalates_instead_of_guessing(temp_db):
    """Grace (HH-DS-003) would get SPRAY; a blurry, low-confidence photo makes the agent say it may be wrong."""
    from langgraph.checkpoint.memory import InMemorySaver
    from crop_pilot.agent import workflow
    _scan(temp_db, "HH-DS-003", {"issues": ["blurry"]}, [{"pest": "fall armyworm", "score": 0.55}])
    r = asyncio.run(workflow.start_run(workflow.build_graph(InMemorySaver()), "HH-DS-003"))
    assert r["frozen_at_human_gate"]
    assert r["advisory"]["status"] == "NEEDS_DATA" and r["self_check"]["outcome"] == "escalate"
    assert {u["code"] for u in r["self_check"]["uncertainty"]} == {"photo_quality", "low_confidence"}
    assert r["escalation"]["ok"] and r["escalation"]["escalation_id"]
    steps = {p["step"]: p["status"] for p in r["plan"]}
    assert steps[1] == "done" and steps[6] == "escalated" and steps[7] == "waiting"
    assert [p["phase"] for p in r["plan"]][-3:] == ["self_verify", "recover", "human_gate"]
    conn = sqlite3.connect(temp_db)
    adv = conn.execute("SELECT verdict, rationale, sources_json FROM pending_advisories").fetchone()
    assert adv[0] is None and adv[1].startswith("UNCERTAIN - I may be wrong")
    assert "field_scans:#" in adv[2]
    esc = conn.execute("SELECT household_id, sub_county, status, question FROM escalations").fetchone()
    assert esc[:3] == ("HH-DS-003", "Dagoretti South", "OPEN") and "No treatment" in esc[3]

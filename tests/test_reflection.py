"""Reflection: the self-check validates every draft before it is written, retries once, then downgrades."""
import asyncio

from langgraph.checkpoint.memory import InMemorySaver

from crop_pilot import config
from crop_pilot.agent import workflow


def _ev(**plot):
    base = {"found": True, "profile_complete": True, "zone_id": "RIRUTA", "growth_stage": "PRE_PLANTING",
            "active_crop": "Beans"}
    return {"plot": {**base, **plot},
            "rain": {"washout_risk": True, "spray_band": "UNSAFE", "rain_7d_mm": 120},
            "pests": {"top_threat": None}}


def test_check_catches_unsafe_or_out_of_area_drafts():
    draft = {"verdict": "PLANT", "sources": ["plots:HH-1", "weather_cache:RIRUTA@x"], "farmer_message": "Plant now."}
    problems = workflow.check_draft(draft, _ev())
    assert any("less cautious" in p for p in problems)
    assert any("outside Dagoretti South" in p for p in workflow.check_draft({"verdict": None}, _ev(zone_id="KISUMU")))
    spray = {"verdict": "SPRAY", "sources": ["plots:HH-1", "weather_cache:RIRUTA@x"], "farmer_message": "x"}
    assert any("SPRAY without" in p for p in workflow.check_draft(spray, _ev()))


def test_graph_retries_once_then_passes(temp_db, monkeypatch):
    monkeypatch.setattr(config, "DISABLE_LLM", True)
    calls = {"n": 0}
    real = workflow.check_draft

    def flaky(draft, evidence):
        calls["n"] += 1
        return ["simulated anomaly"] if calls["n"] == 1 else real(draft, evidence)

    monkeypatch.setattr(workflow, "check_draft", flaky)
    r = asyncio.run(workflow.start_run(workflow.build_graph(InMemorySaver()), "HH-DS-001"))
    assert calls["n"] == 2 and r["self_check"]["outcome"] == "pass" and "self_check_retry" in r["flags"]
    assert r["advisory"]["verdict"] == "PLANT" and r["frozen_at_human_gate"]


def test_graph_downgrades_after_second_failure(temp_db, monkeypatch):
    monkeypatch.setattr(config, "DISABLE_LLM", True)
    monkeypatch.setattr(workflow, "check_draft", lambda d, e: ["persistent anomaly"])
    r = asyncio.run(workflow.start_run(workflow.build_graph(InMemorySaver()), "HH-DS-003"))
    assert r["self_check"]["outcome"] == "downgrade"
    assert r["advisory"]["status"] == "NEEDS_DATA" and r["advisory"]["verdict"] is None
    assert r["followup"]["kind"] == "FIELD_VISIT"

"""Open-Meteo + Visual Crossing cross-check, retries and failover, self-check, and saying "I'm not sure"."""
import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent  # noqa: E402
import mcp_server as plant  # noqa: E402
import weather as wx  # noqa: E402

NOW = datetime(2026, 11, 16, 6, 0)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(plant, "DB_PATH", tmp_path / "plant_ai.db")
    monkeypatch.setattr(wx, "ATTEMPTS", 2)
    return tmp_path / "plant_ai.db"


def hours(rain_at=(), mm=0.0, prob=10, wind=5.0):
    return [{"time": (NOW + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"),
             "precip_mm": mm if i in set(rain_at) else 0.0, "prob": prob, "humidity": 70, "wind_kmh": wind}
            for i in range(72)]


def provider(rows=None, fail_times=0, error=TimeoutError("timed out")):
    state = {"calls": 0}

    async def fn(lat, lon):
        state["calls"] += 1
        if state["calls"] <= fail_times or rows is None:
            raise error
        return rows
    fn.state = state
    return fn


def forecast(providers):
    with plant.db() as conn:
        return asyncio.run(wx.dual_forecast(-1.28, 36.73, providers, conn, now=NOW))


# --- weather -----------------------------------------------------------------------------------------------------
def test_two_sources_agree():
    out = forecast({wx.OPEN_METEO: provider(hours([30], 2)), wx.VISUAL_CROSSING: provider(hours([31], 2.5))})
    assert out["agreement"] == "AGREE" and out["cross_checked"] and out["summary"]["hours_until_rain"] == 30


def test_two_sources_disagree_and_cautious_reading_wins():
    out = forecast({wx.OPEN_METEO: provider(hours([2, 3, 4], 6, prob=90)), wx.VISUAL_CROSSING: provider(hours())})
    assert out["agreement"] == "DISAGREE" and any("spray window" in d for d in out["disagreements"])
    assert out["summary"]["spray_window_ok"] is False and out["summary"]["hours_until_rain"] == 2


def test_timeout_is_retried_then_fails_over():
    om = provider(None)
    out = forecast({wx.OPEN_METEO: om, wx.VISUAL_CROSSING: provider(hours())})
    assert om.state["calls"] == 2 and out["agreement"] == "SINGLE_SOURCE"
    assert out["recovery"][0]["action"] == "failover to Visual Crossing"
    flaky = provider(hours(), fail_times=1)
    out = forecast({wx.OPEN_METEO: flaky, wx.VISUAL_CROSSING: provider(hours())})
    assert out["agreement"] == "AGREE" and out["recovery"][0]["action"] == "retried"


def test_both_down_uses_cache_then_admits_no_data(tmp_db):
    down = {wx.OPEN_METEO: provider(None), wx.VISUAL_CROSSING: provider(None)}
    out = forecast(down)
    assert out["ok"] is False and out["agreement"] == "NO_DATA" and "cannot say" in out["message"]
    forecast({wx.OPEN_METEO: provider(hours()), wx.VISUAL_CROSSING: provider(None)})     # fills the cache
    out = forecast(down)
    assert out["ok"] and out["degraded_source"].startswith("cached forecast")
    assert out["recovery"][-1]["action"] == "fallback to cached forecast"


# --- the agent ---------------------------------------------------------------------------------------------------
def dx(label="tomato__late_blight", conf=0.93, second=0.04, issues=()):
    crop, cond = label.split("__")
    return {"ok": True, "label": label, "crop": crop, "condition": cond, "confidence": conf,
            "predictions": [{"label": label, "confidence": conf}, {"label": "tomato__early_blight", "confidence": second}],
            "image_quality": {"issues": list(issues)}, "confident": conf >= 0.75 and not issues,
            "healthy": cond == "healthy", "needs_human_review": conf < 0.75 or bool(issues)}


def plant_calls(diagnosis, fail=None):
    """A fake plant MCP: real outbreak/advisory tools, a scripted diagnosis, optional transient failures."""
    fail = dict(fail or {})
    calls = []

    async def call(tool, args):
        calls.append(tool)
        if fail.get(tool, 0) > 0:
            fail[tool] -= 1
            return {"ok": False, "error": "ClosedResourceError: MCP server connection lost"}
        if tool == "diagnose_crop_leaf":
            return dict(diagnosis)
        return getattr(plant, tool)(**args)
    call.calls = calls
    return call


def run(diagnosis, weather_out, fail=None, lat=-1.28):
    req = SimpleNamespace(image_base64="x", region="Riruta", lat=lat, lon=36.73, crop=None)
    call = plant_calls(diagnosis, fail)
    seq = list(weather_out) if isinstance(weather_out, list) else [weather_out]

    async def get_weather(a, b):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return asyncio.run(agent.run_diagnosis(req, call, get_weather, "run-t")), call


AGREE_DRY = {"ok": True, "agreement": "AGREE", "summary": {"hours_until_rain": 30, "rain_next_24h_mm": 0,
                                                            "rain_probability_max": 10, "spray_window_ok": True},
             "recovery": [], "disagreements": []}
DISAGREE = {"ok": True, "agreement": "DISAGREE", "disagreements": ["spray window: open vs closed"],
            "summary": {"hours_until_rain": 30, "rain_next_24h_mm": 0, "rain_probability_max": 10,
                        "spray_window_ok": True}, "recovery": []}


def test_confident_answer_has_a_plan_and_passes_self_check():
    r, _ = run(dx(), AGREE_DRY)
    assert r["answer_status"] == "CONFIDENT" and r["self_check"]["passed"] and r["review_request"] is None
    assert [p["id"] for p in r["plan"]] == ["diagnose", "outbreak", "weather", "advise", "self_check", "recover",
                                            "human_gate"]
    assert r["plan"][4]["status"] == "passed" and r["advisory"]["treatment"]["spray_now_ok"]


def test_low_confidence_says_im_not_sure_and_asks_an_officer(tmp_db):
    r, _ = run(dx(conf=0.55, second=0.3), AGREE_DRY)
    assert r["answer_status"] == "UNCERTAIN" and r["message"].startswith("I'm not sure")
    assert "only 55% sure" in r["message"] and r["advisory"]["treatment"] is None
    assert r["review_request"]["status"] == "OPEN"
    assert sqlite3.connect(tmp_db).execute("SELECT COUNT(*) FROM review_requests").fetchone()[0] == 1


def test_close_call_and_blurry_photo_are_uncertain():
    r, _ = run(dx(conf=0.80, second=0.70), AGREE_DRY)
    assert {u["code"] for u in r["uncertainty"]} == {"close_call"} and "could also be tomato early blight" in r["message"]
    r, _ = run(dx(issues=["blurry"]), AGREE_DRY)
    assert "photo_quality" in {u["code"] for u in r["uncertainty"]}


def test_weather_disagreement_is_rechecked_then_spraying_held_back():
    r, _ = run(dx(), [DISAGREE, DISAGREE])
    assert r["answer_status"] == "UNCERTAIN" and "weather_disagreement" in {u["code"] for u in r["uncertainty"]}
    assert r["advisory"]["treatment"]["spray_now_ok"] is False
    assert "re-fetched both forecasts" in r["self_check"]["recovered"]
    # the second fetch agrees: recovered, confident
    r, _ = run(dx(), [DISAGREE, AGREE_DRY])
    assert r["answer_status"] == "CONFIDENT" and r["plan"][5]["status"] == "done"


def test_transient_tool_failures_are_retried_and_logged(tmp_db):
    r, call = run(dx(), AGREE_DRY, fail={"diagnose_crop_leaf": 1, "check_regional_outbreak": 5})
    assert call.calls.count("diagnose_crop_leaf") == 2 and r["answer_status"] == "CONFIDENT"
    assert r["plan"][1]["status"] == "recovered"                      # outbreak gave up: advice without it
    actions = [e["action"] for e in r["recovery"]]
    assert "retried" in actions and "continued without outbreak data" in actions
    assert sqlite3.connect(tmp_db).execute("SELECT COUNT(*) FROM recovery_log").fetchone()[0] == len(actions)


def test_advisory_tool_down_falls_back_safely():
    r, _ = run(dx(), AGREE_DRY, fail={"draft_extension_advisory": 9})
    assert r["advisory"]["fallback"] and r["advisory"]["treatment"] is None


def test_no_weather_before_spraying_is_admitted():
    r, _ = run(dx(), {"ok": False, "agreement": "NO_DATA", "summary": None, "recovery": []})
    assert r["answer_status"] == "UNCERTAIN" and "no weather forecast" in r["message"]


def test_unreadable_photo_fails_cleanly():
    bad = {"ok": False, "error": "image_base64 is not valid base64"}
    r, call = run(bad, AGREE_DRY)
    assert r["answer_status"] == "FAILED" and r["fixable_by_user"] and call.calls == ["diagnose_crop_leaf"]

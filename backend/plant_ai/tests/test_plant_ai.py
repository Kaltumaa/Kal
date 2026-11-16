"""Plant AI service: MCP tools, the orchestration API and its human-in-the-loop gate.

Run with the plant AI venv:   .venv-plantai/bin/python -m pytest backend/plant_ai/tests -q
"""
import base64
import io
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import mcp_server as plant  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(plant, "DB_PATH", tmp_path / "plant_ai.db")
    return tmp_path / "plant_ai.db"


def _leaf_png(sharp=True) -> str:
    img = Image.new("RGB", (256, 256), (40, 120, 40))
    d = ImageDraw.Draw(img)
    if sharp:
        for i in range(0, 256, 8):
            d.line([(i, 0), (255 - i, 255)], fill=(200, 180, 60), width=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeClassifier:
    trained_at, metrics = "test", {"val_acc": 0.9, "val_acc_field": 0.6}

    def __init__(self, label="tomato__late_blight", conf=0.93):
        self.label, self.conf = label, conf

    def predict(self, image, top_k=3):
        crop, cond = self.label.split("__")
        return [{"label": self.label, "crop": crop, "condition": cond, "confidence": self.conf},
                {"label": "tomato__early_blight", "crop": "tomato", "condition": "early_blight",
                 "confidence": round(1 - self.conf, 4)}][:top_k]


# --- MCP tools ----------------------------------------------------------------------------------------------------
def test_diagnose_flags_low_confidence_and_blur(monkeypatch):
    monkeypatch.setattr(plant, "_classifier", FakeClassifier(conf=0.93))
    out = plant.diagnose_crop_leaf(image_base64=_leaf_png())
    assert out["ok"] and out["label"] == "tomato__late_blight" and out["confident"]
    monkeypatch.setattr(plant, "_classifier", FakeClassifier(conf=0.5))
    out = plant.diagnose_crop_leaf(image_base64=_leaf_png())
    assert not out["confident"] and "below 75%" in out["uncertainty_reasons"][0]
    monkeypatch.setattr(plant, "_classifier", FakeClassifier(conf=0.99))
    blurry = plant.diagnose_crop_leaf(image_base64=_leaf_png(sharp=False))
    assert blurry["image_quality"]["issues"] == ["blurry"] and not blurry["confident"]
    assert plant.diagnose_crop_leaf(image_base64="not base64!!")["ok"] is False


def test_real_model_checkpoint_loads_and_predicts(tmp_path, monkeypatch):
    """A tiny untrained checkpoint in the real format: proves LeafClassifier + the tool wire up end to end."""
    import torch
    from plant_model import build_model
    classes = ["corn__common_rust", "corn__healthy", "tomato__late_blight"]
    path = tmp_path / "m.pth"
    torch.save({"classes": classes, "img_size": 224, "state_dict": build_model(3).state_dict(),
                "metrics": {"val_acc": 0.1}}, path)
    monkeypatch.setattr(plant, "MODEL_PATH", path)
    monkeypatch.setattr(plant, "_classifier", None)
    out = plant.diagnose_crop_leaf(image_base64=_leaf_png(), top_k=3)
    assert out["ok"] and out["label"] in classes and len(out["predictions"]) == 3
    assert abs(sum(p["confidence"] for p in out["predictions"]) - 1) < 0.01


def test_outbreak_spike_rule(tmp_db):
    for _ in range(2):
        out = plant.check_regional_outbreak("Riruta", "tomato__late_blight")
    assert out["cases_last_7d"] == 2 and not out["spike"] and out["level"] == "WATCH"
    out = plant.check_regional_outbreak("RIRUTA ", "tomato__late_blight")
    assert out["spike"] and out["level"] == "SPIKE"
    # a busy baseline (10 cases a week for the last 4 weeks) means 3 this week is not a spike
    conn = sqlite3.connect(tmp_db)
    for week in range(1, 5):
        when = (datetime.now(timezone.utc) - timedelta(days=7 * week + 1)).isoformat()
        conn.executemany("INSERT INTO cases (region, disease, source, reported_at) VALUES ('waithaka', "
                         "'corn__common_rust', 'model', ?)", [(when,)] * 10)
    conn.commit()
    for _ in range(3):
        out = plant.check_regional_outbreak("Waithaka", "corn__common_rust")
    assert out["cases_last_7d"] == 3 and out["baseline_weekly"] == 10 and not out["spike"]
    healthy = plant.check_regional_outbreak("Riruta", "tomato__healthy")
    assert healthy["case_id"] is None


def test_advisory_refuses_to_guess_and_respects_rain():
    unsure = plant.draft_extension_advisory("tomato__late_blight", 0.6, "Riruta")
    assert unsure["status"] == "NEEDS_OFFICER_DIAGNOSIS" and unsure["treatment"] is None
    blurry = plant.draft_extension_advisory("tomato__late_blight", 0.95, "Riruta", image_issues=["blurry"])
    assert blurry["treatment"] is None
    wet = plant.draft_extension_advisory("tomato__late_blight", 0.9, "Riruta", hours_until_rain=3,
                                         rain_next_24h_mm=12, outbreak_level="SPIKE")
    assert wet["treatment"]["spray_now_ok"] is False and wet["treatment"]["chemical"].startswith("After the rain")
    assert any("Regional spike" in w for w in wet["warnings"])
    dry = plant.draft_extension_advisory("tomato__late_blight", 0.9, "Riruta", hours_until_rain=30,
                                         rain_next_24h_mm=0, rain_probability_max=10)
    assert dry["treatment"]["spray_now_ok"] and "PCPB" in dry["message"]
    virus = plant.draft_extension_advisory("tomato__mosaic_virus", 0.9, "Riruta", hours_until_rain=30)
    assert virus["treatment"]["chemical"] is None and "No cure" in virus["message"]
    assert plant.draft_extension_advisory("corn__healthy", 0.9, "Riruta")["treatment"] is None


# --- orchestration API ---------------------------------------------------------------------------------------------
def _fake_weather_server(rain_at_hour=3):
    from fastmcp import FastMCP
    srv = FastMCP("fake-open-meteo")

    @srv.tool
    def weather_forecast(latitude: float, longitude: float, hourly: list[str] | None = None,
                         forecast_days: int = 3, timezone: str = "auto") -> dict:
        start = datetime.now().replace(minute=0, second=0, microsecond=0)
        times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(72)]
        return {"latitude": latitude, "longitude": longitude,
                "hourly": {"time": times, "precipitation": [4.0 if i == rain_at_hour else 0.0 for i in range(72)],
                           "precipitation_probability": [70 if i == rain_at_hour else 10 for i in range(72)]}}
    return srv


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient
    from fastmcp import Client
    import agent_api
    monkeypatch.setattr(plant, "_classifier", FakeClassifier())
    agent_api.app.state.mcp_clients = {"plant_client": Client(plant.mcp),
                                       "weather_client": Client(_fake_weather_server())}
    with TestClient(agent_api.app) as client:
        yield client
    agent_api.app.state.mcp_clients = None


def test_pipeline_pauses_outbreak_alert_for_a_named_officer(api, tmp_db):
    body = {"image_base64": _leaf_png(), "region": "Riruta", "lat": -1.285, "lon": 36.735}
    health = api.get("/api/health").json()
    assert health["mcp"]["weather"]["tool"] == "weather_forecast"
    assert set(health["mcp"]["plant_ai"]["tools"]) == {"diagnose_crop_leaf", "check_regional_outbreak",
                                                         "draft_extension_advisory"}
    r1 = api.post("/api/diagnose", json=body).json()
    assert r1["alert"] is None and r1["weather"]["summary"]["hours_until_rain"] == 3
    assert r1["advisory"]["treatment"]["spray_now_ok"] is False          # rain in 3 h: no spraying now
    assert [t["tool"] for t in r1["trace"]][:2] == ["diagnose_crop_leaf", "check_regional_outbreak"]
    api.post("/api/diagnose", json=body)
    r3 = api.post("/api/diagnose", json=body).json()
    alert = r3["alert"]
    assert alert["status"] == "PENDING_APPROVAL" and r3["human_review_required"]
    assert r3["trace"][-1]["tool"] == "HUMAN_GATE"
    assert api.get(f"/api/alerts/{alert['id']}").json()["outbox"] == []   # nothing sent before approval

    assert api.post(f"/api/alerts/{alert['id']}/approve", json={"officer_name": "admin"}).status_code == 400
    done = api.post(f"/api/alerts/{alert['id']}/approve", json={"officer_name": "Wanjiru Kamau"}).json()
    assert done["status"] == "DISPATCHED" and done["decided_by"] == "Wanjiru Kamau"
    assert done["outbox"][0]["approved_by"] == "Wanjiru Kamau"
    assert api.post(f"/api/alerts/{alert['id']}/approve", json={"officer_name": "Wanjiru Kamau"}).status_code == 409

    conn = sqlite3.connect(tmp_db)
    with pytest.raises(sqlite3.IntegrityError):        # the database itself refuses an unsigned dispatch
        conn.execute("INSERT INTO outbreak_alerts (region, disease, message, evidence, status, created_at) "
                     "VALUES ('x', 'y', 'z', '{}', 'DISPATCHED', 'now')")
    assert api.get("/api/outbreaks").json()["regions"][0]["cases"] == 3


def test_unsure_diagnosis_is_not_logged_and_gets_no_treatment(api, monkeypatch):
    monkeypatch.setattr(plant, "_classifier", FakeClassifier(conf=0.4))
    r = api.post("/api/diagnose", json={"image_base64": _leaf_png(), "region": "Riruta"}).json()
    assert r["diagnosis"]["needs_human_review"] and r["advisory"]["status"] == "NEEDS_OFFICER_DIAGNOSIS"
    assert r["outbreak"]["case_id"] is None and r["alert"] is None
    assert r["weather"]["ok"] is False                       # no coordinates sent


def test_reject_and_cors(api):
    for _ in range(3):
        alert = api.post("/api/diagnose", json={"image_base64": _leaf_png(), "region": "Uthiru"}).json()["alert"]
    r = api.post(f"/api/alerts/{alert['id']}/reject", json={"officer_name": "Wanjiru Kamau", "note": "lab check"})
    assert r.json()["status"] == "REJECTED" and r.json()["outbox"] == []
    pre = api.options("/api/diagnose", headers={"Origin": "http://localhost:5173",
                                                "Access-Control-Request-Method": "POST"})
    assert pre.headers.get("access-control-allow-origin") in ("*", "http://localhost:5173")

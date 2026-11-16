"""SMS goes out through Africa's Talking when keys are set; otherwise it is simulated. Failures never lose a message."""
import httpx

from crop_pilot import config
from crop_pilot.dispatch import approval, sms
from crop_pilot.mcp_server import server

CITE = "Citing plots:HH-DS-003 and weather_cache:MUTUINI@2026-10-14"


def _advice():
    return server.draft_advisory(run_id="run-sms", household_id="HH-DS-003", status="PENDING_REVIEW", verdict="HOLD",
                                 farmer_message="Hold field work: heavy rain is coming.", rationale="rain", evidence={},
                                 sources=["plots:HH-DS-003", "weather_cache:MUTUINI@2026-10-14"])["advisory_id"]


def test_without_keys_sms_is_simulated(temp_db):
    r = approval.approve(_advice(), "Wanjiru Kamau", citation=CITE)
    assert [d["status"] for d in r["sms"]] == ["SIMULATED"]
    assert sms.deliveries()[0]["phone"] == "+254700000003"


def test_signed_advice_is_sent_through_africas_talking(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AT_USERNAME", "sandbox")
    monkeypatch.setattr(config, "AT_API_KEY", "k")
    calls = []

    def fake_post(url, data=None, timeout=None, headers=None):
        calls.append((url, data, headers["apiKey"]))
        return httpx.Response(201, json={"SMSMessageData": {"Recipients": [
            {"statusCode": 101, "status": "Success", "messageId": "ATXid_1", "cost": "KES 0.8000"}]}},
            request=httpx.Request("POST", url))
    monkeypatch.setattr(sms.httpx, "post", fake_post)
    r = approval.approve(_advice(), "Wanjiru Kamau", citation=CITE)
    assert r["sms"][0]["status"] == "SENT" and r["sms"][0]["cost"] == "KES 0.8000"
    url, data, key = calls[0]
    assert "sandbox" in url and data["to"] == "+254700000003" and data["username"] == "sandbox" and key == "k"
    sms.queue_out("HH-DS-003", "Your photo was checked.", "photo_result")       # other SMS go out too
    assert len(calls) == 2


def test_gateway_failure_keeps_the_message(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AT_USERNAME", "sandbox")
    monkeypatch.setattr(config, "AT_API_KEY", "k")

    def down(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(sms.httpx, "post", down)
    r = approval.approve(_advice(), "Wanjiru Kamau", citation=CITE)
    assert r["status"] == "APPROVED" and r["sms"][0]["status"] == "FAILED" and approval.outbox()

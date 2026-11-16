"""WhatsApp channel: signed advice reaches smartphone farmers, farmers' commands work, webhooks are verified."""
import hashlib
import hmac
import json

import httpx
import pytest

from crop_pilot import config
from crop_pilot.dispatch import approval, whatsapp
from crop_pilot.mcp_server import server

CITE = "Citing plots:HH-DS-002 and weather_cache:WAITHAKA@2026-10-14"


def _advice(hid="HH-DS-002", zone="WAITHAKA"):
    return server.draft_advisory(run_id=f"run-{hid}", household_id=hid, status="PENDING_REVIEW", verdict="HOLD",
                                 farmer_message="Hold field work: heavy rain is coming.", rationale="rain",
                                 evidence={}, sources=[f"plots:{hid}", f"weather_cache:{zone}@2026-10-14"])["advisory_id"]


def test_signed_advice_goes_to_smartphone_farmers_on_whatsapp(temp_db):
    r = approval.approve(_advice(), "Wanjiru Kamau", citation=CITE)
    assert [w["status"] for w in r["whatsapp"]] == ["SIMULATED"]
    msg = whatsapp.list_messages("HH-DS-002")[0]
    assert (msg["kind"], msg["sent_by"], msg["direction"]) == ("advice", "Wanjiru Kamau", "OUT")
    assert approval.outbox()                                         # the SMS is still queued


def test_feature_phone_farmers_get_sms_only(temp_db):
    r = approval.approve(_advice("HH-DS-003", "MUTUINI"), "Wanjiru Kamau",
                         citation="Citing plots:HH-DS-003 and weather_cache:MUTUINI@2026-10-14")
    assert r["whatsapp"] == [] and whatsapp.list_messages("HH-DS-003") == []


def test_live_send_failure_never_blocks_the_signed_advice(temp_db, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "t")
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "1")

    def down(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(whatsapp.httpx, "post", down)
    monkeypatch.setattr("crop_pilot.core.resilience.time.sleep", lambda s: None)
    r = approval.approve(_advice(), "Wanjiru Kamau", citation=CITE)
    assert r["status"] == "APPROVED" and r["whatsapp"][0]["status"] == "FAILED"


def test_live_send_builds_a_template_for_advice(temp_db, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "t")
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setattr(config, "WHATSAPP_TEMPLATE", "talo_advice")
    sent = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        sent.update(url=url, body=json, auth=headers["Authorization"])
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(whatsapp.httpx, "post", fake_post)
    r = approval.approve(_advice(), "Wanjiru Kamau", citation=CITE)
    assert r["whatsapp"][0]["status"] == "SENT" and sent["url"].endswith("/123/messages")
    assert sent["body"]["to"] == "254700000002" and sent["body"]["template"]["name"] == "talo_advice"
    assert sent["auth"] == "Bearer t"


def test_farmer_commands_work_over_whatsapp(temp_db):
    r = whatsapp.receive("0700 000 002", "LOG WEEDING top field")             # local format matches +254...
    assert r["household_id"] == "HH-DS-002" and r["command"] == "LOG" and r["reply_status"] == "SIMULATED"
    kinds = [(m["direction"], m["kind"]) for m in whatsapp.list_messages("HH-DS-002")]
    assert kinds == [("OUT", "reply"), ("IN", "command")]
    unknown = whatsapp.receive("+254799999999", "HELP")
    assert unknown["household_id"] is None and "not registered" in unknown["reply"]


def test_webhook_handshake_and_signature(temp_db, monkeypatch):
    from fastapi.testclient import TestClient
    from crop_pilot.api.voice_hooks import app
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "s3cret")
    c = TestClient(app)
    ok = c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                           "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope"}).status_code == 403
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "254700000002", "id": "wamid.in", "type": "text", "text": {"body": "HELP"}}]}}]}]}).encode()
    assert c.post("/whatsapp/webhook", content=body, headers={"x-hub-signature-256": "sha256=bad"}).status_code == 403
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = c.post("/whatsapp/webhook", content=body, headers={"x-hub-signature-256": sig})
    assert r.status_code == 200 and r.json() == {"handled": 1}


def test_live_mode_refuses_unsigned_webhooks(temp_db, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "t")
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "1")
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "")
    assert whatsapp.signature_ok(b"{}", None) is False


@pytest.fixture(autouse=True)
def _no_whatsapp_keys(monkeypatch):
    for key in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TEMPLATE", "WHATSAPP_APP_SECRET"):
        monkeypatch.setattr(config, key, "")

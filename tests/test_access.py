"""The main API is locked: sign-in required, roles enforced, farmers see only their own farm, signatures are real."""
import pytest
from fastapi.testclient import TestClient

from crop_pilot.accounts import service as accounts
from crop_pilot.api import main
from crop_pilot.mcp_server import server

pytestmark = pytest.mark.real_auth
PW = "a-long-password-1"


def _h(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


@pytest.fixture()
def people(temp_db):
    return {
        "farmer": accounts.register_farmer("grace@example.com", PW, "Grace Wanjiku", "HH-DS-003"),
        "officer": accounts.register_officer("wanjiru@example.com", PW, "Wanjiru Kamau", None, "Nairobi",
                                             "Dagoretti South"),
        "inst": accounts.register_institution("Nairobi County Agric Department", "county_agric_department",
                                              "Nairobi", "inst@example.com", PW, "Amina Odhiambo"),
    }


@pytest.fixture()
def c(people):
    with TestClient(main.app) as client:
        yield client


def test_nothing_without_sign_in(c):
    assert c.get("/health").status_code == 200
    for method, path in (("GET", "/households"), ("GET", "/advisories"), ("POST", "/runs"), ("GET", "/outbox"),
                         ("GET", "/farms/HH-DS-003/notifications"), ("GET", "/telemetry"), ("GET", "/assurance")):
        assert c.request(method, path, json={"household_id": "HH-DS-003"}).status_code == 401, path
    assert c.get("/households", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    anon = c.get("/farms").json()                                      # the sign-up picker: IDs, no names
    assert anon and all(f["farmer_name"] == f["household_id"] for f in anon)


def test_farmer_sees_only_their_own_farm(c, people):
    h = _h(people["farmer"])
    assert c.get("/farms/HH-DS-003/notifications", headers=h).status_code == 200
    assert c.get("/households/HH-DS-003/profile", headers=h).status_code == 200
    assert c.get("/farms/HH-DS-001/notifications", headers=h).status_code == 403
    assert c.get("/households/HH-DS-001/profile", headers=h).status_code == 403
    assert c.get("/sms", params={"household_id": "HH-DS-001"}, headers=h).status_code == 403
    assert c.post("/sms/inbound", json={"household_id": "HH-DS-001", "text": "HELP"}, headers=h).status_code == 403
    assert c.post("/sms/inbound", json={"household_id": "HH-DS-003", "text": "HELP"}, headers=h).status_code == 200
    for method, path in (("GET", "/advisories"), ("POST", "/runs"), ("POST", "/advisories/1/approve"),
                         ("GET", "/outbox"), ("POST", "/weather/refresh"), ("GET", "/households")):
        assert c.request(method, path, json={}, headers=h).status_code == 403, path
    assert c.get("/forum", headers=h).status_code == 200 and c.get("/knowledge", headers=h).status_code == 200


def test_institution_can_view_but_not_act(c, people):
    h = _h(people["inst"])
    assert c.get("/advisories", headers=h).status_code == 200
    assert c.post("/runs", json={"household_id": "HH-DS-003"}, headers=h).status_code == 403


def test_officer_signature_must_be_their_own_name(c, people):
    adv = server.draft_advisory(run_id="run-acc", household_id="HH-DS-003", status="PENDING_REVIEW", verdict="HOLD",
                                farmer_message="Hold.", rationale="rain", evidence={},
                                sources=["plots:HH-DS-003", "weather_cache:MUTUINI@2026-10-14"])["advisory_id"]
    h = _h(people["officer"])
    body = {"officer_name": "Someone Else", "citation": "Citing plots:HH-DS-003"}
    forged = c.post(f"/advisories/{adv}/reject", json=dict(body, reason="x"), headers=h)
    assert forged.status_code == 403 and "Wanjiru Kamau" in forged.json()["detail"]
    ok = c.post(f"/advisories/{adv}/reject", json=dict(body, officer_name="  wanjiru   KAMAU ", reason="x"),
                headers=h)
    assert ok.status_code == 200 and ok.json()["officer"] == "Wanjiru Kamau"


def test_webhooks_stay_public(c):
    assert c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x"}).status_code == 403
    assert c.post("/voice/callback", data={"sessionId": "x"}).status_code != 401           # own token check, no sign-in
    assert c.post("/api/auth/login", json={"email": "wanjiru@example.com", "password": PW}).status_code == 200

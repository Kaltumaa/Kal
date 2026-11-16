"""Thin HTTP client. The frontend knows nothing about the backend except this URL."""
from __future__ import annotations

import os

import requests

API_URL = os.environ.get("CROP_PILOT_API", "http://127.0.0.1:8000")


class ApiError(RuntimeError):
    def __init__(self, status: int, detail):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def _session_token() -> str | None:
    """The signed-in user's token for this browser session (set by auth.sign_in), if any."""
    try:
        import streamlit as st
        a = st.session_state.get("auth")
    except Exception:  # noqa: BLE001 - outside a Streamlit session (scripts, tests)
        return None
    return a.get("access_token") if a else None


def _auth_headers(extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    token = _session_token()
    if token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _req(method: str, path: str, timeout: float = 30, **kwargs):
    kwargs["headers"] = _auth_headers(kwargs.get("headers"))
    try:
        r = requests.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise ApiError(0, f"backend unreachable at {API_URL} ({type(exc).__name__})") from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        raise ApiError(r.status_code, detail)
    return r.json()


def health():
    return _req("GET", "/health", timeout=10)


def households():
    return _req("GET", "/households")


def run_agent(household_id: str, officer_note: str = ""):
    return _req("POST", "/runs", json={"household_id": household_id, "officer_note": officer_note}, timeout=900)


def advisories(status: str | None = None):
    return _req("GET", "/advisories", params={"status": status} if status else None)


def approve(advisory_id: int, officer_name: str, final_message: str | None, citation: str,
            final_message_sw: str | None = None, languages: list[str] | None = None, call: bool = False):
    return _req("POST", f"/advisories/{advisory_id}/approve",
                json={"officer_name": officer_name, "final_message": final_message, "citation": citation,
                      "final_message_sw": final_message_sw, "languages": languages or ["en"], "call": call})


def reject(advisory_id: int, officer_name: str, reason: str):
    return _req("POST", f"/advisories/{advisory_id}/reject", json={"officer_name": officer_name, "reason": reason})


def telemetry(run_id: str | None = None):
    return _req("GET", "/telemetry", params={"run_id": run_id} if run_id else None)


def outbox():
    return _req("GET", "/outbox")


def manual_fallback(officer_name: str, household_id: str, verdict: str, note: str):
    return _req("POST", "/fallback/manual", json={"officer_name": officer_name, "household_id": household_id,
                                                  "verdict": verdict, "note": note})


def manual_fallback_list():
    return _req("GET", "/fallback/manual")


def overview():
    return _req("GET", "/overview")


def spray_groups() -> list[str]:
    return _req("GET", "/knowledge/spray-groups")


def terrain_options() -> dict:
    return _req("GET", "/knowledge/terrain")


def set_terrain(household_id: str, slope: str, soil: str, officer_name: str, intercrop: str | None = None):
    return _req("POST", f"/farms/{household_id}/terrain",
                json={"slope": slope, "soil": soil, "intercrop": intercrop, "officer_name": officer_name})


def knowledge_topics():
    return _req("GET", "/knowledge")


def knowledge_topic(slug: str) -> str:
    return _req("GET", f"/knowledge/{slug}")["markdown"]


def crops():
    return _req("GET", "/knowledge/crops")


def suitability(season_rain_mm: float, mean_temp_c: float, soil: str | None, greenhouse: bool,
                rain_7d_mm: float | None = None):
    return _req("POST", "/knowledge/suitability", json={"season_rain_mm": season_rain_mm, "mean_temp_c": mean_temp_c,
                                                        "soil": soil, "greenhouse": greenhouse,
                                                        "rain_7d_mm": rain_7d_mm})


def create_scan(image_b64: str, household_id: str | None, crop: str | None):
    return _req("POST", "/scans", json={"image_b64": image_b64, "household_id": household_id, "crop": crop},
                timeout=600)


def scans():
    return _req("GET", "/scans")


def scan_image(scan_id: int) -> bytes | None:
    try:
        r = requests.get(f"{API_URL}/scans/{scan_id}/image", timeout=15, headers=_auth_headers())
        return r.content if r.status_code == 200 else None
    except requests.RequestException:
        return None


def review_scan(scan_id: int, officer_name: str, decision: str, pest: str | None = None, severity: str = "MEDIUM",
                note: str = "", finding: str | None = None, call: bool = False, call_script: str | None = None,
                call_language: str = "sw"):
    return _req("POST", f"/scans/{scan_id}/review", json={"officer_name": officer_name, "decision": decision,
                                                          "pest": pest, "severity": severity, "note": note,
                                                          "finding": finding, "call": call,
                                                          "call_script": call_script, "call_language": call_language})


def scan_groups():
    return _req("GET", "/scans/groups")


def review_scan_batch(scan_ids: list[int], officer_name: str, pest: str, severity: str, note: str):
    return _req("POST", "/scans/review-batch", json={"scan_ids": scan_ids, "officer_name": officer_name,
                                                     "pest": pest, "severity": severity, "note": note})


def forum_topics():
    return _req("GET", "/forum/topics")


def forum(topic: str | None = None):
    return _req("GET", "/forum", params={"topic": topic} if topic else None)


def forum_post(author: str, topic: str, body: str, zone_id: str | None = None, household_id: str | None = None):
    return _req("POST", "/forum", json={"author": author, "topic": topic, "body": body, "zone_id": zone_id,
                                        "household_id": household_id})


def run_ward(zone_id: str):
    return _req("POST", f"/wards/{zone_id}/runs", timeout=3600)


def season_outlook():
    return _req("GET", "/knowledge/season")


def greenhouse_check(temp_c: float, rh_pct: float, crop: str | None, greenhouse_id: str = "GH-1"):
    return _req("POST", "/greenhouse/check", json={"greenhouse_id": greenhouse_id, "temp_c": temp_c, "rh_pct": rh_pct,
                                                   "crop": crop})


def greenhouse_sensor_reading(temp_c: float, rh_pct: float, device_id: str, greenhouse_id: str = "GH-1"):
    return _req("POST", "/greenhouse/readings", json={"greenhouse_id": greenhouse_id, "temp_c": temp_c,
                                                      "rh_pct": rh_pct, "device_id": device_id})


def greenhouse_history(greenhouse_id: str | None = None):
    return _req("GET", "/greenhouse/readings", params={"greenhouse_id": greenhouse_id} if greenhouse_id else None)


def greenhouse_assess(temp_c: float, rh_pct: float, crop: str | None = None):
    return _req("POST", "/greenhouse/assess", json={"temp_c": temp_c, "rh_pct": rh_pct, "crop": crop})


def followups(status: str = "OPEN"):
    return _req("GET", "/followups", params={"status": status})


def close_followup(followup_id: int, officer_name: str):
    return _req("POST", f"/followups/{followup_id}/done", json={"officer_name": officer_name})


def household_profile(household_id: str):
    return _req("GET", f"/households/{household_id}/profile")


def refresh_weather():
    return _req("POST", "/weather/refresh")


def update_forecast(zone_id: str, rain_24h_mm: float, rain_72h_mm: float, rain_7d_mm: float, storm_risk: str):
    return _req("POST", f"/weather/{zone_id}", json={"rain_24h_mm": rain_24h_mm, "rain_72h_mm": rain_72h_mm,
                                                    "rain_7d_mm": rain_7d_mm, "storm_risk": storm_risk,
                                                    "source": "Officer-entered forecast update"})


def farms():
    return _req("GET", "/farms")


def farm_actions(household_id: str):
    return _req("GET", f"/farms/{household_id}/actions")


def log_farm_action(household_id: str, action: str, action_date: str, crop: str | None, details: str, role: str,
                    name: str | None, chem_group: str | None = None, needs_weeding: bool | None = None,
                    soil_moist: bool | None = None, seed_check: str | None = None, as_intercrop: bool = False):
    return _req("POST", f"/farms/{household_id}/actions", json={"action": action, "action_date": action_date,
                                                                "crop": crop, "details": details, "role": role,
                                                                "name": name, "chem_group": chem_group,
                                                                "needs_weeding": needs_weeding,
                                                                "soil_moist": soil_moist,
                                                                "seed_check": seed_check,
                                                                "as_intercrop": as_intercrop})


def reminders(household_id: str):
    return _req("GET", f"/farms/{household_id}/reminders")


def create_reminder(household_id: str, due_date: str, action: str, note: str):
    return _req("POST", f"/farms/{household_id}/reminders", json={"due_date": due_date, "action": action, "note": note})


def reminder_done(reminder_id: int):
    return _req("POST", f"/reminders/{reminder_id}/done")


def farms_plan():
    return _req("GET", "/farms/plan")


def submit_photo(household_id: str, image_b64: str):
    return _req("POST", f"/farms/{household_id}/photos", json={"image_b64": image_b64}, timeout=600)


def my_photos(household_id: str):
    return _req("GET", f"/farms/{household_id}/photos")


def notifications(household_id: str, seen: bool = False):
    return _req("GET", f"/farms/{household_id}/notifications", params={"seen": seen})


def set_language(household_id: str, language: str):
    return _req("POST", f"/farms/{household_id}/language", json={"language": language})


def problem(name: str):
    return _req("GET", "/knowledge/problem", params={"name": name})


def community_reports():
    return _req("GET", "/community/reports")


def review_report(post_id: int, officer_name: str, decision: str, pest: str | None, severity: str,
                  zone_id: str | None, note: str):
    return _req("POST", f"/community/reports/{post_id}/review",
                json={"officer_name": officer_name, "decision": decision, "pest": pest, "severity": severity,
                      "zone_id": zone_id, "note": note})


def sms_inbound(household_id: str, text: str):
    return _req("POST", "/sms/inbound", json={"household_id": household_id, "text": text})


def assurance():
    return _req("GET", "/assurance")


def sms_deliveries():
    return _req("GET", "/sms/deliveries")


def whatsapp_messages():
    return _req("GET", "/whatsapp")


def whatsapp_simulate(phone: str, text: str):
    return _req("POST", "/whatsapp/simulate", json={"phone": phone, "text": text})


def sms_messages(household_id: str | None = None):
    return _req("GET", "/sms", params={"household_id": household_id} if household_id else None)


def speech_status():
    return _req("GET", "/speech/status")


def transcribe(audio_b64: str, language: str | None):
    # The first voice note loads the speech model, which can take a few minutes on a laptop.
    return _req("POST", "/speech/transcribe", timeout=600, json={"audio_b64": audio_b64, "language": language})


def cells():
    return _req("GET", "/cells")


def my_cell(household_id: str):
    return _req("GET", f"/farms/{household_id}/cell")


def cell_photo(lead_id: str, neighbour_id: str, image_b64: str):
    return _req("POST", f"/farms/{lead_id}/cell/photos", json={"neighbour_id": neighbour_id, "image_b64": image_b64},
                timeout=600)


def set_contact(household_id: str, officer_name: str, phone: str | None, phone_type: str | None, cell_id: str | None):
    return _req("POST", f"/farms/{household_id}/contact", json={"officer_name": officer_name, "phone": phone,
                                                                 "phone_type": phone_type, "cell_id": cell_id})


def integrations():
    return _req("GET", "/integrations", timeout=10)


def voice_calls(household_id: str | None = None):
    return _req("GET", "/voice/calls", params={"household_id": household_id} if household_id else None)


def retry_call(call_id: int):
    return _req("POST", f"/voice/calls/{call_id}/retry")


def simulate_call(call_id: int, answer: bool, digit: str | None):
    return _req("POST", f"/voice/calls/{call_id}/simulate", json={"answer": answer, "digit": digit})


# --- Accounts, institutions and billing (/api, Bearer token) --------------------------------------------------------
def _bearer(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def register(payload: dict):
    return _req("POST", "/api/auth/register", json=payload)


def login(email: str, password: str):
    return _req("POST", "/api/auth/login", json={"email": email, "password": password})


def me(token: str):
    return _req("GET", "/api/auth/me", headers=_bearer(token))


def institutions_public():
    return _req("GET", "/api/institutions")


def institution_officers(token: str):
    return _req("GET", "/api/institution/officers", headers=_bearer(token))


def pending_officers(token: str):
    return _req("GET", "/api/institution/officers/pending", headers=_bearer(token))


def decide_officer(token: str, officer_id: int, approve: bool):
    action = "approve" if approve else "reject"
    return _req("POST", f"/api/institution/officers/{officer_id}/{action}", headers=_bearer(token))


def add_officer(token: str, payload: dict):
    return _req("POST", "/api/institution/officers", headers=_bearer(token), json=payload)


def designate_lead_farmer(token: str, household_id: str):
    return _req("POST", "/api/institution/lead-farmers", headers=_bearer(token), json={"household_id": household_id})


def bulk_alert(token: str, sub_county: str, message: str, wards: list[str] | None = None):
    return _req("POST", "/api/institution/alerts/bulk", headers=_bearer(token),
                json={"sub_county": sub_county, "message": message, "wards": wards})


def escalations(token: str, status: str = "OPEN"):
    return _req("GET", "/api/escalations", headers=_bearer(token), params={"status": status})


def resolve_escalation(token: str, escalation_id: int, diagnosis: str):
    return _req("POST", f"/api/escalations/{escalation_id}/resolve", headers=_bearer(token),
                json={"diagnosis": diagnosis})


def subscription_overview(token: str):
    return _req("GET", "/api/institution/subscription", headers=_bearer(token))


def create_subscription(token: str, tier: str, seats: int, sub_counties: list[str] | None = None):
    return _req("POST", "/api/institution/subscriptions", headers=_bearer(token),
                json={"tier": tier, "seats": seats, "sub_counties": sub_counties})


def payments_status():
    return _req("GET", "/api/payments/status", timeout=10)


def mpesa_stkpush(token: str, subscription_id: int, phone: str, simulate_result: str = "success"):
    return _req("POST", "/api/payments/mpesa/stkpush", headers=_bearer(token), timeout=60,
                json={"subscription_id": subscription_id, "phone": phone, "simulate_result": simulate_result})


def card_checkout(token: str, subscription_id: int, simulate_result: str = "success"):
    return _req("POST", "/api/payments/card/checkout", headers=_bearer(token), timeout=60,
                json={"subscription_id": subscription_id, "simulate_result": simulate_result})


def transaction(token: str, transaction_id: int):
    return _req("GET", f"/api/payments/transactions/{transaction_id}", headers=_bearer(token))


def institution_farmers(token: str):
    return _req("GET", "/api/institution/farmers", headers=_bearer(token))

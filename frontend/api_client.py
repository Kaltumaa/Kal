"""Thin HTTP client. The frontend knows nothing about the backend except this URL."""
from __future__ import annotations

import os

import requests

API_URL = os.environ.get("CROP_PILOT_API", "http://127.0.0.1:8000")


class ApiError(RuntimeError):
    def __init__(self, status: int, detail):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def _req(method: str, path: str, timeout: float = 30, **kwargs):
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


def approve(advisory_id: int, officer_name: str, final_message: str | None, citation: str):
    return _req("POST", f"/advisories/{advisory_id}/approve",
                json={"officer_name": officer_name, "final_message": final_message, "citation": citation})


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
        r = requests.get(f"{API_URL}/scans/{scan_id}/image", timeout=15)
        return r.content if r.status_code == 200 else None
    except requests.RequestException:
        return None


def review_scan(scan_id: int, officer_name: str, decision: str, pest: str | None = None, severity: str = "MEDIUM",
                note: str = ""):
    return _req("POST", f"/scans/{scan_id}/review", json={"officer_name": officer_name, "decision": decision,
                                                          "pest": pest, "severity": severity, "note": note})


def forum_topics():
    return _req("GET", "/forum/topics")


def forum(topic: str | None = None):
    return _req("GET", "/forum", params={"topic": topic} if topic else None)


def forum_post(author: str, topic: str, body: str):
    return _req("POST", "/forum", json={"author": author, "topic": topic, "body": body})


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


def update_forecast(zone_id: str, rain_24h_mm: float, rain_72h_mm: float, rain_7d_mm: float, storm_risk: str):
    return _req("POST", f"/weather/{zone_id}", json={"rain_24h_mm": rain_24h_mm, "rain_72h_mm": rain_72h_mm,
                                                    "rain_7d_mm": rain_7d_mm, "storm_risk": storm_risk,
                                                    "source": "Officer-entered forecast update"})


def farms():
    return _req("GET", "/farms")


def farm_actions(household_id: str):
    return _req("GET", f"/farms/{household_id}/actions")


def log_farm_action(household_id: str, action: str, action_date: str, crop: str | None, details: str, role: str,
                    name: str | None):
    return _req("POST", f"/farms/{household_id}/actions", json={"action": action, "action_date": action_date,
                                                                "crop": crop, "details": details, "role": role,
                                                                "name": name})


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


def notifications(household_id: str):
    return _req("GET", f"/farms/{household_id}/notifications")


def problem(name: str):
    return _req("GET", "/knowledge/problem", params={"name": name})

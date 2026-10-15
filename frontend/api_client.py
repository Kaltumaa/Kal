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


def approve(advisory_id: int, officer_name: str, final_message: str | None):
    return _req("POST", f"/advisories/{advisory_id}/approve",
                json={"officer_name": officer_name, "final_message": final_message})


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

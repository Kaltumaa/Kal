"""The diagnosis agent: Plan -> Execute -> Self-check -> Recover, and it says when it does not know.

PLAN      a numbered plan is written first and every step's status is updated as the run goes.
EXECUTE   each tool call is retried on transient faults (timeouts, a crashed MCP server); a step that still fails
          gets a fallback (no outbreak data -> advise without it; one weather source down -> use the other; both
          down -> cached forecast; advisory tool down -> a safe "ask your officer" note).
SELF-CHECK before answering, the agent checks its own draft: is the photo usable and the model sure, are the two
          weather sources in agreement before any spray advice, does the advice respect the rain forecast, does it
          match the diagnosis, is the runner-up disease too close to call.
RECOVER   a problem it can fix (stale/disagreeing weather, advice inconsistent with the forecast) triggers one
          re-plan of that step; what it cannot fix is reported as uncertainty.
ADMIT     if anything is still uncertain the answer is UNCERTAIN: it says plainly "I'm not sure", gives no treatment
          it cannot stand behind, and queues the case for an extension officer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import mcp_server as plant
import weather as wx

PlantCall = Callable[[str, dict], Awaitable[dict]]
CLOSE_CALL_MARGIN = 0.15          # top-2 confidences closer than this = "could also be ..."
TRANSIENT_MARKERS = ("Timeout", "timed out", "ClosedResourceError", "BrokenResourceError", "Connection",
                     "McpError", "EOF", "unavailable")

PLAN = [
    ("diagnose", "Check the photo quality and run the leaf model (diagnose_crop_leaf)"),
    ("outbreak", "Check for a regional outbreak and log the case (check_regional_outbreak)"),
    ("weather", "Get the forecast from Open-Meteo and Visual Crossing and cross-check them"),
    ("advise", "Draft treatment advice that fits the diagnosis and the weather (draft_extension_advisory)"),
    ("self_check", "Check my own answer: photo, confidence, forecast agreement, rain vs spraying, consistency"),
    ("recover", "Fix what I can (re-fetch weather, re-draft advice); report what I can't as uncertainty"),
    ("human_gate", "Hold any outbreak alert, and any case I am unsure about, for a named extension officer"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS recovery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts TEXT NOT NULL, component TEXT NOT NULL,
    failure TEXT NOT NULL, action TEXT NOT NULL, used TEXT, attempts INTEGER NOT NULL DEFAULT 1);
-- Cases the agent was not sure about: an extension officer looks at them; the farmer got no guessed treatment.
CREATE TABLE IF NOT EXISTS review_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE, region TEXT NOT NULL, label TEXT,
    confidence REAL, reasons TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','DONE')),
    created_at TEXT NOT NULL, reviewed_by TEXT, diagnosis TEXT,
    CHECK (status = 'OPEN' OR (reviewed_by IS NOT NULL AND diagnosis IS NOT NULL)));
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Run:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.plan = [{"step": i, "id": sid, "goal": goal, "status": "pending"} for i, (sid, goal) in
                     enumerate(PLAN, start=1)]
        self.trace: list[dict] = []
        self.recovery: list[dict] = []
        self.uncertainty: list[dict] = []
        self.problems: list[str] = []

    def mark(self, sid: str, status: str, note: str | None = None) -> None:
        for p in self.plan:
            if p["id"] == sid:
                p["status"] = status
                if note:
                    p["note"] = note

    def recovered(self, component: str, failure: str, action: str, used: str | None = None, attempts: int = 1):
        event = {"component": component, "failure": failure[:300], "action": action, "used": used,
                 "attempts": attempts, "ts": _now()}
        self.recovery.append(event)
        with plant.db() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO recovery_log (run_id, ts, component, failure, action, used, attempts) "
                         "VALUES (?,?,?,?,?,?,?)", (self.run_id, event["ts"], component, event["failure"], action,
                                                    used, attempts))

    def unsure(self, code: str, detail: str) -> None:
        if not any(u["code"] == code for u in self.uncertainty):
            self.uncertainty.append({"code": code, "detail": detail})


def _transient(out: Any) -> bool:
    return isinstance(out, dict) and out.get("ok") is False and any(m in str(out.get("error")) for m in TRANSIENT_MARKERS)


async def call_with_retry(run: Run, call: PlantCall, tool: str, args: dict, attempts: int = 3) -> dict:
    """Retry transient faults only; a real answer (even ok=false for a bad photo) is returned as is."""
    failures = []
    out: dict = {"ok": False, "error": "not called"}
    for i in range(1, attempts + 1):
        out = await call(tool, args)
        run.trace.append({"step": len(run.trace) + 1, "tool": tool, "ok": bool(out.get("ok", True)),
                          "ms": out.pop("_ms", None), **({"attempt": i} if i > 1 else {})})
        if not _transient(out):
            break
        failures.append(str(out.get("error")))
    if failures:
        run.recovered(f"mcp:{tool}", "; ".join(failures), "retried" if not _transient(out) else "gave up after retries",
                      tool if not _transient(out) else None, len(failures) + (not _transient(out)))
    return out


def self_check(dx: dict, weather: dict, advisory: dict) -> tuple[list[dict], list[str]]:
    """(uncertainty it cannot fix, problems it can fix by re-planning). Deterministic."""
    unsure, fixable = [], []
    issues = dx.get("image_quality", {}).get("issues") or []
    if issues:
        unsure.append({"code": "photo_quality", "detail": f"the photo is {' and '.join(issues)}, so I cannot read "
                                                          "the leaf properly"})
    if dx.get("confidence", 0) < plant.CONFIDENCE_MIN:
        unsure.append({"code": "low_confidence", "detail": f"the model is only {dx['confidence']:.0%} sure it is "
                                                           f"{dx['label'].replace('__', ' ').replace('_', ' ')}"})
    preds = dx.get("predictions") or []
    if len(preds) >= 2 and preds[0]["confidence"] - preds[1]["confidence"] < CLOSE_CALL_MARGIN \
            and dx.get("confidence", 0) >= plant.CONFIDENCE_MIN:
        unsure.append({"code": "close_call", "detail": f"it could also be "
                                                       f"{preds[1]['label'].replace('__', ' ').replace('_', ' ')} "
                                                       f"({preds[1]['confidence']:.0%})"})
    treatment = advisory.get("treatment") or {}
    spray_advice = bool(treatment.get("chemical"))
    w = weather.get("summary") or {}
    if spray_advice and weather.get("agreement") == "DISAGREE":
        fixable.append("weather_disagreement")
    if treatment.get("spray_now_ok") and w and (w.get("hours_until_rain", 99) < wx.SPRAY_DRY_HOURS
                                                or not w.get("spray_window_ok", True)):
        fixable.append("advice_ignores_rain")
    if advisory.get("disease") and advisory["disease"] != dx.get("label"):
        fixable.append("advice_for_wrong_disease")
    if spray_advice and not weather.get("ok"):
        unsure.append({"code": "no_weather", "detail": "I have no weather forecast, so I cannot say if it is safe "
                                                       "to spray today"})
    return unsure, fixable


def _plain(label: str) -> str:
    return label.replace("__", " ").replace("_", " ")


async def run_diagnosis(req, call: PlantCall, get_weather: Callable[[float, float], Awaitable[dict]],
                        run_id: str) -> dict:
    run = Run(run_id)
    with plant.db() as conn:
        conn.executescript(SCHEMA)

    # 1. diagnose -------------------------------------------------------------------------------------------------
    dx = await call_with_retry(run, call, "diagnose_crop_leaf", {"image_base64": req.image_base64})
    if not dx.get("ok"):
        run.mark("diagnose", "failed", str(dx.get("error")))
        reason = str(dx.get("error"))
        return {"answer_status": "FAILED", "run_id": run_id, "plan": run.plan, "trace": run.trace,
                "recovery": run.recovery, "error": reason, "fixable_by_user": "model not found" not in reason,
                "message": ("I could not analyse this photo: " + reason + ". Please send a clear JPEG or PNG photo "
                            "of one leaf.") if "model not found" not in reason else
                           "I can't diagnose photos yet: the leaf model has not been installed."}
    run.mark("diagnose", "done", f"{_plain(dx['label'])} at {dx['confidence']:.0%}")

    # 2. outbreak ---------------------------------------------------------------------------------------------------
    outbreak = await call_with_retry(run, call, "check_regional_outbreak", {
        "region": req.region, "disease": dx["label"], "crop": req.crop or dx["crop"], "confidence": dx["confidence"],
        "lat": req.lat, "lon": req.lon, "record": bool(dx["confident"] and not dx["healthy"])})
    if outbreak.get("ok"):
        run.mark("outbreak", "done", f"{outbreak['level']}: {outbreak['cases_last_7d']} cases in 7 days")
    else:
        run.recovered("outbreak", str(outbreak.get("error")), "continued without outbreak data")
        run.mark("outbreak", "recovered", "outbreak data unavailable; advice given without it")
        outbreak = {"ok": False, "level": None, "spike": False, "error": outbreak.get("error")}

    # 3. weather ----------------------------------------------------------------------------------------------------
    async def fetch_weather() -> dict:
        if req.lat is None or req.lon is None:
            return {"ok": False, "agreement": "NO_DATA", "summary": None, "recovery": [],
                    "message": "No GPS location was sent, so I could not check the weather."}
        out = await get_weather(req.lat, req.lon)
        for ev in out.get("recovery", []):
            run.recovered(f"weather:{ev['component']}", ev["failure"], ev["action"], ev.get("used"), ev["attempts"])
        return out
    weather = await fetch_weather()
    run.trace.append({"step": len(run.trace) + 1, "tool": "weather:Open-Meteo+Visual Crossing", "ok": weather["ok"],
                      "ms": None, "agreement": weather.get("agreement")})
    run.mark("weather", "done" if weather.get("agreement") == "AGREE" else ("recovered" if weather["ok"] else "failed"),
             weather.get("agreement"))

    # 4. advise -----------------------------------------------------------------------------------------------------
    async def advise(w: dict, force_no_spray: bool = False) -> dict:
        hours = w.get("hours_until_rain")
        if force_no_spray:
            hours = 0                                   # cautious: treat the spray window as closed
        out = await call_with_retry(run, call, "draft_extension_advisory", {
            "disease_label": dx["label"], "confidence": dx["confidence"], "region": req.region,
            "crop": req.crop or dx["crop"], "outbreak_level": outbreak.get("level"),
            "rain_next_24h_mm": w.get("rain_next_24h_mm"), "rain_probability_max": w.get("rain_probability_max"),
            "hours_until_rain": hours, "image_issues": dx["image_quality"]["issues"]})
        if not out.get("ok"):
            run.recovered("advise", str(out.get("error")), "fallback to an 'ask your officer' note")
            out = {"ok": True, "status": "NEEDS_OFFICER_DIAGNOSIS", "treatment": None, "disease": dx["label"],
                   "message": "I could not prepare treatment advice right now. Please ask your extension officer.",
                   "fallback": True}
        return out
    advisory = await advise(weather.get("summary") or {})
    run.mark("advise", "done", advisory.get("status"))

    # 5. self-check, 6. recover (at most one re-plan) -----------------------------------------------------------------
    unsure, fixable = self_check(dx, weather, advisory)
    run.mark("self_check", "passed" if not unsure and not fixable else "flagged",
             "; ".join([u["code"] for u in unsure] + fixable) or None)
    recovered_steps = []
    if fixable:
        if "weather_disagreement" in fixable:          # forecasts may have updated: ask both again once
            weather = await fetch_weather()
            recovered_steps.append("re-fetched both forecasts")
        cautious = weather.get("agreement") == "DISAGREE"
        advisory = await advise(weather.get("summary") or {}, force_no_spray=cautious)
        recovered_steps.append("re-drafted the advice" + (" with spraying held back" if cautious else ""))
        unsure, fixable = self_check(dx, weather, advisory)
        if cautious:
            unsure.append({"code": "weather_disagreement",
                           "detail": "Open-Meteo and Visual Crossing disagree (" + "; ".join(
                               weather.get("disagreements") or []) + "), so I can't tell you it is safe to spray today"})
        for f in fixable:
            unsure.append({"code": f, "detail": f"my own check still fails: {f.replace('_', ' ')}"})
    for u in unsure:
        run.unsure(u["code"], u["detail"])
    run.mark("recover", "done" if recovered_steps else ("not_needed" if not run.recovery else "done"),
             "; ".join(recovered_steps) or None)

    # 7. human gate -----------------------------------------------------------------------------------------------
    status = "UNCERTAIN" if run.uncertainty else "CONFIDENT"
    review = None
    if status == "UNCERTAIN":
        review = _queue_review(run, req.region, dx)
    message = _answer(status, dx, advisory, run.uncertainty)
    return {"answer_status": status, "run_id": run_id, "message": message, "uncertainty": run.uncertainty,
            "diagnosis": {k: v for k, v in dx.items() if k != "ok"}, "outbreak": outbreak, "weather": weather,
            "advisory": advisory, "plan": run.plan, "trace": run.trace, "recovery": run.recovery,
            "review_request": review, "self_check": {"passed": not run.uncertainty, "recovered": recovered_steps}}


def _answer(status: str, dx: dict, advisory: dict, unsure: list[dict]) -> str:
    if status == "CONFIDENT":
        return advisory.get("message") or f"This looks like {_plain(dx['label'])}."
    guess = (f" My best guess is {_plain(dx['label'])} ({dx['confidence']:.0%}), but please don't act on it alone."
             if dx.get("confidence", 0) >= 0.3 else "")
    safe = ""
    treatment = advisory.get("treatment") or {}
    if treatment.get("immediate") and dx.get("confidence", 0) >= plant.CONFIDENCE_MIN:
        safe = f" Safe things to do now: {treatment['immediate']}"
    return (f"I'm not sure: {'; '.join(u['detail'] for u in unsure)}.{guess}{safe} I have asked an extension officer "
            "to check this case.")


def _queue_review(run: Run, region: str, dx: dict) -> dict:
    with plant.db() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO review_requests (run_id, region, label, confidence, reasons, created_at) "
                     "VALUES (?,?,?,?,?,?)", (run.run_id, plant._norm(region), dx.get("label"), dx.get("confidence"),
                                              json.dumps(run.uncertainty), _now()))
        row = conn.execute("SELECT * FROM review_requests WHERE run_id=?", (run.run_id,)).fetchone()
    run.mark("human_gate", "waiting", f"review request #{row['id']} for an extension officer")
    return {"id": row["id"], "status": row["status"]}

"""Deterministic agronomy: spray-safety index, pest threat scoring and the Plant/Spray/Hold rule engine.

These functions are the safety core. The language model never overrides them; it only explains them.
"""
from __future__ import annotations

import math
from datetime import date

from crop_pilot import config


# ---------------------------------------------------------------------------------- rainfall
def nearest_zone(lat: float, lon: float, zones: list[dict]) -> dict | None:
    if not zones:
        return None
    return min(zones, key=lambda z: haversine_km(lat, lon, z["centroid_lat"], z["centroid_lon"]))


def rainfall_outlook(weather: dict, today: date | None = None) -> dict:
    """Spray-safety index (0-100) and planting-window decision from a cached CHIRPS-style outlook."""
    today = today or config.today()
    r24 = max(0.0, float(weather.get("rain_24h_mm") or 0))
    r72 = max(r24, float(weather.get("rain_72h_mm") or 0))
    r7d = max(r72, float(weather.get("rain_7d_mm") or 0))
    storm = (weather.get("storm_risk") or "MODERATE").upper()
    runoff = min(1.0, max(0.0, float(weather.get("runoff_coeff") or 0.3)))

    # Wash-off: rain within 24 h of spraying is the main risk; 72 h rain matters more on high-runoff soils.
    penalty_24h = min(70.0, r24 * 7.0)
    penalty_72h = min(25.0, (r72 - r24) * 0.5 * (1 + runoff))
    penalty_storm = config.STORM_PENALTY.get(storm, 15)
    index = round(max(0.0, 100.0 - penalty_24h - penalty_72h - penalty_storm), 1)

    if index >= config.SPRAY_SAFE_MIN:
        spray_band = "SAFE"
    elif index >= config.SPRAY_CAUTION_MIN:
        spray_band = "CAUTION"
    else:
        spray_band = "UNSAFE"

    washout = r72 >= config.WASHOUT_RAIN_72H_MM or storm == "HIGH"
    planting_window = "OPEN" if (r7d >= config.PLANTING_RAIN_7D_MM and not washout) else "CLOSED"

    issued = weather.get("issued_at")
    try:
        age_days = (today - date.fromisoformat(str(issued)[:10])).days
    except ValueError:
        age_days = None
    stale = age_days is None or age_days > config.WEATHER_STALE_DAYS

    return {
        "zone_id": weather.get("zone_id"),
        "rain_24h_mm": r24, "rain_72h_mm": r72, "rain_7d_mm": r7d,
        "storm_risk": storm, "runoff_coeff": runoff,
        "spray_safety_index": index,
        "spray_band": spray_band,
        "washout_risk": washout,
        "planting_window": planting_window,
        "forecast_issued_at": issued,
        "forecast_age_days": age_days,
        "stale": stale,
        "formula": "100 - min(70, 7*r24) - min(25, 0.5*(r72-r24)*(1+runoff)) - storm_penalty",
        "source": weather.get("source"),
    }


# ---------------------------------------------------------------------------------- pests
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def score_pest_alerts(alerts: list[dict], lat: float | None, lon: float | None,
                      crop: str | None, stage: str | None, today: date | None = None) -> dict:
    """Score VERIFIED alerts by severity x distance decay x recency decay."""
    today = today or config.today()
    scored, ignored = [], []
    for alert in alerts:
        pest = (alert.get("pest") or "").strip().lower()
        if not alert.get("verified"):
            ignored.append({"id": alert["id"], "reason": "unverified"})
            continue
        try:
            age = (today - date.fromisoformat(str(alert["reported_at"])[:10])).days
        except ValueError:
            ignored.append({"id": alert["id"], "reason": "unreadable date"})
            continue
        if age > config.PEST_MAX_AGE_DAYS or age < 0:
            ignored.append({"id": alert["id"], "reason": f"report age {age} days outside window"})
            continue

        if None not in (lat, lon, alert.get("lat"), alert.get("lon")):
            distance = haversine_km(lat, lon, alert["lat"], alert["lon"])
            distance_method = "haversine"
        elif alert.get("distance_km") is not None:
            distance = float(alert["distance_km"])
            distance_method = "registry distance index"
        else:
            ignored.append({"id": alert["id"], "reason": "no location"})
            continue

        radius = config.PEST_RADIUS_KM.get(pest, config.DEFAULT_PEST_RADIUS_KM)
        proximity = max(0.0, 1 - distance / radius)
        recency = 0.5 ** (age / config.PEST_RECENCY_HALF_LIFE_DAYS)
        score = round(config.SEVERITY_WEIGHT.get(alert.get("severity", "LOW"), 0.3) * proximity * recency, 3)
        susceptible = stage in config.PEST_SUSCEPTIBILITY.get(pest, {}).get(crop or "", set())
        scored.append({
            "id": alert["id"], "pest": alert["pest"], "severity": alert.get("severity"),
            "distance_km": round(distance, 2), "distance_method": distance_method,
            "action_radius_km": radius, "within_radius": distance <= radius,
            "age_days": age, "threat_score": score, "crop_susceptible": susceptible,
            "actionable": distance <= radius and susceptible and score >= config.PEST_ACTION_SCORE,
            "source": alert.get("source"),
        })
    scored.sort(key=lambda a: a["threat_score"], reverse=True)
    actionable = [a for a in scored if a["actionable"]]
    return {
        "verified_alerts": scored,
        "ignored_alerts": ignored,
        "top_threat": actionable[0] if actionable else None,
        "action_required": bool(actionable),
        "formula": "severity_weight * max(0, 1 - distance/radius) * 0.5^(age/14)",
    }


# ---------------------------------------------------------------------------------- planting by crop
def planting_threshold(crop: str | None) -> float:
    return config.PLANTING_RAIN_BY_CROP.get(crop or "", config.PLANTING_RAIN_7D_MM)


def crops_plantable_now(rain_7d_mm: float, washout: bool) -> list[str]:
    """Crops whose sowing rain threshold is met this week (none during a washout)."""
    if washout:
        return []
    main = ["Maize", "Beans", "Potato", "Kale"]
    candidates = {c: config.PLANTING_RAIN_7D_MM for c in main} | config.PLANTING_RAIN_BY_CROP
    return [c for c, need in sorted(candidates.items(), key=lambda kv: kv[1]) if rain_7d_mm >= need]


# ---------------------------------------------------------------------------------- rule engine
def decide(plot: dict, rain: dict | None, pests: dict | None) -> dict:
    """The safe verdict. Ordered rules; first match wins. Returns verdict, status and reasons."""
    reasons: list[str] = []
    if not plot.get("found") or not plot.get("profile_complete"):
        return {"status": "NEEDS_DATA", "verdict": None, "rule": "R0_missing_profile",
                "reasons": ["Household profile is missing a crop or zone; schedule a field visit."]}
    if plot.get("injection_detected"):
        return {"status": "SECURITY_LOCK", "verdict": "HOLD", "rule": "R1_injection_lock",
                "reasons": ["Instruction-like text was found in the household record; locked for officer review."]}
    if rain is None:
        return {"status": "NEEDS_DATA", "verdict": None, "rule": "R0_missing_weather",
                "reasons": ["No rainfall outlook for this zone."]}

    threat = (pests or {}).get("top_threat")
    stage = plot.get("growth_stage")

    if rain["washout_risk"] or rain["spray_band"] == "UNSAFE":
        reasons.append(f"Rain {rain['rain_72h_mm']} mm/72 h, storm risk {rain['storm_risk']}, "
                       f"spray-safety index {rain['spray_safety_index']} ({rain['spray_band']}).")
        if threat:
            reasons.append(f"Verified {threat['pest']} {threat['distance_km']} km away: spray once the window opens.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R2_washout_hold", "reasons": reasons}

    if threat:
        reasons.append(f"Verified {threat['pest']} ({threat['severity']}) {threat['distance_km']} km away, "
                       f"{threat['age_days']} days old; crop stage {stage} is susceptible.")
        reasons.append(f"Spray-safety index {rain['spray_safety_index']} ({rain['spray_band']}).")
        return {"status": "PENDING_REVIEW", "verdict": "SPRAY", "rule": "R3_threat_spray", "reasons": reasons}

    if stage == "PRE_PLANTING":
        crop = plot.get("active_crop")
        need = planting_threshold(crop)
        if not rain["washout_risk"] and rain["rain_7d_mm"] >= need:
            reasons.append(f"{rain['rain_7d_mm']} mm expected over 7 days; {crop} needs about {need:.0f} mm to "
                           f"establish, and there is no washout risk.")
            return {"status": "PENDING_REVIEW", "verdict": "PLANT", "rule": "R4_planting_window", "reasons": reasons}
        reasons.append(f"Only {rain['rain_7d_mm']} mm expected over 7 days; {crop} needs about {need:.0f} mm. "
                       f"Wait for the rains.")
        alternatives = [c for c in crops_plantable_now(rain["rain_7d_mm"], rain["washout_risk"]) if c != crop]
        if alternatives:
            reasons.append(f"Drought-tolerant options that could go in now: {', '.join(alternatives)}.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R5_wait_for_onset", "reasons": reasons}

    reasons.append(f"No actionable verified pest threat; crop at {stage}. Continue routine scouting.")
    return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R6_monitor", "reasons": reasons}

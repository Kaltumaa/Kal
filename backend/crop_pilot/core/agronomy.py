"""Deterministic agronomy: spray-safety index, pest threat scoring and the Plant/Spray/Hold rule engine.

These functions are the safety core. The language model never overrides them; it only explains them.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from functools import lru_cache

from crop_pilot import config


# ---------------------------------------------------------------------------------- rainfall
_CODE_WORDS = re.compile(r"\b(?:[A-Z]{2,}(?:_[A-Z]+)+|OPEN|CLOSED|UNSAFE|SAFE|CAUTION|EMERGENCE|VEGETATIVE|FLOWERING|"
                         r"MATURITY|ESTABLISHMENT)\b")


def plain_terms(text: str | None) -> str:
    """Internal codes as words, in any text a person reads: 'GRAIN_FILL' -> 'grain fill', 'OPEN' -> 'open'.
    The small model copies these from its evidence. PLANT, SPRAY and HOLD are verdicts and stay as they are."""
    return _CODE_WORDS.sub(lambda m: m.group(0).replace("_", " ").lower(), text or "")


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
    wind = weather.get("wind_kmh")
    wind = None if wind is None else max(0.0, float(wind))
    peak = weather.get("peak_rain_mm_h")
    peak = None if peak is None else max(0.0, float(peak))
    dry_hours = weather.get("dry_hours_ahead")
    dry_hours = None if dry_hours is None else max(0.0, float(dry_hours))
    rain_soon = dry_hours is not None and dry_hours < config.SPRAY_DRY_HOURS
    dry_ahead = weather.get("dry_spell_days_ahead")
    dry_ahead = None if dry_ahead is None else max(0.0, float(dry_ahead))

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
    too_windy = wind is not None and wind > config.SPRAY_MAX_WIND_KMH
    # One answer to "can you spray?" for every page: rain first, then wind (same order as decide()).
    if spray_band == "UNSAFE":
        spray_status, spray_label = "NO_RAIN", "Don't spray (rain)"
    elif rain_soon:
        spray_status, spray_label = "RAIN_SOON", f"Rain due in {dry_hours:.0f} h"
    elif too_windy:
        spray_status, spray_label = "NO_WIND", f"Too windy ({wind:.0f} km/h)"
    elif spray_band == "CAUTION":
        spray_status, spray_label = "CAREFUL", "Careful: only if no rain for 6 h"
    else:
        spray_status, spray_label = "OK", "OK"

    return {
        "zone_id": weather.get("zone_id"),
        "rain_24h_mm": r24, "rain_72h_mm": r72, "rain_7d_mm": r7d,
        "storm_risk": storm, "runoff_coeff": runoff,
        "wind_kmh": wind, "wind_too_strong": too_windy,
        "peak_rain_mm_h": peak, "peak_rain_at": weather.get("peak_rain_at"),
        "crust_risk": peak is not None and peak >= config.CRUST_RAIN_MM_H,
        "dry_spell_days_ahead": dry_ahead,
        "dry_hours_ahead": dry_hours, "rain_soon": rain_soon,
        "spray_status": spray_status, "spray_label": spray_label,
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
def _latest(log: list[dict], action: str) -> dict | None:
    rows = [e for e in log if e.get("action") == action and e.get("action_date")]
    return max(rows, key=lambda e: (e["action_date"], e.get("id") or 0)) if rows else None


def weeds_uncleared(field_log: list[dict] | None) -> dict | None:
    """The farmer's latest observation answered "needs weeding: yes" and no weeding has been logged since.

    Uses the structured yes/no answer only; free-text notes are never read ("weeding done" or "no weeds" must not
    block planting).
    """
    log = field_log or []
    answered = [e for e in log if e.get("action") == "OBSERVATION" and e.get("needs_weeding") is not None
                and e.get("action_date")]
    if not answered:
        return None
    obs = max(answered, key=lambda e: (e["action_date"], e.get("id") or 0))
    if not obs["needs_weeding"]:
        return None
    weeding = _latest(log, "WEEDING")
    return None if weeding and weeding["action_date"] >= obs["action_date"] else obs


def group_kind(group: str | None) -> str | None:
    """IRAC groups (and Bt / neem) are insect sprays; FRAC groups are disease sprays."""
    if not group or group == "Not sure":
        return None
    return "disease" if "FRAC" in group else "insect"


@lru_cache(maxsize=1)
def _pest_types() -> dict[str, str]:
    data = json.loads((config.REFERENCE_DIR / "pest_symptoms.json").read_text(encoding="utf-8"))
    return {name.lower(): info.get("type", "") for name, info in data.items()}


def threat_kind(pest: str | None) -> str | None:
    """'insect' for pests, 'disease' for diseases (from the reference guide); None if unknown."""
    kind = _pest_types().get((pest or "").lower())
    return {"Pest": "insect", "Disease": "disease"}.get(kind)


def chemical_rotation(field_log: list[dict] | None, today: date | None = None, kind: str | None = None,
                      pest: str | None = None) -> dict | None:
    """Mode-of-action group of the last logged spray of the same kind (within a year), and whether it was used
    twice in a row. `kind` is 'insect' or 'disease'; a fungicide says nothing about which insecticide to use next."""
    today = today or config.today()
    sprays = sorted((e for e in field_log or [] if e.get("action") == "SPRAYING" and group_kind(e.get("chem_group"))
                     and (kind is None or group_kind(e["chem_group"]) == kind) and e.get("action_date")
                     and (today - date.fromisoformat(e["action_date"][:10])).days <= 365),
                    key=lambda e: (e["action_date"], e.get("id") or 0), reverse=True)
    if not sprays:
        return None
    last = sprays[0]
    repeated = len(sprays) > 1 and sprays[1]["chem_group"] == last["chem_group"]
    what = {"insect": "insect spray", "disease": "disease spray"}.get(group_kind(last["chem_group"]), "spray")
    note = (f"The last {what} ({last['action_date'][:10]}) used {last['chem_group']}"
            + (", twice in a row" if repeated else "")
            + ". Use a product from a different group this time to slow resistance")
    listed = config.PEST_GROUPS.get((pest or "").lower(), [])
    others = [g for g in listed if g != last["chem_group"]]
    if others:
        note += f". For {pest}, the desk guide lists: {', '.join(others)}"
        if last["chem_group"] not in listed:
            note += f" ({last['chem_group']} is not on that list)"
    note += ". Check the PCPB label with the officer."
    return {"group": last["chem_group"], "date": last["action_date"][:10], "repeated": repeated, "note": note,
            "citation": f"plot_actions:#{last['id']}" if last.get("id") else None}


# A short name for each verdict, shown to the officer above the reasons ("HOLD: Deceptive false start").
RULE_TITLES = {
    "R1_injection_lock": "Record locked", "R2_washout_hold": "Washout risk",
    "R2b_wind_hold": "Too windy: drift risk to neighbours", "R2c_rain_soon_hold": "Rain due: spray would wash off",
    "R6c_risk_window": "Pest risk window: scout",
    "R3_threat_spray": "Confirmed pest nearby", "R4_planting_window": "Planting window open",
    "R4b_clear_weeds_first": "Vegetation moisture trap", "R4c_false_start_hold": "Deceptive false start",
    "R4e_waterlog_hold": "Waterlogging risk", "R4f_crust_hold": "Hold seeding: violent storm forecast",
    "R4g_soil_dry_hold": "Soil not moist yet", "R4h_unverified_seed": "Unverified seed",
    "R5_wait_for_onset": "Rains not started", "R6b_scout_soon": "Scout soon", "R6_monitor": "Keep monitoring",
}


def storm_coming(rain: dict, today: date | None = None) -> dict | None:
    """A violent downpour (peak rain per hour at or above the crusting line) forecast for today or the next 2 days."""
    today = today or config.today()
    peak, at = rain.get("peak_rain_mm_h"), str(rain.get("peak_rain_at") or "")[:10]
    try:
        days = (date.fromisoformat(at) - today).days
    except ValueError:
        return None
    if peak is None or peak < config.CRUST_RAIN_MM_H or not 0 <= days <= 2:
        return None
    return {"mm_h": peak, "date": at}


def storm_since(rain: dict, since: str | None, today: date | None = None) -> dict | None:
    """A violent downpour that already fell on or after `since` (e.g. the sowing date)."""
    today = today or config.today()
    peak, at = rain.get("peak_rain_mm_h"), str(rain.get("peak_rain_at") or "")[:10]
    if peak is None or peak < config.CRUST_RAIN_MM_H or not at or not since or at < since[:10] \
            or at > today.isoformat():
        return None
    return {"mm_h": peak, "date": at}


def seed_label_check(field_log: list[dict] | None) -> dict | None:
    """The latest seed or planting entry that records a KEPHIS label check (VERIFIED, FAILED or NOT_CHECKED)."""
    rows = [e for e in field_log or [] if e.get("action") in ("VARIETY", "PLANTING") and e.get("seed_check")
            and e.get("action_date")]
    return max(rows, key=lambda e: (e["action_date"], e.get("id") or 0)) if rows else None


def soil_moisture_check(field_log: list[dict] | None, today: date | None = None) -> dict | None:
    """The farmer's latest "soil moist to a hand's depth?" answer from the last few days (older answers are stale)."""
    today = today or config.today()
    answered = [e for e in field_log or [] if e.get("action") == "OBSERVATION" and e.get("soil_moist") is not None
                and e.get("action_date")
                and 0 <= (today - date.fromisoformat(e["action_date"][:10])).days <= config.SOIL_CHECK_FRESH_DAYS]
    return max(answered, key=lambda e: (e["action_date"], e.get("id") or 0)) if answered else None


CEREALS, LEGUMES = {"Maize", "Sorghum"}, {"Beans", "Cowpeas", "Groundnut"}


def intercrop_tip(plot: dict, pattern: dict | None) -> str | None:
    """Layout advice for a plot that grows two crops together, by season. A tip only: it never changes the verdict."""
    pair = {plot.get("active_crop"), plot.get("intercrop")}
    cereal, legume = next(iter(pair & CEREALS), None), next(iter(pair & LEGUMES), None)
    season = (pattern or {}).get("season_class")
    if not (plot.get("intercrop") and cereal and legume) or season not in ("BELOW", "ABOVE"):
        return None
    c, l = cereal.lower(), legume.lower()
    if season == "BELOW":
        return (f"Low-rain season for this {c} and {l} plot: keep the usual layout (one {l} row between the {c} "
                f"rows) and do not add extra plants, because in a dry season they compete for water. Choose "
                f"early-maturing seed for both and mulch between the rows to keep moisture in.")
    return (f"Wet season for this {c} and {l} plot: keep one {l} row between the {c} rows, not crowded, so air "
            f"moves through and {l} diseases stay down.")


def decide(plot: dict, rain: dict | None, pests: dict | None, *, pattern: dict | None = None,
           field_log: list[dict] | None = None) -> dict:
    """The safe verdict. Ordered rules; first match wins. Returns verdict, status, rule, title and reasons.

    `pattern` (get_weather_pattern), `field_log` (the farm's own log) and the plot's slope and soil are optional;
    without them the rules behave exactly as before.
    """
    out = _decide(plot, rain, pests, pattern=pattern, field_log=field_log)
    if out["verdict"] and out["status"] == "PENDING_REVIEW" and plot.get("growth_stage") == "PRE_PLANTING":
        tip = intercrop_tip(plot, pattern)
        if tip:
            out["reasons"].append(tip)
    # A violent downpour right after sowing can crust the soil over the seed: tell the officer to check emergence.
    if out["status"] == "PENDING_REVIEW" and rain and plot.get("growth_stage") == "EMERGENCE":
        hit = storm_since(rain, plot.get("planting_date"))
        if hit:
            out["reasons"].append(f"A violent downpour ({hit['mm_h']:.0f} mm in an hour, {hit['date']}) fell after "
                                  "sowing: check the seedlings are coming through, and gently break any crust "
                                  "between the rows.")
    return out | {"title": RULE_TITLES.get(out["rule"], "Needs data")}


def _decide(plot: dict, rain: dict | None, pests: dict | None, *, pattern: dict | None = None,
            field_log: list[dict] | None = None) -> dict:
    reasons: list[str] = []
    pattern = pattern or {}
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
        if stage == "PRE_PLANTING" and rain["storm_risk"] == "HIGH":
            reasons.append("Sow after the storms pass: heavy rain on newly sown soil can crust it over the seed.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R2_washout_hold", "reasons": reasons}

    if threat and rain.get("rain_soon"):
        reasons.append(f"Verified {threat['pest']} ({threat['severity']}) {threat['distance_km']} km away, but rain is "
                       f"forecast in about {rain['dry_hours_ahead']:.0f} hours. A spray needs at least "
                       f"{config.SPRAY_DRY_HOURS} dry hours to dry on the leaves, or it washes off and the money is lost.")
        reasons.append("Spray when at least 6 dry hours are forecast; check the label's rain-fast time.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R2c_rain_soon_hold", "reasons": reasons}

    if threat and rain.get("wind_too_strong"):
        reasons.append(f"Verified {threat['pest']} ({threat['severity']}) {threat['distance_km']} km away, but wind "
                       f"is {rain['wind_kmh']:.0f} km/h (spray only below {config.SPRAY_MAX_WIND_KMH:.0f} km/h). "
                       "Spray would drift onto neighbours' crops, beehives and water.")
        reasons.append("Spray early in the morning once the wind drops.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R2b_wind_hold", "reasons": reasons}

    if threat:
        reasons.append(f"Verified {threat['pest']} ({threat['severity']}) {threat['distance_km']} km away, "
                       f"{threat['age_days']} days old; crop stage {plain_terms(stage)} is susceptible.")
        reasons.append(f"Spray-safety index {rain['spray_safety_index']} ({rain['spray_band']}).")
        kind = threat_kind(threat["pest"])
        rot = chemical_rotation(field_log, kind=kind, pest=threat["pest"]) if kind else None
        if rot:
            reasons.append(rot["note"])
        return {"status": "PENDING_REVIEW", "verdict": "SPRAY", "rule": "R3_threat_spray", "reasons": reasons}

    if stage == "PRE_PLANTING":
        crop = plot.get("active_crop")
        need = planting_threshold(crop)
        seed = seed_label_check(field_log)
        if seed and seed["seed_check"] == "FAILED":
            reasons.append(f"The farm's log ({seed['action_date'][:10]}) says the seed packet's KEPHIS label did not "
                           "verify (no reply, or the wrong variety or producer). It may be fake seed that will not "
                           "germinate: do not plant it. Return it to the agro-dealer, report it to KEPHIS, and use "
                           "seed whose label verifies.")
            return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R4h_unverified_seed", "reasons": reasons}
        if not rain["washout_risk"] and rain["rain_7d_mm"] >= need:
            dry_ahead = rain.get("dry_spell_days_ahead")
            if dry_ahead is not None and dry_ahead >= config.FALSE_START_DRY_SPELL_DAYS:
                reasons.append(f"{rain['rain_7d_mm']} mm expected this week, but the 2-week outlook shows about "
                               f"{dry_ahead:.0f} dry days after it. Seed that germinates now would dry out: this looks "
                               "like a false start. Wait until the outlook shows the rains continuing.")
                return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R4c_false_start_hold",
                        "reasons": reasons}
            weedy = weeds_uncleared(field_log)
            if weedy:
                reasons.append(f"Rain is enough to plant, but the farm's own log ({weedy['action_date'][:10]}) says "
                               "the plot needs weeding. Weeds take the topsoil moisture new seed needs: clear them "
                               "first, then plant.")
                return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R4b_clear_weeds_first",
                        "reasons": reasons}
            storm = storm_coming(rain)
            if storm:
                reasons.append(f"Rain is enough to plant, but a violent downpour (about {storm['mm_h']:.0f} mm in an "
                               f"hour) is forecast for {storm['date']}. Rain that hard on newly sown soil seals it into "
                               "a crust that seedlings cannot push through. Sow just after the storm passes.")
                return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R4f_crust_hold", "reasons": reasons}
            moist = soil_moisture_check(field_log)
            if moist and not moist["soil_moist"]:
                reasons.append(f"Rain is forecast, but the farm's own check ({moist['action_date'][:10]}) says the soil "
                               "is not yet moist to a hand's depth (about 15 cm). Seed in dry soil can sprout on a "
                               "little moisture and then die. Plant once the soil is moist that deep.")
                return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R4g_soil_dry_hold",
                        "reasons": reasons}
            slope, soil = plot.get("slope"), plot.get("soil")
            if soil in config.WATERLOG_SOILS and slope in (None, "flat") \
                    and rain["rain_7d_mm"] >= config.WATERLOG_RAIN_7D_MM:
                reasons.append(f"{rain['rain_7d_mm']} mm expected this week on {'flat ' if slope else ''}{soil} soil, "
                               "which drains slowly: the plot is likely to waterlog and seed can rot in wet soil.")
                reasons.append("Wait for 2 to 3 dry days after the heavy rain, or plant on raised beds or ridges.")
                return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R4e_waterlog_hold", "reasons": reasons}
            reasons.append(f"{rain['rain_7d_mm']} mm expected over 7 days; {crop} needs about {need:.0f} mm to "
                           f"establish, and there is no washout risk.")
            if moist and moist["soil_moist"]:
                reasons.append(f"The farm's own check ({moist['action_date'][:10]}): soil moist to a hand's depth.")
            else:
                reasons.append("Before sowing, check the soil is moist to a hand's depth (about 15 cm).")
            if slope in config.SLOPE_ADVICE:
                reasons.append(config.SLOPE_ADVICE[slope])
            if soil in config.WATERLOG_SOILS:
                reasons.append(f"{soil.capitalize()} soil drains slowly: ridges help if heavy rain follows.")
            elif soil == "sandy loam":
                reasons.append("Sandy soil dries fast: mulch after planting to keep the moisture in.")
            if pattern.get("onset") == "FALSE_START_RISK":
                reasons.append("The rains follow a dry spell (false-start risk): plant part of the plot now and the "
                               "rest after a second wet week.")
            if seed and seed["seed_check"] == "VERIFIED":
                reasons.append(f"Seed label verified with KEPHIS ({seed['action_date'][:10]}).")
            else:
                reasons.append("Use certified seed: scratch the KEPHIS label on the packet and SMS the code to the "
                               "number on it (1393 on most labels). The reply should name the variety, producer and "
                               "lot; if it does not, do not plant that seed.")
            return {"status": "PENDING_REVIEW", "verdict": "PLANT", "rule": "R4_planting_window", "reasons": reasons}
        reasons.append(f"Only {rain['rain_7d_mm']} mm expected over 7 days; {crop} needs about {need:.0f} mm. "
                       f"Wait for the rains.")
        alternatives = [c for c in crops_plantable_now(rain["rain_7d_mm"], rain["washout_risk"]) if c != crop]
        if alternatives:
            reasons.append(f"Drought-tolerant options that could go in now: {', '.join(alternatives)}.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R5_wait_for_onset", "reasons": reasons}

    near = [a for a in (pests or {}).get("verified_alerts", [])
            if a.get("crop_susceptible") and not a.get("actionable") and a["distance_km"] <= 2 * a["action_radius_km"]]
    if near:
        a0 = near[0]
        reasons.append(f"Verified {a0['pest']} {a0['distance_km']} km away: outside the {a0['action_radius_km']:.0f} km "
                       f"action radius, but close enough to scout this week. Do not spray yet.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R6b_scout_soon", "reasons": reasons}

    watch = [p for p, crops in config.PEST_SUSCEPTIBILITY.items() if stage in crops.get(plot.get("active_crop"), set())]
    if watch:
        pest = watch[0]
        reasons.append(f"{plot.get('active_crop')} at {plain_terms(stage)} is in the {pest.title()} risk window, but no confirmed "
                       f"report is near. Do not spray ahead of the pest: {config.SCOUT_ADVICE.get(pest, 'scout twice a week')}.")
        return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R6c_risk_window", "reasons": reasons}
    reasons.append(f"No actionable verified pest threat; crop at {plain_terms(stage)}. Continue routine scouting.")
    return {"status": "PENDING_REVIEW", "verdict": "HOLD", "rule": "R6_monitor", "reasons": reasons}

"""Dual-source live weather for a ward's GPS point: Open-Meteo (primary, keyless) and Visual Crossing (secondary).

Both are asked, each with retries. Their 7-day hourly forecasts are reduced to the numbers the spray and planting
rules use (rain over 24 h / 72 h / 7 days, rain probability, humidity, wind, hours until the next rain) and then
CROSS-VERIFIED: if they disagree significantly on rainfall or the spray window, the agent must not advise a spray on
them (it escalates to the sub-county officer instead).

Recovery, in order, all logged to `recovery_log`:
  1. a provider that times out or errors is retried (config.WEATHER_RETRIES attempts);
  2. if one provider still fails, the other one is used alone (failover; SINGLE_SOURCE, cannot be cross-verified);
  3. if both fail, the last good live forecast for the ward (< WEATHER_LIVE_CACHE_HOURS old) is used;
  4. otherwise the cached sub-county climate baseline (weather_cache outlook + CHIRPS dekadal normal) is used.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from crop_pilot import config
from crop_pilot.core import agronomy, sanitizer, weather_patterns
from crop_pilot.core.resilience import log_recovery, with_retry
from crop_pilot.core.telemetry import now_iso
from crop_pilot.database.db import connect

TZ = ZoneInfo("Africa/Nairobi")
WET_HOUR_MM = 0.2          # an hour with at least this much rain ends the dry (spray) window
PRIMARY, SECONDARY = "open_meteo", "visual_crossing"
LABELS = {PRIMARY: "Open-Meteo", SECONDARY: "Visual Crossing"}


class ProviderError(RuntimeError):
    pass


def status() -> dict:
    return {"live": config.LIVE_WEATHER, "primary": "Open-Meteo (keyless)",
            "secondary": "Visual Crossing" + ("" if config.VISUAL_CROSSING_API_KEY else " (no key: off)")}


# --- providers ----------------------------------------------------------------------------------------------------
def _local_now() -> datetime:
    return datetime.now(TZ).replace(minute=0, second=0, microsecond=0, tzinfo=None)


def fetch_open_meteo(lat: float, lon: float, client: httpx.Client | None = None) -> list[dict]:
    params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "Africa/Nairobi", "forecast_days": 7,
              "hourly": "precipitation,precipitation_probability,relative_humidity_2m,wind_speed_10m",
              "wind_speed_unit": "kmh"}
    with (client or httpx.Client(timeout=config.WEATHER_TIMEOUT_S)) as c:
        r = c.get(config.OPEN_METEO_URL, params=params)
    if r.status_code != 200:
        raise ProviderError(f"Open-Meteo HTTP {r.status_code}")
    h = r.json().get("hourly") or {}
    times = h.get("time") or []
    if not times:
        raise ProviderError("Open-Meteo returned no hourly data")
    col = lambda k: h.get(k) or [None] * len(times)   # noqa: E731
    return [{"time": t, "precip_mm": p, "prob": pr, "humidity": hu, "wind_kmh": w}
            for t, p, pr, hu, w in zip(times, col("precipitation"), col("precipitation_probability"),
                                       col("relative_humidity_2m"), col("wind_speed_10m"))]


def fetch_visual_crossing(lat: float, lon: float, client: httpx.Client | None = None) -> tuple[list[dict], list[dict]]:
    if not config.VISUAL_CROSSING_API_KEY:
        raise ProviderError("VISUAL_CROSSING_API_KEY is not set")
    url = f"{config.VISUAL_CROSSING_URL}/{round(lat, 4)},{round(lon, 4)}/next7days"
    params = {"unitGroup": "metric", "include": "hours,alerts", "contentType": "json",
              "elements": "datetime,precip,precipprob,humidity,windspeed", "key": config.VISUAL_CROSSING_API_KEY}
    with (client or httpx.Client(timeout=config.WEATHER_TIMEOUT_S)) as c:
        r = c.get(url, params=params)
    if r.status_code != 200:
        raise ProviderError(f"Visual Crossing HTTP {r.status_code}")
    data = r.json()
    hours = []
    for day in data.get("days") or []:
        for hr in day.get("hours") or []:
            hours.append({"time": f"{day['datetime']}T{hr['datetime'][:5]}", "precip_mm": hr.get("precip"),
                          "prob": hr.get("precipprob"), "humidity": hr.get("humidity"), "wind_kmh": hr.get("windspeed")})
    if not hours:
        raise ProviderError("Visual Crossing returned no hourly data")
    alerts = [{"source": LABELS[SECONDARY], "event": sanitizer.scrub_free_text(a.get("event"), 80)[0],
               "headline": sanitizer.scrub_free_text(a.get("headline"), 200)[0]} for a in data.get("alerts") or []]
    return hours, alerts


def summarise(hours: list[dict], now: datetime | None = None) -> dict:
    """The rule-relevant numbers from an hourly forecast, starting at the current local hour."""
    now = now or _local_now()
    ahead = []
    for h in hours:
        try:
            t = datetime.fromisoformat(str(h["time"])[:16])
        except ValueError:
            continue
        if t >= now:
            ahead.append(h)
    if len(ahead) < 24:
        raise ProviderError("forecast covers less than the next 24 hours")
    num = lambda v: float(v) if isinstance(v, (int, float)) else 0.0   # noqa: E731
    rain = [max(0.0, num(h["precip_mm"])) for h in ahead]
    prob = [num(h["prob"]) for h in ahead[:24]]
    hum = [num(h["humidity"]) for h in ahead[:24] if h["humidity"] is not None]
    wind = [num(h["wind_kmh"]) for h in ahead[:24]]
    dry = next((i for i, mm in enumerate(rain) if mm >= WET_HOUR_MM), len(rain))
    out = {"rain_24h_mm": round(sum(rain[:24]), 1), "rain_72h_mm": round(sum(rain[:72]), 1),
           "rain_7d_mm": round(sum(rain[:168]), 1), "rain_prob_24h_max": round(max(prob or [0]), 0),
           "humidity_24h_mean": round(sum(hum) / len(hum), 0) if hum else None,
           "wind_24h_max_kmh": round(max(wind or [0]), 1), "wind_spray_window_kmh": round(max(wind[:6] or [0]), 1),
           "dry_hours_ahead": dry, "hours": len(ahead)}
    out["spray_window_ok"] = (dry >= config.SPRAY_DRY_HOURS and out["wind_spray_window_kmh"] <= config.SPRAY_MAX_WIND_KMH)
    out["alerts"] = severe_alerts(out)
    return out


def severe_alerts(f: dict) -> list[dict]:
    alerts = []
    if f["rain_72h_mm"] >= config.WASHOUT_RAIN_72H_MM:
        alerts.append({"event": "WASHOUT_RISK", "headline": f"{f['rain_72h_mm']} mm in 72 h: fertiliser and sprays "
                                                            "will wash off; seed may rot"})
    if f["rain_24h_mm"] >= config.SEVERE_RAIN_24H_MM:
        alerts.append({"event": "HEAVY_RAIN", "headline": f"{f['rain_24h_mm']} mm in the next 24 h"})
    if f["wind_24h_max_kmh"] >= config.SEVERE_WIND_KMH:
        alerts.append({"event": "DAMAGING_WIND", "headline": f"gusts to {f['wind_24h_max_kmh']} km/h"})
    if (f.get("humidity_24h_mean") or 0) >= 90 and f["rain_72h_mm"] >= 10:
        alerts.append({"event": "DISEASE_WEATHER", "headline": "very humid and wet: blight and fungal leaf disease "
                                                               "spread fast; scout more often"})
    return alerts


# --- cross-verification -----------------------------------------------------------------------------------------
def compare(a: dict, b: dict) -> list[str]:
    """Significant disagreements between two summaries (empty list = they agree)."""
    out = []
    gap = abs(a["rain_72h_mm"] - b["rain_72h_mm"])
    if gap > config.WEATHER_DISAGREE_RAIN_72H_MM and gap > config.WEATHER_DISAGREE_RAIN_RATIO * max(a["rain_72h_mm"],
                                                                                                b["rain_72h_mm"]):
        out.append(f"72-hour rain: {a['rain_72h_mm']} vs {b['rain_72h_mm']} mm")
    if abs(a["rain_prob_24h_max"] - b["rain_prob_24h_max"]) > config.WEATHER_DISAGREE_PROB_PTS:
        out.append(f"24-hour rain chance: {a['rain_prob_24h_max']:.0f}% vs {b['rain_prob_24h_max']:.0f}%")
    if a["spray_window_ok"] != b["spray_window_ok"]:
        out.append(f"spray window: {'open' if a['spray_window_ok'] else 'closed'} vs "
                   f"{'open' if b['spray_window_ok'] else 'closed'}")
    elif abs(min(a["dry_hours_ahead"], 24) - min(b["dry_hours_ahead"], 24)) > config.WEATHER_DISAGREE_DRY_HOURS:
        out.append(f"hours until rain: {a['dry_hours_ahead']} vs {b['dry_hours_ahead']}")
    return out


def consensus(forecasts: list[dict]) -> dict:
    """The most cautious reading across sources (more rain, less dry time, more wind)."""
    keys_max = ("rain_24h_mm", "rain_72h_mm", "rain_7d_mm", "rain_prob_24h_max", "wind_24h_max_kmh",
                "wind_spray_window_kmh")
    out = {k: max(f[k] for f in forecasts) for k in keys_max}
    out["dry_hours_ahead"] = min(f["dry_hours_ahead"] for f in forecasts)
    hums = [f["humidity_24h_mean"] for f in forecasts if f.get("humidity_24h_mean") is not None]
    out["humidity_24h_mean"] = max(hums) if hums else None
    out["spray_window_ok"] = all(f["spray_window_ok"] for f in forecasts)
    return out


# --- fallbacks --------------------------------------------------------------------------------------------------
def _store(zone: str, provider: str, summary: dict) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO forecast_cache (zone_id, provider, fetched_at, forecast) VALUES (?,?,?,?)",
                     (zone, provider, now_iso(), json.dumps(summary)))


def _cached_live(zone: str) -> dict[str, dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=config.WEATHER_LIVE_CACHE_HOURS)).isoformat()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM forecast_cache WHERE zone_id = ? AND fetched_at >= ?", (zone, cutoff))
        return {r["provider"]: json.loads(r["forecast"]) | {"fetched_at": r["fetched_at"]} for r in rows}


def baseline(zone: str) -> dict | None:
    """Cached sub-county climate baseline: the ward's stored outlook plus its CHIRPS dekadal normal."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM weather_cache WHERE zone_id = ?", (zone,)).fetchone()
    if row is None:
        return None
    w = dict(row)
    o = agronomy.rainfall_outlook(w)
    normal = [d["normal_mm"] for d in weather_patterns.dekads(zone)[-1:]]
    return {"rain_24h_mm": o["rain_24h_mm"], "rain_72h_mm": o["rain_72h_mm"], "rain_7d_mm": o["rain_7d_mm"],
            "rain_prob_24h_max": None, "humidity_24h_mean": None, "wind_24h_max_kmh": w.get("wind_kmh"),
            "wind_spray_window_kmh": w.get("wind_kmh"), "dry_hours_ahead": w.get("dry_hours_ahead"),
            "spray_window_ok": (w.get("dry_hours_ahead") or 0) >= config.SPRAY_DRY_HOURS
            and (w.get("wind_kmh") or 0) <= config.SPRAY_MAX_WIND_KMH,
            "dekad_normal_mm": normal[0] if normal else None, "issued_at": w["issued_at"],
            "citation": f"weather_cache:{zone}@{w['issued_at']}"}


# --- the dual forecast --------------------------------------------------------------------------------------------
Fetcher = Callable[[float, float], object]


def _provider_fetchers() -> dict[str, Fetcher]:
    return {PRIMARY: fetch_open_meteo, SECONDARY: fetch_visual_crossing}


def dual_forecast(zone_id: str | None = None, lat: float | None = None, lon: float | None = None, *,
                  run_id: str = "weather", fetchers: dict[str, Fetcher] | None = None,
                  now: datetime | None = None) -> dict:
    zone = sanitizer.normalise_zone(zone_id)
    with connect() as conn:
        zones = [dict(r) for r in conn.execute("SELECT zone_id, centroid_lat, centroid_lon FROM weather_cache")]
    if zone is None and lat is not None and lon is not None:
        zone = (agronomy.nearest_zone(float(lat), float(lon), zones) or {}).get("zone_id")
    point = next((z for z in zones if z["zone_id"] == zone), None)
    if point is None:
        return {"ok": False, "error": f"unknown ward {zone_id!r}"}
    lat = float(lat) if lat is not None else point["centroid_lat"]
    lon = float(lon) if lon is not None else point["centroid_lon"]

    recovery: list[dict] = []
    live: dict[str, dict] = {}
    errors: dict[str, str] = {}
    provider_alerts: list[dict] = []
    if not config.LIVE_WEATHER:
        errors = {PRIMARY: "live weather switched off (CROP_PILOT_LIVE_WEATHER=0)",
                  SECONDARY: "live weather switched off (CROP_PILOT_LIVE_WEATHER=0)"}
    else:
        for name, fetch in (fetchers or _provider_fetchers()).items():
            if name == SECONDARY and fetchers is None and not config.VISUAL_CROSSING_API_KEY:
                errors[name] = "not configured (VISUAL_CROSSING_API_KEY empty)"
                continue
            try:
                raw, used, errs = with_retry(lambda f=fetch: f(lat, lon), attempts=config.WEATHER_RETRIES,
                                             retry_on=(httpx.HTTPError, ProviderError, ValueError, KeyError, TypeError))
                hours, alerts = raw if isinstance(raw, tuple) else (raw, [])
                live[name] = summarise(hours, now) | {"fetched_at": now_iso()}
                provider_alerts += alerts
                if used > 1:
                    recovery.append(log_recovery(run_id, name, "; ".join(errs), "retried", None, used))
                _store(zone, name, live[name])
            except Exception as exc:  # noqa: BLE001 - any provider failure is recoverable
                errors[name] = f"{type(exc).__name__}: {exc}"[:200]

    for name, err in errors.items():
        if config.LIVE_WEATHER and "not configured" not in err:
            other = SECONDARY if name == PRIMARY else PRIMARY
            action = f"failover:{other}" if other in live else "fallback"
            recovery.append(log_recovery(run_id, name, err, action, LABELS[other] if other in live else None,
                                         config.WEATHER_RETRIES))

    degraded_source = None
    if not live:                                             # both down: last good live forecast, then the baseline
        cached = _cached_live(zone)
        if cached:
            live = cached
            degraded_source = "cached live forecast (" + ", ".join(sorted(LABELS[p] for p in cached)) + ")"
        else:
            degraded_source = "cached sub-county climate baseline"
        why = "no live weather provider reachable" if config.LIVE_WEATHER else "live weather switched off"
        recovery.append(log_recovery(run_id, "weather", why,
                                     f"fallback:{'forecast_cache' if cached else 'baseline'}", degraded_source))

    base = baseline(zone)
    if not live and base is None:
        return {"ok": False, "error": f"no live forecast and no baseline for {zone}", "recovery": recovery}

    disagreements = compare(live[PRIMARY], live[SECONDARY]) if PRIMARY in live and SECONDARY in live else []
    if not live:
        agreement = "BASELINE_ONLY"
    elif len(live) == 1:
        agreement = "SINGLE_SOURCE"
    else:
        agreement = "DISAGREE" if disagreements else "AGREE"
    merged = consensus(list(live.values())) if live else {k: v for k, v in base.items() if k != "citation"}
    alerts = (severe_alerts(merged) if live else []) + provider_alerts
    stamp = now_iso()[:16]
    return {"ok": True, "zone_id": zone, "lat": lat, "lon": lon,
            "sources": {LABELS[p]: f for p, f in live.items()}, "provider_errors": {LABELS[p]: e for p, e in errors.items()},
            "agreement": agreement, "disagreements": disagreements, "cross_verified": agreement == "AGREE",
            "consensus": merged, "baseline": base, "alerts": alerts,
            "degraded": agreement != "AGREE", "degraded_source": degraded_source or (
                f"{LABELS[next(iter(live))]} only" if agreement == "SINGLE_SOURCE" else None),
            "recovery": recovery,
            "citation": f"live_weather:{zone}@{stamp}" if live else (base or {}).get("citation")}

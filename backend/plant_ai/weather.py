"""Two weather sources for one GPS point, cross-checked, with retry, failover and a cache.

* Open-Meteo (primary, keyless): through the external Open-Meteo MCP server when it is running, otherwise straight
  from api.open-meteo.com.
* Visual Crossing (secondary): its Timeline API, with VISUAL_CROSSING_API_KEY.

Each provider is retried. If one still fails the other is used alone (failover, SINGLE_SOURCE). If both fail, the
last good forecast for the spot (< 24 h old, SQLite) is used, and failing that the agent says it has no forecast.
Every failure and the recovery taken is reported back so the agent can log it and tell the user.

The two forecasts are compared on rain, rain chance and the spray window. If they DISAGREE the agent must not tell
a farmer it is safe to spray.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx

TZ = ZoneInfo("Africa/Nairobi")
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
VISUAL_CROSSING_URL = os.environ.get(
    "VISUAL_CROSSING_URL", "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline")
TIMEOUT_S = float(os.environ.get("PLANT_AI_WEATHER_TIMEOUT", "8"))
ATTEMPTS = 2
CACHE_HOURS = 24
WET_HOUR_MM = 0.2          # an hour with this much rain ends the dry spray window
SPRAY_DRY_HOURS = 6        # a spray needs this many dry hours after it
SPRAY_MAX_WIND_KMH = 15.0
# "Disagree significantly" = any of these.
DISAGREE_RAIN_24H_MM, DISAGREE_RAIN_RATIO, DISAGREE_PROB_PTS, DISAGREE_DRY_HOURS = 5.0, 0.5, 30.0, 6

OPEN_METEO, VISUAL_CROSSING = "Open-Meteo", "Visual Crossing"
Provider = Callable[[float, float], Awaitable[list[dict]]]


class ProviderError(RuntimeError):
    pass


def visual_crossing_key() -> str:
    return os.environ.get("VISUAL_CROSSING_API_KEY", "")


# --- providers: each returns hourly rows {time, precip_mm, prob, humidity, wind_kmh} ----------------------------------
def hours_from_open_meteo(data: Any) -> list[dict]:
    h = (data or {}).get("hourly") if isinstance(data, dict) else None
    if not h or not h.get("time") or h.get("precipitation") is None:
        raise ProviderError("Open-Meteo answer had no hourly precipitation")
    n = len(h["time"])
    col = lambda k: h.get(k) or [None] * n   # noqa: E731
    return [{"time": t, "precip_mm": p, "prob": pr, "humidity": hu, "wind_kmh": w}
            for t, p, pr, hu, w in zip(h["time"], col("precipitation"), col("precipitation_probability"),
                                       col("relative_humidity_2m"), col("wind_speed_10m"))]


async def open_meteo_http(lat: float, lon: float) -> list[dict]:
    params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "Africa/Nairobi", "forecast_days": 3,
              "hourly": "precipitation,precipitation_probability,relative_humidity_2m,wind_speed_10m",
              "wind_speed_unit": "kmh"}
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
        r = await c.get(OPEN_METEO_URL, params=params)
    if r.status_code != 200:
        raise ProviderError(f"Open-Meteo HTTP {r.status_code}")
    return hours_from_open_meteo(r.json())


async def visual_crossing_http(lat: float, lon: float) -> list[dict]:
    key = visual_crossing_key()
    if not key:
        raise ProviderError("VISUAL_CROSSING_API_KEY is not set")
    params = {"unitGroup": "metric", "include": "hours", "contentType": "json",
              "elements": "datetime,precip,precipprob,humidity,windspeed", "key": key}
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
        r = await c.get(f"{VISUAL_CROSSING_URL}/{round(lat, 4)},{round(lon, 4)}/next3days", params=params)
    if r.status_code != 200:
        raise ProviderError(f"Visual Crossing HTTP {r.status_code}")
    hours = [{"time": f"{d['datetime']}T{hr['datetime'][:5]}", "precip_mm": hr.get("precip"),
              "prob": hr.get("precipprob"), "humidity": hr.get("humidity"), "wind_kmh": hr.get("windspeed")}
             for d in r.json().get("days") or [] for hr in d.get("hours") or []]
    if not hours:
        raise ProviderError("Visual Crossing returned no hourly data")
    return hours


# --- reduce, compare, merge -----------------------------------------------------------------------------------------
def summarise(hours: list[dict], now: datetime | None = None) -> dict:
    now = (now or datetime.now(TZ)).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    ahead = []
    for h in hours:
        try:
            if datetime.fromisoformat(str(h["time"])[:16]) >= now:
                ahead.append(h)
        except ValueError:
            continue
    if len(ahead) < 24:
        raise ProviderError("forecast covers less than the next 24 hours")
    num = lambda v: float(v) if isinstance(v, (int, float)) else 0.0   # noqa: E731
    rain = [max(0.0, num(h["precip_mm"])) for h in ahead]
    probs = [num(h["prob"]) for h in ahead[:24] if h.get("prob") is not None]
    hum = [num(h["humidity"]) for h in ahead[:24] if h.get("humidity") is not None]
    wind = [num(h["wind_kmh"]) for h in ahead[:6] if h.get("wind_kmh") is not None]
    dry = next((i for i, mm in enumerate(rain) if mm >= WET_HOUR_MM), len(rain))
    out = {"rain_next_24h_mm": round(sum(rain[:24]), 1), "rain_next_72h_mm": round(sum(rain[:72]), 1),
           "rain_probability_max": max(probs) if probs else None,
           "humidity_mean": round(sum(hum) / len(hum)) if hum else None,
           "wind_next_6h_kmh": max(wind) if wind else None, "hours_until_rain": dry, "hours_covered": len(ahead)}
    out["spray_window_ok"] = dry >= SPRAY_DRY_HOURS and (out["wind_next_6h_kmh"] or 0) <= SPRAY_MAX_WIND_KMH
    return out


def compare(a: dict, b: dict) -> list[str]:
    out = []
    gap = abs(a["rain_next_24h_mm"] - b["rain_next_24h_mm"])
    if gap > DISAGREE_RAIN_24H_MM and gap > DISAGREE_RAIN_RATIO * max(a["rain_next_24h_mm"], b["rain_next_24h_mm"]):
        out.append(f"rain in the next 24 h: {a['rain_next_24h_mm']} vs {b['rain_next_24h_mm']} mm")
    if a["rain_probability_max"] is not None and b["rain_probability_max"] is not None and \
            abs(a["rain_probability_max"] - b["rain_probability_max"]) > DISAGREE_PROB_PTS:
        out.append(f"chance of rain: {a['rain_probability_max']:.0f}% vs {b['rain_probability_max']:.0f}%")
    if a["spray_window_ok"] != b["spray_window_ok"]:
        out.append(f"spray window: {'open' if a['spray_window_ok'] else 'closed'} vs "
                   f"{'open' if b['spray_window_ok'] else 'closed'}")
    elif abs(min(a["hours_until_rain"], 24) - min(b["hours_until_rain"], 24)) > DISAGREE_DRY_HOURS:
        out.append(f"hours until rain: {a['hours_until_rain']} vs {b['hours_until_rain']}")
    return out


def consensus(forecasts: list[dict]) -> dict:
    """The cautious reading across sources: more rain, sooner rain, more wind."""
    pick_max = lambda k: max((f[k] for f in forecasts if f.get(k) is not None), default=None)   # noqa: E731
    return {"rain_next_24h_mm": pick_max("rain_next_24h_mm"), "rain_next_72h_mm": pick_max("rain_next_72h_mm"),
            "rain_probability_max": pick_max("rain_probability_max"), "humidity_mean": pick_max("humidity_mean"),
            "wind_next_6h_kmh": pick_max("wind_next_6h_kmh"),
            "hours_until_rain": min(f["hours_until_rain"] for f in forecasts),
            "spray_window_ok": all(f["spray_window_ok"] for f in forecasts)}


# --- cache ----------------------------------------------------------------------------------------------------------
CACHE_SCHEMA = """CREATE TABLE IF NOT EXISTS forecast_cache (
    spot TEXT NOT NULL, provider TEXT NOT NULL, fetched_at TEXT NOT NULL, summary TEXT NOT NULL,
    PRIMARY KEY (spot, provider));"""


def _spot(lat: float, lon: float) -> str:
    return f"{round(lat, 2)},{round(lon, 2)}"      # ~1 km grid


def _store(conn, lat, lon, provider, summary) -> None:
    conn.executescript(CACHE_SCHEMA)
    conn.execute("INSERT OR REPLACE INTO forecast_cache VALUES (?,?,?,?)",
                 (_spot(lat, lon), provider, datetime.now(timezone.utc).isoformat(), json.dumps(summary)))


def _cached(conn, lat, lon) -> dict[str, dict]:
    conn.executescript(CACHE_SCHEMA)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=CACHE_HOURS)).isoformat()
    rows = conn.execute("SELECT provider, fetched_at, summary FROM forecast_cache WHERE spot=? AND fetched_at>=?",
                        (_spot(lat, lon), cutoff)).fetchall()
    return {r[0]: json.loads(r[2]) | {"fetched_at": r[1]} for r in rows}


# --- the dual forecast ------------------------------------------------------------------------------------------------
async def _with_retry(name: str, fn: Provider, lat: float, lon: float) -> tuple[list[dict] | None, list[str]]:
    errors = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(fn(lat, lon), timeout=TIMEOUT_S + 2), errors
        except Exception as exc:  # noqa: BLE001 - any provider fault is recoverable
            errors.append(f"{type(exc).__name__}: {exc}"[:160])
            if attempt < ATTEMPTS:
                await asyncio.sleep(0.3 * attempt)
    return None, errors


async def dual_forecast(lat: float, lon: float, providers: dict[str, Provider], conn,
                        now: datetime | None = None) -> dict:
    """providers: {name: async fn(lat, lon) -> hourly rows}. conn: sqlite3 connection for the cache."""
    live, errors, recovery = {}, {}, []
    results = await asyncio.gather(*(_with_retry(n, f, lat, lon) for n, f in providers.items()))
    for (name, _), (hours, errs) in zip(providers.items(), results):
        if hours is not None:
            try:
                live[name] = summarise(hours, now)
                _store(conn, lat, lon, name, live[name])
            except ProviderError as exc:
                errs = errs + [str(exc)]
        if name not in live:
            errors[name] = errs[-1] if errs else "no data"
        if errs and name in live:
            recovery.append({"component": name, "failure": "; ".join(errs), "action": "retried",
                             "used": name, "attempts": len(errs) + 1})
    for name, err in errors.items():
        others = [n for n in live if n != name]
        recovery.append({"component": name, "failure": err,
                         "action": f"failover to {others[0]}" if others else "no live provider", "used": others[0]
                         if others else None, "attempts": ATTEMPTS})
    degraded = None
    if not live:
        cached = _cached(conn, lat, lon)
        if cached:
            live, degraded = cached, "cached forecast from " + ", ".join(
                f"{p} ({v['fetched_at'][:16]})" for p, v in cached.items())
            recovery.append({"component": "weather", "failure": "no provider reachable",
                             "action": "fallback to cached forecast", "used": degraded, "attempts": 1})
    if not live:
        return {"ok": False, "agreement": "NO_DATA", "sources": {}, "errors": errors, "recovery": recovery,
                "summary": None, "disagreements": [],
                "message": "I could not get a weather forecast, so I cannot say whether it is safe to spray today."}
    names = list(live)
    disagreements = compare(live[names[0]], live[names[1]]) if len(names) >= 2 else []
    agreement = ("DISAGREE" if disagreements else "AGREE") if len(names) >= 2 else "SINGLE_SOURCE"
    return {"ok": True, "agreement": agreement, "cross_checked": agreement == "AGREE",
            "sources": live, "errors": errors, "disagreements": disagreements,
            "summary": consensus(list(live.values())), "degraded_source": degraded or (
                f"{names[0]} only" if agreement == "SINGLE_SOURCE" else None),
            "recovery": recovery}

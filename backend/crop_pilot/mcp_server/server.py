"""Crop-Pilot MCP server (built by us). Four tools; one of them writes.

Run standalone:  python -m crop_pilot.mcp_server.server   (stdio transport)

There is deliberately NO tool here that sends, dispatches, approves or contacts anyone.
`draft_advisory` can only create rows in the staging queue with a non-final status.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from mcp.server.fastmcp import FastMCP

from crop_pilot.core import agronomy, sanitizer
from crop_pilot.core.telemetry import now_iso
from crop_pilot.database.db import connect

mcp = FastMCP("crop-pilot")

DRAFT_STATUSES = {"PENDING_REVIEW", "SECURITY_LOCK", "NEEDS_DATA"}   # APPROVED is unreachable from here
VERDICTS = {"PLANT", "SPRAY", "HOLD"}
SOURCE_RE = re.compile(r"^(plots|weather_cache|pest_alerts|reference):[A-Za-z0-9_\-./#:@ ]{1,120}$")
MAX_MESSAGE_CHARS = 320


def _zones(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM weather_cache")]


@mcp.tool()
def get_rainfall_outlook(lat: Optional[float] = None, lon: Optional[float] = None,
                         zone_id: Optional[str] = None) -> dict:
    """Compute a deterministic spray-safety index (0-100) and planting-window decision for a location.

    Pass coordinates (lat, lon) or a zone_id. Coordinates are mapped to the nearest cached zone.
    """
    with connect() as conn:
        zones = _zones(conn)
    zone = sanitizer.normalise_zone(zone_id) if zone_id else None
    weather = next((z for z in zones if z["zone_id"] == zone), None)
    resolved_by = "zone_id"
    if weather is None and lat is not None and lon is not None:
        weather = agronomy.nearest_zone(float(lat), float(lon), zones)
        resolved_by = "nearest zone centroid"
    if weather is None:
        return {"ok": False, "error": f"no rainfall cache for zone {zone_id!r} / coordinates ({lat}, {lon})"}
    result = agronomy.rainfall_outlook(weather)
    result.update(ok=True, resolved_by=resolved_by, citation=f"weather_cache:{weather['zone_id']}@{weather['issued_at']}")
    return result


@mcp.tool()
def get_plot_context(household_id: str) -> dict:
    """Fetch one household's plot record, scrubbed: crop names normalised, growth stage re-derived from
    the crop calendar, corrupt fields repaired or defaulted, and instruction-like text redacted."""
    hid = sanitizer.normalise_text(household_id).upper()[:32]
    with connect() as conn:
        row = conn.execute("SELECT * FROM plots WHERE upper(trim(household_id)) = ?", (hid,)).fetchone()
        zones = {z["zone_id"]: z for z in _zones(conn)}
    clean = sanitizer.scrub_plot(dict(row) if row else None)
    clean["requested_id"] = hid
    if clean.get("found"):
        zone = zones.get(clean.get("zone_id"))
        if clean.get("lat") is None and zone:
            clean["lat"], clean["lon"] = zone["centroid_lat"], zone["centroid_lon"]
            clean["location_source"] = "zone centroid"
        elif clean.get("lat") is not None:
            clean["location_source"] = "plot GPS"
        clean["citation"] = f"plots:{clean['household_id']}"
    return clean


@mcp.tool()
def get_pest_reports(zone_id: str, lat: Optional[float] = None, lon: Optional[float] = None,
                     crop: Optional[str] = None, growth_stage: Optional[str] = None) -> dict:
    """Score officer-verified pest/disease alerts near a plot (severity x distance x recency) and say
    whether any is actionable for this crop's growth stage. Unverified reports are listed but ignored."""
    zone = sanitizer.normalise_zone(zone_id)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM pest_alerts WHERE zone_id = ? OR (lat IS NOT NULL AND lon IS NOT NULL)", (zone,))]
    result = agronomy.score_pest_alerts(rows, lat, lon, sanitizer.normalise_crop(crop) if crop else None,
                                        (growth_stage or "").upper() or None)
    result.update(ok=True, zone_id=zone,
                  citations=[f"pest_alerts:#{a['id']}" for a in result["verified_alerts"]])
    return result


@mcp.tool()
def draft_advisory(run_id: str, household_id: str, status: str, verdict: Optional[str],
                   farmer_message: str, rationale: str, sources: list[str],
                   evidence: dict, flags: Optional[list[str]] = None,
                   rule_verdict: Optional[str] = None, model_verdict: Optional[str] = None) -> dict:
    """WRITE: stage a draft advisory in the pending_advisories queue for a named officer to review.

    This cannot send anything. Allowed statuses: PENDING_REVIEW, SECURITY_LOCK, NEEDS_DATA.
    Every draft must cite at least one source (plots:, weather_cache:, pest_alerts:, reference:).
    Idempotent per run_id.
    """
    flags = list(flags or [])
    status = (status or "").upper()
    verdict = verdict.upper() if verdict else None
    if status not in DRAFT_STATUSES:
        return {"ok": False, "error": f"status {status!r} not allowed; drafts can only be {sorted(DRAFT_STATUSES)}"}
    if verdict is not None and verdict not in VERDICTS:
        return {"ok": False, "error": f"verdict {verdict!r} must be one of {sorted(VERDICTS)}"}
    clean_sources = sorted({s.strip() for s in sources or [] if SOURCE_RE.match(s.strip())})
    if not clean_sources:
        return {"ok": False, "error": "refused: an advisory with no valid source cannot be drafted"}
    if verdict in VERDICTS and not any(s.startswith(("weather_cache:", "plots:")) for s in clean_sources):
        return {"ok": False, "error": "refused: a Plant/Spray/Hold verdict must cite the plot and rainfall records"}

    message, hits = sanitizer.scrub_free_text(farmer_message, MAX_MESSAGE_CHARS)
    if hits:
        status, verdict = "SECURITY_LOCK", "HOLD"
        flags.append("injection_in_drafted_message")
    rationale_clean, _ = sanitizer.scrub_free_text(rationale, 2000)

    with connect() as conn:
        existing = conn.execute("SELECT id, status FROM pending_advisories WHERE run_id = ?", (run_id,)).fetchone()
        if existing:
            return {"ok": True, "advisory_id": existing["id"], "status": existing["status"], "idempotent_replay": True}
        cur = conn.execute(
            "INSERT INTO pending_advisories (run_id, household_id, verdict, status, farmer_message, rationale,"
            " evidence_json, sources_json, flags_json, rule_verdict, model_verdict, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, sanitizer.normalise_text(household_id)[:32], verdict, status, message, rationale_clean,
             json.dumps(evidence, default=str), json.dumps(clean_sources), json.dumps(sorted(set(flags))),
             rule_verdict, model_verdict, now_iso()))
    return {"ok": True, "advisory_id": cur.lastrowid, "status": status, "verdict": verdict,
            "sources": clean_sources, "note": "Staged for officer review. Nothing has been sent."}


if __name__ == "__main__":
    mcp.run()

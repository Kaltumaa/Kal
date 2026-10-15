"""Weather patterns: season outlook vs normal, recent rainfall vs the long-term mean, and onset / false-start risk.

Deterministic. Reads the CHIRPS-format dekadal history and the season outlook from the reference library.
Like plot history, a pattern never flips a Plant/Spray/Hold verdict: it adds a sourced reason and a farmer tip.
"""
from __future__ import annotations

import csv

from crop_pilot import config

BELOW_NORMAL = -0.10      # season outlook at least 10 % under the long-term mean
ABOVE_NORMAL = 0.15
DRY_RECENT = 0.70         # last two dekads under 70 % of normal = rains running late
FALSE_START = 0.60        # a wet week after two dekads under 60 % of normal = false-start risk


def _rows(name: str) -> list[dict]:
    path = config.REFERENCE_DIR / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def dekads(zone_id: str) -> list[dict]:
    rows = [r for r in _rows("chirps_dekadal_dagoretti.csv") if r["zone_id"] == zone_id]
    out = [{"period": f"{int(r['year'])}-{int(r['month']):02d} D{r['dekad']}", "rain_mm": float(r["rain_mm"]),
            "normal_mm": float(r["long_term_mean_mm"])} for r in rows]
    return sorted(out, key=lambda r: r["period"])


def assess(zone_id: str, rain_7d_mm: float | None = None) -> dict:
    """Pattern summary for one ward. `rain_7d_mm` is the current 7-day forecast, used for onset checks."""
    history = dekads(zone_id)
    season = next((r for r in _rows("season_outlook.csv") if r["zone_id"] == zone_id), None)
    advice, tips = [], []
    result: dict = {"zone_id": zone_id, "dekads": history,
                    "sources": ["reference:chirps_dekadal_dagoretti.csv", "reference:season_outlook.csv"]}

    if season:
        expected, normal = float(season["expected_rain_mm"]), float(season["long_term_mean_mm"])
        anomaly = expected / normal - 1
        season_class = "BELOW" if anomaly <= BELOW_NORMAL else ("ABOVE" if anomaly >= ABOVE_NORMAL else "NEAR")
        result.update(season=season["season"], season_expected_mm=expected, season_normal_mm=normal,
                      season_anomaly_pct=round(anomaly * 100), season_class=season_class)
        if season_class == "BELOW":
            advice.append(f"Season rain expected {abs(round(anomaly * 100))}% below normal: choose early-maturing, "
                          "drought-tolerant varieties and plant at the first reliable rains.")
            tips.append("Drier season than usual: use early-maturing seed.")
        elif season_class == "ABOVE":
            advice.append(f"Season rain expected {round(anomaly * 100)}% above normal: plant on raised beds or ridges, "
                          "keep drains open, split fertiliser doses and watch for blight.")
            tips.append("Wetter season than usual: keep drains open.")
    else:
        result.update(season_class="UNKNOWN")

    recent = history[-2:]
    if recent:
        ratio = sum(r["rain_mm"] for r in recent) / max(0.1, sum(r["normal_mm"] for r in recent))
        result["recent_pct_of_normal"] = round(ratio * 100)
        wet_week = rain_7d_mm is not None and rain_7d_mm >= config.PLANTING_RAIN_7D_MM
        if wet_week and ratio < FALSE_START:
            onset = "FALSE_START_RISK"
            advice.append(f"Rain is returning after a dry spell (last 20 days at {round(ratio * 100)}% of normal). "
                          "A dry spell can follow a first burst: plant part of the plot now and the rest after a "
                          "second wet week.")
            tips.append("Rain follows a dry spell: plant half now, half after the next wet week.")
        elif wet_week:
            onset = "ONSET"
        elif ratio < DRY_RECENT:
            onset = "LATE"
            advice.append(f"Rains are running late (last 20 days at {round(ratio * 100)}% of normal). Keep land ready.")
        else:
            onset = "NOT_YET"
        result["onset"] = onset
    else:
        result.update(onset="UNKNOWN", recent_pct_of_normal=None)

    result["advice"] = advice
    result["sms_tip"] = tips[0] if tips else None
    return result

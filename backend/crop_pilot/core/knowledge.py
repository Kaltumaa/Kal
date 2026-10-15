"""Knowledge-base logic: symptom -> pest matching and crop suitability scoring. Pure and deterministic."""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

from crop_pilot import config

KB_TOPICS = {
    "pests_diseases": ("Pests & diseases", "🐛"),
    "pesticides_safety": ("Pesticides & safe use", "🧴"),
    "weeds": ("Weeds", "🌿"),
    "soils": ("Soils", "🟫"),
    "greenhouse": ("Greenhouse growing", "🏠"),
    "crop_calendar_nairobi": ("Crop calendar", "📅"),
    "pest_action_thresholds": ("Pest action thresholds", "🎯"),
    "spray_safety_guidelines": ("When it is safe to spray", "🌦️"),
}


def list_topics() -> list[dict]:
    return [{"slug": s, "title": t, "icon": i} for s, (t, i) in KB_TOPICS.items()
            if (config.REFERENCE_DIR / f"{s}.md").exists()]


def read_topic(slug: str) -> str | None:
    if slug not in KB_TOPICS:          # whitelist: no path traversal possible
        return None
    path = config.REFERENCE_DIR / f"{slug}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


@lru_cache(maxsize=1)
def _symptoms() -> dict:
    return json.loads((config.REFERENCE_DIR / "pest_symptoms.json").read_text(encoding="utf-8"))


def match_symptoms(description: str, crop: str | None = None) -> list[dict]:
    """Rank likely pests/diseases from a free-text symptom description (e.g. a vision-model caption)."""
    text = (description or "").lower()
    results = []
    for pest, spec in _symptoms().items():
        hits = sorted({k for k in spec["keywords"] if re.search(rf"\b{re.escape(k)}", text)})
        if not hits:
            continue
        score = len(hits) / max(4, len(spec["keywords"]) / 2)
        if crop and spec["crops"]:
            score *= 1.5 if crop in spec["crops"] else 0.4
        results.append({"pest": pest, "score": round(min(score, 1.0), 2), "matched": hits,
                        "host_crops": spec["crops"]})
    return sorted(results, key=lambda r: r["score"], reverse=True)[:3]


@lru_cache(maxsize=1)
def crops() -> list[dict]:
    with (config.REFERENCE_DIR / "crop_suitability.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("season_rain_min_mm", "season_rain_max_mm", "temp_min_c", "temp_max_c"):
            r[k] = float(r[k])
        r["soils"] = [s.strip() for s in r["soils"].split(";")]
    return rows


def suitability(season_rain_mm: float, mean_temp_c: float, soil: str | None, greenhouse: bool) -> list[dict]:
    """Score every crop 0-100 against rainfall, temperature, soil and greenhouse availability."""
    out = []
    for c in crops():
        reasons, score = [], 100.0
        lo, hi = c["season_rain_min_mm"], c["season_rain_max_mm"]
        if greenhouse and c["greenhouse"] in ("best", "yes"):
            reasons.append("greenhouse controls water")
        elif season_rain_mm < lo:
            gap = (lo - season_rain_mm) / lo
            penalty = gap * (60 if c["drought_tolerance"] == "high" else 100)
            score -= penalty
            reasons.append(f"rain {season_rain_mm:.0f} mm below the {lo:.0f} mm it needs")
        elif season_rain_mm > hi:
            score -= min(40, (season_rain_mm - hi) / hi * 80)
            reasons.append(f"rain above {hi:.0f} mm: waterlogging/disease risk")
        else:
            reasons.append("rainfall in range")
        tlo, thi = c["temp_min_c"], c["temp_max_c"]
        if not tlo <= mean_temp_c <= thi:
            score -= min(50, min(abs(mean_temp_c - tlo), abs(mean_temp_c - thi)) * 8)
            reasons.append(f"best between {tlo:.0f}–{thi:.0f} °C")
        if soil and soil not in c["soils"]:
            score -= 25
            reasons.append(f"prefers {', '.join(c['soils'])}")
        if greenhouse and c["greenhouse"] == "best":
            score += 10
        if greenhouse and c["greenhouse"] == "no":
            reasons.append("field crop: not worth greenhouse space")
        out.append({"crop": c["crop"], "score": int(max(0, min(100, score))), "reasons": reasons,
                    "greenhouse": c["greenhouse"], "days_to_maturity": c["days_to_maturity"],
                    "drought_tolerance": c["drought_tolerance"], "notes": c["notes"]})
    return sorted(out, key=lambda r: r["score"], reverse=True)

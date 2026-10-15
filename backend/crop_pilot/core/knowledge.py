"""Knowledge-base logic: symptom -> pest matching and crop suitability scoring. Pure and deterministic."""
from __future__ import annotations

import bisect
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
                        "host_crops": spec["crops"], "type": spec.get("type", "Pest")})
    return sorted(results, key=lambda r: r["score"], reverse=True)[:3]


MIN_MATCH = 0.3
INSECT_WORDS = re.compile(r"\b(aphids?|insects?|caterpillars?|larvae?|worms?|beetles?|bugs?|mites?|whitefl(y|ies)|"
                          r"armyworms?|thrips|grubs?|weevils?)\b", re.IGNORECASE)


def _vote(answer: str) -> str:
    """Read one natural-language answer to 'weed or crop?' (the model answers in sentences)."""
    t = (answer or "").lower()
    if "not a weed" in t:
        return "crop"
    if "not a crop" in t:
        return "weed"
    hits = {cat: t.find(word) for word, cat in (("weed", "weed"), ("crop", "crop"), ("caterpillar", "insect"),
                                                 ("insect", "insect")) if word in t}
    return min(hits, key=hits.get) if hits else "unclear"


def _yes_no(answer: str) -> bool | None:
    t = (answer or "").strip().lower()
    return True if t.startswith("yes") else (False if t.startswith("no") else None)


def classify_photo(description: str, subject_answers: list[str], healthy_answer: str, crop: str | None) -> dict:
    """Combine the vision model's answers with the guide. Deterministic.

    The small model is biased by word order and tends to say "yes", so: the main subject is the MAJORITY of three
    differently-worded questions (else "unclear"), and damage is judged only by "Do the leaves look healthy?".
    - Weed (majority): only weed matches, or "weed, species unclear".
    - Healthy leaves and not a weed: no pest is suggested.
    - Otherwise pests and diseases, dropping any that do not attack the farm's crop and any weak match.
    """
    votes = [_vote(a) for a in subject_answers]
    top = max(set(votes), key=votes.count) if votes else "unclear"
    category = top if votes.count(top) >= 2 else "unclear"
    # If the AI's own description names an insect or pest, it is a pest photo whatever the weed/crop votes say
    # (that question is meaningless for a close-up of insects on a crop).
    if INSECT_WORDS.search(description or ""):
        category = "insect"
    healthy = _yes_no(healthy_answer)
    signs = None if healthy is None else not healthy
    found = match_symptoms(description, crop)
    if category == "weed":
        weeds = [c for c in found if c["type"] == "Weed" and c["score"] >= MIN_MATCH]
        candidates = weeds or [{"pest": "Weed (species unclear)", "type": "Weed", "score": 0.5,
                                "matched": [f"AI: weed in {votes.count('weed')} of {len(votes)} checks"],
                                "host_crops": []}]
    elif signs is False and category != "insect":
        candidates = []
    else:
        candidates = [c for c in found if c["type"] != "Weed" and c["score"] >= MIN_MATCH
                      and not (crop and c["host_crops"] and crop not in c["host_crops"])]
    return {"category": category, "votes": votes, "signs": signs, "candidates": candidates[:3]}


@lru_cache(maxsize=1)
def crops() -> list[dict]:
    with (config.REFERENCE_DIR / "crop_suitability.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("season_rain_min_mm", "season_rain_max_mm", "temp_min_c", "temp_max_c"):
            r[k] = float(r[k])
        r["soils"] = [s.strip() for s in r["soils"].split(";")]
    return rows


# Score tables for the suitability matrix. bisect finds which band a value falls in (O(log n)); the score is a fixed
# lookup, so the result is fully deterministic and the language model is never involved.
RAIN_SCORES = {"high": [30, 60, 85, 100, 75, 45], "medium": [15, 45, 75, 100, 70, 40], "low": [5, 35, 65, 100, 70, 40]}
TEMP_SCORES = [20, 50, 75, 100, 75, 50, 20]


def _rain_band(c: dict) -> list[float]:
    lo, hi = c["season_rain_min_mm"], c["season_rain_max_mm"]
    return [0.5 * lo, 0.75 * lo, lo, hi, 1.25 * hi]


def _temp_band(c: dict) -> list[float]:
    lo, hi = c["temp_min_c"], c["temp_max_c"]
    return [lo - 4, lo - 2, lo, hi, hi + 2, hi + 4]


def _maturity_days(text: str) -> int | None:
    nums = [int(n) for n in re.findall(r"\d+", text or "")]
    return round(sum(nums[:2]) / len(nums[:2])) if nums else None


def suitability(season_rain_mm: float, mean_temp_c: float, soil: str | None, greenhouse: bool,
                rain_7d_mm: float | None = None) -> list[dict]:
    """Score every crop 0-100 against rainfall, temperature, soil and greenhouse availability (bisect lookup),
    with reasons that quote the numbers, when to plant and an expected harvest date."""
    from datetime import timedelta

    from crop_pilot.core import agronomy, sanitizer
    out = []
    for c in crops():
        reasons = []
        lo, hi = c["season_rain_min_mm"], c["season_rain_max_mm"]
        under_cover = greenhouse and c["greenhouse"] in ("best", "yes")
        if under_cover:
            rain_score = 100
            reasons.append(f"Grown under cover, so you control the water (needs {lo:.0f}–{hi:.0f} mm equivalent).")
        else:
            band = bisect.bisect_right(_rain_band(c), season_rain_mm)
            rain_score = RAIN_SCORES.get(c["drought_tolerance"], RAIN_SCORES["medium"])[band]
            if lo <= season_rain_mm <= hi:
                reasons.append(f"{season_rain_mm:.0f} mm of season rain is within the {lo:.0f}–{hi:.0f} mm "
                               "this crop needs.")
            elif season_rain_mm < lo:
                tip = ("its drought tolerance helps" if c["drought_tolerance"] == "high"
                       else "choose an early-maturing variety or add water")
                reasons.append(f"{season_rain_mm:.0f} mm is {lo - season_rain_mm:.0f} mm short of the {lo:.0f} mm "
                               f"this crop needs: {tip}.")
            else:
                reasons.append(f"{season_rain_mm:.0f} mm is above the {hi:.0f} mm this crop likes: risk of "
                               "waterlogging and disease; use raised beds.")
        tlo, thi = c["temp_min_c"], c["temp_max_c"]
        temp_score = TEMP_SCORES[bisect.bisect_right(_temp_band(c), mean_temp_c)]
        if tlo <= mean_temp_c <= thi:
            reasons.append(f"{mean_temp_c:.1f} °C average suits it ({tlo:.0f}–{thi:.0f} °C).")
        else:
            reasons.append(f"{mean_temp_c:.1f} °C is {'too cool' if mean_temp_c < tlo else 'too warm'}: it grows "
                           f"best at {tlo:.0f}–{thi:.0f} °C, so growth will be slower.")
        score = min(rain_score, temp_score)
        if soil and soil not in c["soils"]:
            score -= 25
            reasons.append(f"{soil.capitalize()} soil is not ideal: it prefers {', '.join(c['soils'])}.")
        elif soil:
            reasons.append(f"{soil.capitalize()} soil suits it.")
        if greenhouse and c["greenhouse"] == "best":
            score += 10
        if greenhouse and c["greenhouse"] == "no":
            reasons.append("Field crop: not worth greenhouse space.")
        days = _maturity_days(c["days_to_maturity"])
        harvest = (config.today() + timedelta(days=days)).strftime("%b %Y") if days else None
        plant_now = None
        if rain_7d_mm is not None:
            need = agronomy.planting_threshold(sanitizer.normalise_crop(c["crop"]))
            plant_now = under_cover or rain_7d_mm >= need
        rain_ok = under_cover or lo <= season_rain_mm <= hi
        rain_text = ("Watered under cover" if under_cover else
                     f"{season_rain_mm:.0f} mm rain (needs {lo:.0f}–{hi:.0f})" if rain_ok else
                     f"{season_rain_mm:.0f} mm rain: {lo - season_rain_mm:.0f} mm short (needs {lo:.0f}+)"
                     if season_rain_mm < lo else f"{season_rain_mm:.0f} mm rain: too wet (max {hi:.0f})")
        temp_ok = tlo <= mean_temp_c <= thi
        temp_text = (f"{mean_temp_c:.1f} °C (best {tlo:.0f}–{thi:.0f})" if temp_ok else
                     f"{mean_temp_c:.1f} °C: {'too cool' if mean_temp_c < tlo else 'too warm'} (best {tlo:.0f}–{thi:.0f})")
        soil_ok = not soil or soil in c["soils"]
        soil_text = (f"{(soil or 'any soil').capitalize()} suits it" if soil_ok else
                     f"{soil.capitalize()}: prefers {', '.join(c['soils'])}")
        checks = [{"kind": "rain", "ok": rain_ok, "text": rain_text},
                  {"kind": "temp", "ok": temp_ok, "text": temp_text},
                  {"kind": "soil", "ok": soil_ok, "text": soil_text}]
        out.append({"crop": c["crop"], "score": int(max(0, min(100, score))), "reasons": reasons, "checks": checks,
                    "greenhouse": c["greenhouse"], "days_to_maturity": c["days_to_maturity"],
                    "harvest_if_planted_now": harvest, "plant_now": plant_now,
                    "drought_tolerance": c["drought_tolerance"], "notes": c["notes"]})
    return sorted(out, key=lambda r: r["score"], reverse=True)


def season_outlook() -> list[dict]:
    """Expected season rainfall, temperature and dominant soil per ward (CHIRPS-style, synthetic)."""
    path = config.REFERENCE_DIR / "season_outlook.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("expected_rain_mm", "long_term_mean_mm", "mean_temp_c"):
            r[k] = float(r[k])
        r["rain_vs_normal_pct"] = round(100 * r["expected_rain_mm"] / r["long_term_mean_mm"])
    return rows


def plant_seen(description: str) -> str | None:
    """Name a crop the photo description mentions (e.g. 'maize leaf'), using the crop-name dictionary."""
    from crop_pilot.core.sanitizer import CROP_ALIASES
    text = (description or "").lower()
    for word, crop in sorted(CROP_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(word)}\b", text):
            return crop
    return None


@lru_cache(maxsize=1)
def _problem_guide() -> dict:
    path = config.REFERENCE_DIR / "problem_guide.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def problem_info(name: str | None) -> dict | None:
    return _problem_guide().get(name or "")


def farmer_explainer(name: str | None) -> str:
    """Plain message for a farmer: what it is, how to fix it, how to prevent it (from the problem guide)."""
    info = problem_info(name)
    if not info:
        return f"{name}." if name else ""
    steps = " ".join(f"{i}) {step}" for i, step in enumerate(info["fix"], 1))
    return f"{name}: {info['what']} How to fix: {steps} Next season: {info['prevent']}"


VERDICT_STEPS = {
    "PLANT": ["Prepare the seedbed and plant with certified seed now, while the rain is coming.",
              "Plant at the recommended spacing and add manure or planting fertiliser.",
              "Weed at 2-3 weeks and again at 5-6 weeks."],
    "HOLD": ["Do not plant, spray or apply fertiliser this week.",
             "Clear drainage channels if heavy rain is expected.",
             "Keep checking your crop; your officer will update you."],
}


def advice_steps(verdict: str | None, pest: str | None) -> list[str]:
    """Concrete steps to go with an approved advisory."""
    if verdict == "SPRAY" and problem_info(pest):
        return problem_info(pest)["fix"]
    return VERDICT_STEPS.get(verdict or "", [])

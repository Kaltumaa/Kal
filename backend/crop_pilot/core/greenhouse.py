"""Greenhouse microclimate: vapour pressure deficit (VPD), dew point and plain-language advice. Pure and deterministic."""
from __future__ import annotations

import math

# Ideal daytime air temperature per greenhouse crop (°C), matching data/reference/greenhouse.md.
CROP_TEMP = {"Tomato": (21, 27), "Capsicum": (21, 29), "Cucumber": (22, 28), "Kale": (15, 24),
             "Spinach": (15, 24), "Strawberry": (18, 24)}
VPD_BANDS = [  # (upper kPa, status, meaning)
    (0.4, "TOO_HUMID", "Air is nearly saturated: high risk of blight, grey mould and mildew."),
    (0.8, "HUMID", "A little humid: fine for seedlings, but watch for mould on mature plants."),
    (1.2, "IDEAL", "Ideal: plants transpire and take up nutrients well."),
    (1.6, "DRY", "Air is getting dry: plants start closing their pores and growth slows."),
    (math.inf, "TOO_DRY", "Very dry air: heat and water stress, flower drop."),
]


def saturation_vp(temp_c: float) -> float:
    """Tetens equation, kPa."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def vpd(temp_c: float, rh_pct: float) -> float:
    return round(saturation_vp(temp_c) * (1 - rh_pct / 100), 2)


def dew_point(temp_c: float, rh_pct: float) -> float:
    """Magnus formula, °C."""
    g = math.log(max(rh_pct, 1) / 100) + 17.27 * temp_c / (237.3 + temp_c)
    return round(237.3 * g / (17.27 - g), 1)


def assess(temp_c: float, rh_pct: float, crop: str | None = None) -> dict:
    if not (-5 <= temp_c <= 60) or not (0 <= rh_pct <= 100):
        raise ValueError("Readings out of range: temperature -5–60 °C, humidity 0–100 %.")
    v = vpd(temp_c, rh_pct)
    status, meaning = next((s, m) for upper, s, m in VPD_BANDS if v < upper)
    lo, hi = CROP_TEMP.get(crop or "", (18, 28))
    actions = []
    if status in ("TOO_HUMID", "HUMID"):
        actions.append("Open side vents or roll up curtains for 1–2 hours, ideally mid-morning.")
        actions.append("Water at the base early in the day, never on the leaves in the evening.")
    if status in ("DRY", "TOO_DRY"):
        actions.append("Wet the paths or mist around (not on) plants to raise humidity.")
        actions.append("Add 30–40 % shade net during the hottest hours.")
    if temp_c > hi:
        actions.append(f"Too hot for {crop or 'most crops'} (best {lo}–{hi} °C): ventilate fully and shade.")
    elif temp_c < lo:
        actions.append(f"Too cool for {crop or 'most crops'} (best {lo}–{hi} °C): close vents in the late afternoon "
                       "to keep heat in.")
    if temp_c - dew_point(temp_c, rh_pct) < 2:
        actions.append("Condensation likely on leaves and plastic: ventilate before nightfall to stop drips.")
    if not actions:
        actions.append("Conditions are good. Keep the current vent routine.")
    return {"temp_c": temp_c, "rh_pct": rh_pct, "vpd_kpa": v, "dew_point_c": dew_point(temp_c, rh_pct),
            "status": status, "meaning": meaning, "crop": crop, "ideal_temp_c": [lo, hi], "actions": actions,
            "formula": "VPD = 0.6108·exp(17.27·T/(T+237.3)) × (1 − RH/100)"}

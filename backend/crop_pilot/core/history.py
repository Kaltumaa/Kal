"""Plot history: crop-rotation risk from a household's past seasons. Pure and deterministic.

`crop_history` = past seasons, oldest -> newest, NOT including the current season's crop.
The result never changes the Plant/Spray/Hold verdict; it adds a sourced reason and a farmer tip.
"""
from __future__ import annotations

FAMILY = {
    "Maize": "cereal", "Sorghum": "cereal",
    "Beans": "legume", "Cowpeas": "legume", "Groundnut": "legume",
    "Potato": "nightshade", "Tomato": "nightshade", "Capsicum": "nightshade",
    "Kale": "brassica", "Cabbage": "brassica", "Spinach": "leafy",
}
CARRYOVER = {
    "cereal": ("Fall Armyworm, Maize Lethal Necrosis and Striga", "plant beans here next season"),
    "nightshade": ("Late Blight and bacterial wilt", "keep potato and tomato off this plot for 3 seasons"),
    "brassica": ("aphids and clubroot", "rotate to a cereal or legume next season"),
    "legume": ("bean fly and root rots", "rotate to maize or sorghum next season"),
}


def rotation(active_crop: str | None, history: list[str]) -> dict:
    if not active_crop:
        return {"risk": "UNKNOWN", "note": None, "sms_tip": None, "same_family_run": 0}
    if not history:
        return {"risk": "UNKNOWN", "same_family_run": 1, "sms_tip": None,
                "note": "No crop history recorded for this plot; rotation risk unknown."}
    fam = FAMILY.get(active_crop)
    run = 1
    for past in reversed(history):
        if FAMILY.get(past) == fam and fam is not None:
            run += 1
        else:
            break
    previous = history[-1]
    seq = " > ".join(history + [f"{active_crop} (now)"])
    if run >= 2 and fam in CARRYOVER:
        pests, fix = CARRYOVER[fam]
        risk = "HIGH" if run >= 3 else "ELEVATED"
        return {"risk": risk, "same_family_run": run, "sequence": seq,
                "note": f"Plot history {seq}: {run} seasons of {fam} crops in a row raises carry-over of {pests}.",
                "sms_tip": f"Same crop {run} seasons running: scout twice a week; {fix}."}
    if fam == "nightshade" and any(FAMILY.get(p) == "nightshade" for p in history[-3:]):
        pests, fix = CARRYOVER[fam]
        return {"risk": "ELEVATED", "same_family_run": run, "sequence": seq,
                "note": f"Plot history {seq}: a nightshade crop within the last 3 seasons keeps {pests} risk up.",
                "sms_tip": "Blight can carry over: no potato or tomato here for 3 seasons."}
    if FAMILY.get(previous) == "legume" and fam == "cereal":
        return {"risk": "LOW", "same_family_run": run, "sequence": seq,
                "note": f"Plot history {seq}: follows {previous.lower()}, a good rotation with a nitrogen benefit.",
                "sms_tip": None}
    return {"risk": "LOW", "same_family_run": run, "sequence": seq,
            "note": f"Plot history {seq}: rotation is fine.", "sms_tip": None}

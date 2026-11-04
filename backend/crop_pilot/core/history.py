"""Plot history: crop-rotation risk from a household's past seasons. Pure and deterministic.

`crop_history` = past seasons, oldest -> newest, NOT including the current season's crop.
The result never changes the Plant/Spray/Hold verdict; it adds a sourced reason and a farmer tip.
"""
from __future__ import annotations

from datetime import date

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



def rotation_for_plot(plot: dict) -> dict:
    """Rotation risk for a scrubbed plot, aware of crops grown together. The main crop of each season decides the
    risk (beans between maize rows add nitrogen but do not break the maize pest cycle), but the sequence shows every
    crop, and the tip never tells a farmer to add beans they already grow."""
    crop = plot.get("active_crop")
    r = rotation(crop, plot.get("crop_history") or [])
    seasons = plot.get("seasons") or []
    companions = plot.get("companions") or ([plot["intercrop"]] if plot.get("intercrop") else [])
    if not crop or not r.get("sequence") or not any(len(x) > 1 for x in seasons + [[crop, *companions]]):
        return r
    seq = " > ".join(["+".join(x) for x in seasons] + ["+".join([crop, *companions]) + " (now)"])
    r = r | {"sequence": seq, "note": (r.get("note") or "").replace(r["sequence"], seq)}
    fam, run = FAMILY.get(crop), r.get("same_family_run", 0)
    recent = seasons[-(run - 1):] if run > 1 else []
    with_legume = bool(recent) and all(any(FAMILY.get(c) == "legume" for c in x[1:]) for x in recent) \
        and any(FAMILY.get(c) == "legume" for c in companions)
    if fam == "cereal" and run >= 2 and with_legume:
        pests, _ = CARRYOVER["cereal"]
        r |= {"note": f"Plot history {seq}: {crop.lower()} has been the main crop {run} seasons in a row. The "
                      f"legumes grown with it add nitrogen, but they do not break the cycle of {pests}.",
              "sms_tip": f"{crop} {run} seasons running, even with beans: scout twice a week; next season make "
                         "beans or another non-cereal the main crop."}
    return r


def crops_growing(plot: dict, field_log: list[dict] | None, today: date | None = None) -> list[dict]:
    """Every crop on the plot right now, each with its own planting date: the main crop, its recorded companions,
    and any crop the field log shows planted in the last year and not harvested since. Farmers often grow several
    crops at once (maize with beans, a kale strip) and plant them on different days."""
    from crop_pilot import config
    from crop_pilot.core import sanitizer
    today = today or config.today()
    main = plot.get("active_crop")
    crops: dict[str, dict] = {}
    if main:
        crops[main] = {"crop": main, "planted": plot.get("planting_date"), "main": True, "source": "farm record"}
    for c in plot.get("companions") or ([plot["intercrop"]] if plot.get("intercrop") else []):
        crops.setdefault(c, {"crop": c, "planted": plot.get("planting_date"), "main": False,
                             "source": "grown with the main crop"})
    log = sorted((e for e in field_log or [] if e.get("action") in ("PLANTING", "HARVEST") and e.get("crop")
                  and e.get("action_date")), key=lambda e: (e["action_date"], e.get("id") or 0))
    for e in log:
        c, when = sanitizer.normalise_crop(e["crop"]), e["action_date"][:10]
        if not c:
            continue
        try:
            age = (today - date.fromisoformat(when)).days
        except ValueError:
            continue
        if e["action"] == "PLANTING" and 0 <= age <= 365:
            crops[c] = crops.get(c, {"crop": c, "main": False, "source": "field log"}) | {"planted": when,
                                                                                          "harvested": None}
        elif e["action"] == "HARVEST" and c in crops and (crops[c].get("planted") or "") <= when:
            crops[c]["harvested"] = when
    out = []
    for info in crops.values():
        if info.get("harvested") and not info["main"]:
            continue                                     # harvested companion crops are no longer growing
        try:
            days = (today - date.fromisoformat(info["planted"])).days if info.get("planted") else None
        except ValueError:
            days = None
        days = days if days is not None and 0 <= days <= 365 else None
        out.append(info | {"days": days, "stage": sanitizer.growth_stage(info["crop"], days),
                           "harvested": info.get("harvested")})
    return sorted(out, key=lambda x: (not x["main"], x["crop"]))

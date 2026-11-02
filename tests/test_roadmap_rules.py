"""Theme-1 roadmap rules: wind drift, chemical rotation, weeds first, false-start hold, storm crusting, scout soon."""
import asyncio

from langgraph.checkpoint.memory import InMemorySaver

from crop_pilot import config
from crop_pilot.agent import workflow
from crop_pilot.core import agronomy

PLOT = {"found": True, "profile_complete": True, "injection_detected": False, "active_crop": "Maize",
        "growth_stage": "EARLY_VEGETATIVE"}
SOWING = PLOT | {"active_crop": "Beans", "growth_stage": "PRE_PLANTING"}
THREAT = {"id": 1, "pest": "Fall Armyworm", "severity": "HIGH", "distance_km": 0.2, "age_days": 3,
          "action_radius_km": 5.0, "crop_susceptible": True, "actionable": True}


def rain(wind=6.0, r7d=31.0, storm="LOW", r72=7.0):
    return agronomy.rainfall_outlook({"rain_24h_mm": 1.0, "rain_72h_mm": r72, "rain_7d_mm": r7d, "storm_risk": storm,
                                      "runoff_coeff": 0.3, "issued_at": "2026-10-14", "wind_kmh": wind})


def test_wind_above_limit_turns_spray_into_hold():
    d = agronomy.decide(PLOT, rain(wind=24), {"top_threat": THREAT})
    assert d["verdict"] == "HOLD" and d["rule"] == "R2b_wind_hold" and "24 km/h" in " ".join(d["reasons"])
    assert agronomy.decide(PLOT, rain(wind=10), {"top_threat": THREAT})["verdict"] == "SPRAY"
    # No wind data (an older forecast): behaves exactly as before.
    assert agronomy.decide(PLOT, rain(wind=None), {"top_threat": THREAT})["verdict"] == "SPRAY"


def test_spray_advice_asks_for_a_different_chemical_group():
    log = [{"id": 2, "action": "SPRAYING", "action_date": "2026-04-20", "chem_group": "Pyrethroids (IRAC 3A)"},
           {"id": 1, "action": "SPRAYING", "action_date": "2026-04-02", "chem_group": "Pyrethroids (IRAC 3A)"}]
    d = agronomy.decide(PLOT, rain(), {"top_threat": THREAT}, field_log=log)
    text = " ".join(d["reasons"])
    assert d["verdict"] == "SPRAY" and "Pyrethroids (IRAC 3A), twice in a row" in text and "different group" in text
    assert agronomy.chemical_rotation(log)["citation"] == "plot_actions:#2"


def test_weedy_plot_holds_planting_until_weeding_is_logged():
    weedy = [{"id": 1, "action": "OBSERVATION", "action_date": "2026-10-10", "details": "", "needs_weeding": 1}]
    d = agronomy.decide(SOWING, rain(), None, field_log=weedy)
    assert d["verdict"] == "HOLD" and d["rule"] == "R4b_clear_weeds_first"
    cleared = weedy + [{"id": 2, "action": "WEEDING", "action_date": "2026-10-12", "details": ""}]
    assert agronomy.decide(SOWING, rain(), None, field_log=cleared)["verdict"] == "PLANT"
    # A later observation answering "No" also clears it.
    clean = weedy + [{"id": 3, "action": "OBSERVATION", "action_date": "2026-10-13", "details": "", "needs_weeding": 0}]
    assert agronomy.decide(SOWING, rain(), None, field_log=clean)["verdict"] == "PLANT"


def test_free_text_about_weeds_never_blocks_planting():
    # The bug we fixed: word-matching read "weeding done" and "no weeds" as a weedy plot.
    for text in ["weeding done, plot clean", "no weeds at all", "cleared the bush last week", "plot full of weeds"]:
        log = [{"id": 1, "action": "OBSERVATION", "action_date": "2026-10-10", "details": text, "needs_weeding": None}]
        assert agronomy.decide(SOWING, rain(), None, field_log=log)["verdict"] == "PLANT", text


def test_rotation_compares_insect_sprays_with_insect_sprays_only():
    # The bug we fixed: a fungicide (copper, for disease) was used to advise on an armyworm (insect) spray.
    log = [{"id": 1, "action": "SPRAYING", "action_date": "2026-09-01", "chem_group": "Copper (FRAC M01)"}]
    d = agronomy.decide(PLOT, rain(), {"top_threat": THREAT}, field_log=log)          # Fall Armyworm = insect
    assert d["verdict"] == "SPRAY" and "different group" not in " ".join(d["reasons"])
    blight = THREAT | {"pest": "Late Blight"}                                             # disease
    potato = PLOT | {"active_crop": "Potato", "growth_stage": "VEGETATIVE"}
    d = agronomy.decide(potato, rain(), {"top_threat": blight}, field_log=log)
    assert "last disease spray" in " ".join(d["reasons"]) and "Copper (FRAC M01)" in " ".join(d["reasons"])
    assert agronomy.threat_kind("Fall Armyworm") == "insect" and agronomy.threat_kind("Late Blight") == "disease"


def test_false_start_holds_only_after_a_very_dry_spell():
    dry = {"onset": "FALSE_START_RISK", "recent_pct_of_normal": 30}
    d = agronomy.decide(SOWING, rain(), None, pattern=dry)
    assert d["verdict"] == "HOLD" and d["rule"] == "R4c_false_start_hold"
    mild = {"onset": "FALSE_START_RISK", "recent_pct_of_normal": 60}
    d = agronomy.decide(SOWING, rain(), None, pattern=mild)
    assert d["verdict"] == "PLANT" and "two" not in d["rule"] and "rest after a second wet week" in " ".join(d["reasons"])
    assert "certified seed" in " ".join(d["reasons"])


def test_storm_before_sowing_warns_about_soil_crusting():
    d = agronomy.decide(SOWING, rain(storm="HIGH", r72=80), None)
    assert d["rule"] == "R2_washout_hold" and "crust" in " ".join(d["reasons"])


def test_pest_just_outside_radius_means_scout_not_spray():
    near = THREAT | {"distance_km": 7.0, "actionable": False}
    d = agronomy.decide(PLOT, rain(), {"top_threat": None, "verified_alerts": [near]})
    assert d["verdict"] == "HOLD" and d["rule"] == "R6b_scout_soon"
    far = THREAT | {"distance_km": 12.0, "actionable": False}
    assert agronomy.decide(PLOT, rain(), {"top_threat": None, "verified_alerts": [far]})["rule"] == "R6_monitor"


def test_agent_end_to_end_wind_hold_and_rotation(temp_db, monkeypatch):
    monkeypatch.setattr(config, "DISABLE_LLM", True)
    graph = workflow.build_graph(InMemorySaver())
    windy = asyncio.run(workflow.start_run(graph, "HH-DS-010"))          # tomato, late blight, Riruta 22 km/h
    assert windy["advisory"]["verdict"] == "HOLD" and windy["decision"]["rule"] == "R2b_wind_hold"
    assert windy["followup"]["kind"] == "RECHECK_WIND" and windy["frozen_at_human_gate"]
    grace = asyncio.run(workflow.start_run(graph, "HH-DS-003"))           # sprayed pyrethroids twice last season
    assert grace["advisory"]["verdict"] == "SPRAY"
    assert any(s.startswith("plot_actions:#") for s in grace["advisory"]["sources"])

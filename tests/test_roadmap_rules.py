"""Theme-1 roadmap rules: wind drift, chemical rotation, weeds first, false-start hold, storm crusting, scout soon."""
import asyncio

import pytest

from langgraph.checkpoint.memory import InMemorySaver

from crop_pilot import config
from crop_pilot.agent import workflow
from crop_pilot.core import agronomy
from crop_pilot.dispatch.approval import ApprovalError

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


def test_false_start_holds_only_when_a_dry_spell_is_forecast_after_the_rain():
    def outlook(dry):
        return agronomy.rainfall_outlook({"rain_24h_mm": 1.0, "rain_72h_mm": 7.0, "rain_7d_mm": 31.0,
                                          "storm_risk": "LOW", "runoff_coeff": 0.3, "issued_at": "2026-10-14",
                                          "wind_kmh": 6, "dry_spell_days_ahead": dry})
    d = agronomy.decide(SOWING, outlook(12), None)
    assert d["verdict"] == "HOLD" and d["rule"] == "R4c_false_start_hold" and "12 dry days" in " ".join(d["reasons"])
    assert agronomy.decide(SOWING, outlook(4), None)["verdict"] == "PLANT"
    assert agronomy.decide(SOWING, outlook(None), None)["verdict"] == "PLANT"          # no outlook: as before
    # A dry past alone is normal before the season starts: it only adds the two-batch tip, never a hold.
    past_dry = {"onset": "FALSE_START_RISK", "recent_pct_of_normal": 30}
    d = agronomy.decide(SOWING, outlook(4), None, pattern=past_dry)
    assert d["verdict"] == "PLANT" and "rest after a second wet week" in " ".join(d["reasons"])
    assert "certified seed" in " ".join(d["reasons"])


def test_storm_before_sowing_warns_about_soil_crusting():
    d = agronomy.decide(SOWING, rain(storm="HIGH", r72=80), None)
    assert d["rule"] == "R2_washout_hold" and "crust" in " ".join(d["reasons"])


def test_pest_just_outside_radius_means_scout_not_spray():
    near = THREAT | {"distance_km": 7.0, "actionable": False}
    d = agronomy.decide(PLOT, rain(), {"top_threat": None, "verified_alerts": [near]})
    assert d["verdict"] == "HOLD" and d["rule"] == "R6b_scout_soon"
    far = THREAT | {"distance_km": 12.0, "actionable": False}
    # Too far to scout for that report, but young maize is in the armyworm risk window: scout, still no spray.
    assert agronomy.decide(PLOT, rain(), {"top_threat": None, "verified_alerts": [far]})["rule"] == "R6c_risk_window"


def test_agent_end_to_end_wind_hold_and_rotation(temp_db, monkeypatch):
    monkeypatch.setattr(config, "DISABLE_LLM", True)
    graph = workflow.build_graph(InMemorySaver())
    windy = asyncio.run(workflow.start_run(graph, "HH-DS-010"))          # tomato, late blight, Riruta 22 km/h
    assert windy["advisory"]["verdict"] == "HOLD" and windy["decision"]["rule"] == "R2b_wind_hold"
    assert windy["followup"]["kind"] == "RECHECK_WIND" and windy["frozen_at_human_gate"]
    grace = asyncio.run(workflow.start_run(graph, "HH-DS-003"))           # sprayed pyrethroids twice last season
    assert grace["advisory"]["verdict"] == "SPRAY"
    assert any(s.startswith("plot_actions:#") for s in grace["advisory"]["sources"])


def test_spraying_status_is_decided_once_rain_before_wind():
    assert rain(wind=6)["spray_status"] == "OK"
    windy = rain(wind=22)
    assert windy["spray_status"] == "NO_WIND" and windy["spray_label"] == "Too windy (22 km/h)"
    wet_and_windy = agronomy.rainfall_outlook({"rain_24h_mm": 30, "rain_72h_mm": 80, "rain_7d_mm": 120,
                                               "storm_risk": "HIGH", "runoff_coeff": 0.3, "issued_at": "2026-10-14",
                                               "wind_kmh": 30})
    assert wet_and_windy["spray_status"] == "NO_RAIN"           # rain is the first reason, as in decide()


def test_api_serves_spray_groups_and_rejects_bad_field_log_input(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from crop_pilot.api.main import app
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "ck.db")
    base = {"action_date": "2026-10-10", "details": "", "role": "farmer"}
    with TestClient(app) as c:
        assert c.get("/knowledge/spray-groups").json() == config.CHEM_GROUPS
        bad_group = c.post("/farms/HH-DS-003/actions", json=base | {"action": "SPRAYING", "chem_group": "Fake"})
        weeding_on_spray = c.post("/farms/HH-DS-003/actions", json=base | {"action": "SPRAYING", "needs_weeding": True})
        assert bad_group.status_code == 400 and weeding_on_spray.status_code == 400
        ok = c.post("/farms/HH-DS-001/actions", json=base | {"action": "OBSERVATION", "needs_weeding": True})
        assert ok.status_code == 200
        assert c.get("/farms/HH-DS-001/actions").json()[0]["needs_weeding"] == 1


def test_older_database_gets_missing_demo_rows_without_overwrites(temp_db):
    import sqlite3
    from crop_pilot.database.init_db import seed_missing
    conn = sqlite3.connect(temp_db)
    # Make it look like a database from before the roadmap work, plus one user change that must survive.
    conn.execute("DELETE FROM plots WHERE household_id = 'HH-DS-010'")
    conn.execute("DELETE FROM pest_alerts WHERE zone_id = 'RIRUTA' AND pest = 'Late Blight'")
    conn.execute("DELETE FROM plot_actions")
    conn.execute("UPDATE weather_cache SET wind_kmh = NULL")
    conn.execute("UPDATE plots SET field_notes = 'edited by officer' WHERE household_id = 'HH-DS-001'")
    seed_missing(conn)
    seed_missing(conn)                                            # running twice adds nothing twice
    one = lambda q: conn.execute(q).fetchone()[0]                 # noqa: E731
    assert one("SELECT COUNT(*) FROM plots WHERE household_id = 'HH-DS-010'") == 1
    assert one("SELECT COUNT(*) FROM pest_alerts WHERE zone_id = 'RIRUTA' AND pest = 'Late Blight'") == 1
    assert one("SELECT COUNT(*) FROM plot_actions") == 3
    assert one("SELECT wind_kmh FROM weather_cache WHERE zone_id = 'RIRUTA'") == 22.0
    assert one("SELECT field_notes FROM plots WHERE household_id = 'HH-DS-001'") == "edited by officer"
    conn.close()


# --- Slope & soil, rainfall intensity, soil moisture, intercropping ---------------------------------------------
def outlook(dry=None, peak=None, peak_at=None, r7d=31.0, r72=7.0):
    return agronomy.rainfall_outlook({"rain_24h_mm": 1.0, "rain_72h_mm": r72, "rain_7d_mm": r7d, "storm_risk": "LOW",
                                      "runoff_coeff": 0.3, "issued_at": "2026-10-14", "wind_kmh": 6,
                                      "dry_spell_days_ahead": dry, "peak_rain_mm_h": peak, "peak_rain_at": peak_at})


def test_slope_changes_how_to_plant_never_whether():
    steep = agronomy.decide(SOWING | {"slope": "steep", "soil": "red loam"}, rain(), None)
    text = " ".join(steep["reasons"])
    assert steep["verdict"] == "PLANT" and "contour" in text and "tied ridges" in text
    gentle = agronomy.decide(SOWING | {"slope": "gentle"}, rain(), None)
    assert gentle["verdict"] == "PLANT" and "contour" in " ".join(gentle["reasons"])
    flat = agronomy.decide(SOWING | {"slope": "flat"}, rain(), None)
    assert "contour" not in " ".join(flat["reasons"])


def test_flat_clay_waterlogs_after_a_very_wet_week():
    clay = SOWING | {"slope": "flat", "soil": "black cotton"}
    d = agronomy.decide(clay, rain(r7d=70, r72=30), None)
    assert d["verdict"] == "HOLD" and d["rule"] == "R4e_waterlog_hold" and "waterlog" in " ".join(d["reasons"])
    ok = agronomy.decide(clay, rain(), None)
    assert ok["verdict"] == "PLANT" and "ridges" in " ".join(ok["reasons"])
    assert agronomy.decide(SOWING | {"slope": "flat", "soil": "red loam"}, rain(r7d=70, r72=30), None)["verdict"] == "PLANT"


def test_violent_storm_forecast_holds_seeding_but_a_past_one_does_not():
    d = agronomy.decide(SOWING, outlook(peak=42, peak_at="2026-10-16"), None)         # tomorrow (demo today 10-15)
    assert d["verdict"] == "HOLD" and d["rule"] == "R4f_crust_hold" and "Sow just after the storm" in " ".join(d["reasons"])
    # Already fell before sowing: digging the planting holes breaks that crust, so plant.
    assert agronomy.decide(SOWING, outlook(peak=42, peak_at="2026-10-13"), None)["verdict"] == "PLANT"
    assert agronomy.decide(SOWING, outlook(peak=10, peak_at="2026-10-16"), None)["verdict"] == "PLANT"  # gentle
    assert agronomy.decide(SOWING, outlook(peak=42, peak_at="2026-10-25"), None)["verdict"] == "PLANT"  # too far off
    assert agronomy.decide(SOWING, outlook(), None)["verdict"] == "PLANT"                                # no data


def test_storm_after_sowing_asks_to_check_emergence():
    sown = PLOT | {"active_crop": "Beans", "growth_stage": "EMERGENCE", "planting_date": "2026-10-10"}
    d = agronomy.decide(sown, outlook(peak=42, peak_at="2026-10-13"), None)
    assert "gently break any crust" in " ".join(d["reasons"])
    before = agronomy.decide(sown, outlook(peak=42, peak_at="2026-10-05"), None)        # fell before sowing
    assert "crust" not in " ".join(before["reasons"])


def test_soil_moisture_check_by_hand():
    dry = [{"id": 1, "action": "OBSERVATION", "action_date": "2026-10-14", "details": "", "soil_moist": 0}]
    d = agronomy.decide(SOWING, rain(), None, field_log=dry)
    assert d["verdict"] == "HOLD" and d["rule"] == "R4g_soil_dry_hold" and "hand's depth" in " ".join(d["reasons"])
    wet = dry + [{"id": 2, "action": "OBSERVATION", "action_date": "2026-10-15", "details": "", "soil_moist": 1}]
    ok = agronomy.decide(SOWING, rain(), None, field_log=wet)
    assert ok["verdict"] == "PLANT" and "soil moist to a hand's depth" in " ".join(ok["reasons"])
    stale = [dry[0] | {"action_date": "2026-10-01"}]                                    # too old to count
    assert agronomy.decide(SOWING, rain(), None, field_log=stale)["verdict"] == "PLANT"
    none = agronomy.decide(SOWING, rain(), None)
    assert "Before sowing, check the soil is moist" in " ".join(none["reasons"])


def test_intercrop_tip_is_standard_advice_and_never_changes_the_verdict():
    maize = SOWING | {"active_crop": "Maize", "intercrop": "Beans"}
    d = agronomy.decide(maize, rain(), None, pattern={"season_class": "BELOW"})
    text = " ".join(d["reasons"])
    assert d["verdict"] == "PLANT" and "one beans row between the maize rows" in text
    assert "early-maturing" in text and "mulch" in text and "shade" not in text
    wet = agronomy.decide(maize, rain(), None, pattern={"season_class": "ABOVE"})
    assert "not crowded" in " ".join(wet["reasons"])
    assert agronomy.intercrop_tip(maize, {"season_class": "NEAR"}) is None
    assert agronomy.intercrop_tip(SOWING | {"intercrop": "Kale"}, {"season_class": "BELOW"}) is None
    held = agronomy.decide(maize, rain(r7d=14), None, pattern={"season_class": "BELOW"})
    assert held["rule"] == "R5_wait_for_onset" and "between the maize rows" in " ".join(held["reasons"])


def test_holds_carry_a_plain_title():
    assert agronomy.decide(SOWING, outlook(dry=12), None)["title"] == "Deceptive false start"
    weedy = [{"id": 1, "action": "OBSERVATION", "action_date": "2026-10-10", "details": "", "needs_weeding": 1}]
    assert agronomy.decide(SOWING, rain(), None, field_log=weedy)["title"] == "Vegetation moisture trap"


def test_hold_message_gives_the_real_reason_in_both_languages():
    plot = {"active_crop": "Tomato", "growth_stage": "VEGETATIVE"}
    r = rain(wind=22)
    en = workflow._template_message("HOLD", plot, r, None, "R2b_wind_hold")
    assert "too windy" in en and "No pest threat" not in en
    assert set(workflow.HOLD_REASONS) == set(workflow.SW_HOLD_REASONS)
    for rule in workflow.HOLD_REASONS:
        assert rule in agronomy.RULE_TITLES
        en = workflow._template_message("HOLD", plot, r, None, rule)
        sw = workflow._template_message_sw("HOLD", plot, r, None, rule)
        assert len(en) <= 320 and len(sw) <= 320 and "{" not in en + sw


def test_scrubber_ignores_unknown_terrain():
    from crop_pilot.core import sanitizer
    row = {"household_id": "X", "zone_id": "RIRUTA", "active_crop": "Beans", "slope": "Steep ", "soil": "mud"}
    clean = sanitizer.scrub_plot(row)
    assert clean["slope"] == "steep" and clean["soil"] is None
    assert any("soil" in q for q in clean["data_quality"])


def test_demo_farms_end_to_end_and_api(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from crop_pilot.api.main import app
    monkeypatch.setattr(config, "DISABLE_LLM", True)
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "ck.db")
    graph = workflow.build_graph(InMemorySaver())
    rose = asyncio.run(workflow.start_run(graph, "HH-DS-014"))              # Mutuini, 12 dry days ahead
    assert rose["decision"]["rule"] == "R4c_false_start_hold" and rose["self_check"]["outcome"] == "pass"
    daniel = asyncio.run(workflow.start_run(graph, "HH-DS-011"))            # steep hillside: plants, along contour
    assert daniel["advisory"]["verdict"] == "PLANT" and daniel["self_check"]["outcome"] == "pass"
    with TestClient(app) as c:
        draft = next(d for d in c.get("/advisories").json() if d["run_id"] == rose["run_id"])
        assert draft["rationale"].startswith("HOLD: Deceptive false start.") and "dry spell" in draft["farmer_message"]
        dan = next(d for d in c.get("/advisories").json() if d["run_id"] == daniel["run_id"])
        assert "contour" in dan["rationale"]
        plan = {f["household_id"]: f for f in c.get("/farms/plan").json()}
        assert plan["HH-DS-012"]["rule"] == "R4f_crust_hold"                        # Faith: storm forecast tomorrow
        assert any("between the maize rows" in n for n in plan["HH-DS-013"]["notes"])  # John: dry season intercrop
        assert plan["HH-DS-001"]["plan"] == "PLANT"                                  # Peter unchanged
        assert c.get("/knowledge/terrain").json()["slopes"] == config.SLOPES
        bad = c.post("/farms/HH-DS-011/terrain", json={"slope": "cliff", "soil": "red loam", "officer_name": "Jane Officer"})
        rocks = c.post("/farms/HH-DS-013/terrain", json={"slope": "flat", "soil": "red loam", "intercrop": "Rocks",
                                                         "officer_name": "Jane Officer"})
        anon = c.post("/farms/HH-DS-011/terrain", json={"slope": "flat", "soil": "red loam", "officer_name": "   "})
        assert bad.status_code == 400 and rocks.status_code == 400 and anon.status_code in (400, 422)
        ok = c.post("/farms/HH-DS-013/terrain", json={"slope": "flat", "soil": "red loam", "intercrop": None,
                                                      "officer_name": "Jane Officer"})
        assert ok.status_code == 200 and ok.json()["intercrop"] is None
        moist = c.post("/farms/HH-DS-001/actions", json={"action": "OBSERVATION", "action_date": "2026-10-15",
                                                         "details": "", "role": "farmer", "soil_moist": False})
        wrong = c.post("/farms/HH-DS-001/actions", json={"action": "WEEDING", "action_date": "2026-10-15",
                                                         "details": "", "role": "farmer", "soil_moist": True})
        assert moist.status_code == 200 and wrong.status_code == 400
        peter = next(f for f in c.get("/farms/plan").json() if f["household_id"] == "HH-DS-001")
        assert peter["rule"] == "R4g_soil_dry_hold"
        storm = c.post("/weather/RIRUTA", json={"rain_24h_mm": 1, "rain_72h_mm": 7, "rain_7d_mm": 31,
                                                "storm_risk": "LOW", "peak_rain_mm_h": 35, "peak_rain_date": "2026-10-16"})
        assert storm.status_code == 200
        assert next(f for f in c.get("/farms/plan").json() if f["household_id"] == "HH-DS-011")["rule"] == "R4f_crust_hold"


# --- Spray vs hold: rain-fastness, pest risk window, rotation alternatives, neighbour drift ---------------------
def spray_outlook(dry_hours):
    return agronomy.rainfall_outlook({"rain_24h_mm": 1.0, "rain_72h_mm": 7.0, "rain_7d_mm": 31.0, "storm_risk": "LOW",
                                      "runoff_coeff": 0.3, "issued_at": "2026-10-14", "wind_kmh": 6,
                                      "dry_hours_ahead": dry_hours})


def test_rain_due_within_6_hours_holds_the_spray():
    d = agronomy.decide(PLOT, spray_outlook(3), {"top_threat": THREAT})
    assert d["verdict"] == "HOLD" and d["rule"] == "R2c_rain_soon_hold" and "3 hours" in " ".join(d["reasons"])
    assert spray_outlook(3)["spray_status"] == "RAIN_SOON" and spray_outlook(3)["spray_label"] == "Rain due in 3 h"
    assert agronomy.decide(PLOT, spray_outlook(8), {"top_threat": THREAT})["verdict"] == "SPRAY"
    assert agronomy.decide(PLOT, spray_outlook(None), {"top_threat": THREAT})["verdict"] == "SPRAY"   # no data
    draft = {"verdict": "SPRAY", "sources": ["plots:X", "weather_cache:Y"], "farmer_message": "x"}
    ev = {"plot": {}, "rain": spray_outlook(3), "pests": {"top_threat": THREAT}}
    assert any("wash off" in p for p in workflow.check_draft(draft, ev))


def test_risk_window_means_scout_with_a_threshold_never_spray_ahead():
    d = agronomy.decide(PLOT, rain(), {"top_threat": None, "verified_alerts": []})
    text = " ".join(d["reasons"])
    assert d["verdict"] == "HOLD" and d["rule"] == "R6c_risk_window" and d["title"] == "Pest risk window: scout"
    assert "Do not spray ahead of the pest" in text and "10 %" in text
    mature = PLOT | {"growth_stage": "GRAIN_FILL"}                                    # past the armyworm window
    assert agronomy.decide(mature, rain(), {"top_threat": None})["rule"] == "R6_monitor"


def test_rotation_names_the_guide_alternatives_for_that_pest():
    log = [{"id": 2, "action": "SPRAYING", "action_date": "2026-04-20", "chem_group": "Pyrethroids (IRAC 3A)"},
           {"id": 1, "action": "SPRAYING", "action_date": "2026-04-02", "chem_group": "Pyrethroids (IRAC 3A)"}]
    note = agronomy.chemical_rotation(log, kind="insect", pest="Fall Armyworm")["note"]
    assert "Spinosyns (IRAC 5)" in note and "not on that list" in note
    emam = [{"id": 3, "action": "SPRAYING", "action_date": "2026-09-01", "chem_group": "Avermectins / emamectin (IRAC 6)"}]
    note = agronomy.chemical_rotation(emam, kind="insect", pest="Fall Armyworm")["note"]
    assert "lists: Spinosyns" in note and "lists: Avermectins" not in note


def test_wind_hold_names_the_neighbours():
    d = agronomy.decide(PLOT, rain(wind=24), {"top_threat": THREAT})
    assert d["title"] == "Too windy: drift risk to neighbours" and "neighbours' crops, beehives" in " ".join(d["reasons"])
    assert "neighbours" in workflow._template_message("HOLD", PLOT, rain(wind=24), THREAT, "R2b_wind_hold")


def test_demo_risk_window_farm_and_forecast_update(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from crop_pilot.api.main import app
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "ck.db")
    with TestClient(app) as c:
        plan = {f["household_id"]: f for f in c.get("/farms/plan").json()}
        assert plan["HH-DS-015"]["rule"] == "R6c_risk_window"                 # Paul, beans just up in Uthiru
        assert "Bean Fly risk window" in plan["HH-DS-015"]["why"]
        assert plan["HH-DS-003"]["plan"] == "SPRAY"                           # Grace: dry window today
        r = c.post("/weather/MUTUINI", json={"rain_24h_mm": 0.5, "rain_72h_mm": 3, "rain_7d_mm": 18,
                                             "storm_risk": "LOW", "dry_hours_ahead": 2})
        assert r.status_code == 200
        grace = next(f for f in c.get("/farms/plan").json() if f["household_id"] == "HH-DS-003")
        assert grace["rule"] == "R2c_rain_soon_hold"


# --- Photos: inconclusive / not a plant / group review; seed label check ---------------------------------------
def _sharp_png():
    import io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 200), (120, 160, 90))
    d = ImageDraw.Draw(img)
    for x in range(0, 200, 8):
        d.line([(x, 0), (200 - x, 200)], fill=(20, 60, 20), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    import base64
    return base64.b64encode(buf.getvalue()).decode()


def _fake_vision(monkeypatch, fieldscan, description, subjects, present):
    monkeypatch.setattr(fieldscan, "_describe", lambda b64: (description, {"latency_ms": 1, "tokens": 1}))
    monkeypatch.setattr(fieldscan, "_classify", lambda b64: ({"subjects": subjects, "healthy": "No, holes in leaves",
                                                              "present": present}, {"latency_ms": 1, "tokens": 1}))


def test_unclear_photo_is_inconclusive_and_no_plant_is_not_applicable(temp_db, tmp_path, monkeypatch):
    import base64
    import io
    from PIL import Image
    from crop_pilot.fieldscan import service as fieldscan
    monkeypatch.setattr(fieldscan, "SCAN_DIR", tmp_path)
    _fake_vision(monkeypatch, fieldscan, "Maize leaf with ragged holes and frass in the whorl", ["a crop"] * 3, "Yes")
    dark = io.BytesIO()
    Image.new("RGB", (200, 200), (10, 10, 10)).save(dark, format="PNG")
    res = fieldscan.analyse(base64.b64encode(dark.getvalue()).decode(), "HH-DS-003", None)
    assert res["inconclusive"] and not res["not_a_plant"]
    _fake_vision(monkeypatch, fieldscan, "A blue plastic bucket on a concrete floor.", ["unclear"] * 3, "No")
    bucket = fieldscan.analyse(_sharp_png(), "HH-DS-003", None)
    assert bucket["not_a_plant"] and not bucket["inconclusive"]
    r = fieldscan.review(bucket["scan_id"], "Wanjiru Kamau", "DISMISSED",
                         finding="Not a plant or pest: advice not applicable")
    assert r["status"] == "DISMISSED"
    mine = {p["id"]: p for p in fieldscan.farmer_view("HH-DS-003")}
    assert mine[bucket["scan_id"]]["officer_finding"] == "Not a plant or pest: advice not applicable"
    with pytest.raises(ApprovalError):
        fieldscan.review(res["scan_id"], "Wanjiru Kamau", "DISMISSED", finding="Looks fine to me")


def test_group_review_needs_clear_matching_photos_and_one_named_officer(temp_db, tmp_path, monkeypatch):
    from crop_pilot.fieldscan import service as fieldscan
    monkeypatch.setattr(fieldscan, "SCAN_DIR", tmp_path)
    _fake_vision(monkeypatch, fieldscan, "Maize leaf with ragged holes, frass and window-pane feeding in the whorl",
                 ["a crop"] * 3, "Yes")
    ids = [fieldscan.analyse(_sharp_png(), "HH-DS-003", None)["scan_id"] for _ in range(3)]
    groups = fieldscan.review_groups()
    assert len(groups) == 1 and set(groups[0]["scan_ids"]) == set(ids) and groups[0]["zone_id"] == "MUTUINI"
    pest = groups[0]["pest"]
    with pytest.raises(ApprovalError):
        fieldscan.review_batch(ids[:2], "", pest)                         # no named officer
    out = fieldscan.review_batch(ids[:2], "Wanjiru Kamau", pest, "HIGH", "Spray into the whorl early morning.")
    assert out["verified"] == ids[:2]
    with pytest.raises(ApprovalError):
        fieldscan.review_batch(ids, "Wanjiru Kamau", pest)                # two are already reviewed
    from crop_pilot.core import telemetry  # noqa: F401
    import sqlite3
    conn = sqlite3.connect(temp_db)
    audit = conn.execute("SELECT COUNT(*) FROM tool_calls WHERE tool='review_field_scan' AND approved_by='Wanjiru Kamau'")
    assert audit.fetchone()[0] == 2                                        # one audit line per photo
    conn.close()


def test_failed_seed_label_holds_planting_and_verified_is_quoted():
    failed = [{"id": 1, "action": "VARIETY", "action_date": "2026-10-12", "details": "", "seed_check": "FAILED"}]
    d = agronomy.decide(SOWING, rain(), None, field_log=failed)
    assert d["verdict"] == "HOLD" and d["rule"] == "R4h_unverified_seed" and d["title"] == "Unverified seed"
    ok = failed + [{"id": 2, "action": "VARIETY", "action_date": "2026-10-13", "details": "", "seed_check": "VERIFIED"}]
    d = agronomy.decide(SOWING, rain(), None, field_log=ok)
    assert d["verdict"] == "PLANT" and "Seed label verified with KEPHIS (2026-10-13)" in " ".join(d["reasons"])
    plain = agronomy.decide(SOWING, rain(), None)
    assert "SMS the code" in " ".join(plain["reasons"])


def test_seed_check_api_validation(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from crop_pilot.api.main import app
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "ck.db")
    base = {"action_date": "2026-10-15", "details": "", "role": "farmer"}
    with TestClient(app) as c:
        assert c.post("/farms/HH-DS-001/actions", json=base | {"action": "WEEDING", "seed_check": "FAILED"}).status_code == 400
        assert c.post("/farms/HH-DS-001/actions", json=base | {"action": "VARIETY", "seed_check": "MAYBE"}).status_code == 422
        assert c.post("/farms/HH-DS-001/actions", json=base | {"action": "VARIETY", "seed_check": "FAILED"}).status_code == 200
        peter = next(f for f in c.get("/farms/plan").json() if f["household_id"] == "HH-DS-001")
        assert peter["rule"] == "R4h_unverified_seed"
        assert c.get("/scans/groups").json() == []


# --- Language preference and SMS delivery ---------------------------------------------------------------------
def test_sms_text_stays_plain_and_parts_are_counted():
    from crop_pilot.dispatch import approval
    assert approval.sms_safe("Don’t spray – rain due “soon”…") == 'Don\'t spray - rain due "soon"...'
    assert approval.sms_parts("a" * 160) == 1 and approval.sms_parts("a" * 161) == 2
    assert approval.sms_parts("Panda maharagwe sasa. " * 7) == 1                # Swahili fits the plain alphabet
    assert approval.sms_parts("’" + "a" * 100) == 2                               # one curly quote: UCS-2, 67 a part


def test_signed_message_goes_by_sms_with_plain_punctuation_and_language_pref(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from crop_pilot.api.main import app
    from crop_pilot.dispatch import approval
    monkeypatch.setattr(config, "DISABLE_LLM", True)
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "ck.db")
    run = asyncio.run(workflow.start_run(workflow.build_graph(InMemorySaver()), "HH-DS-003"))
    adv = next(a for a in approval.list_advisories() if a["run_id"] == run["run_id"])
    r = approval.approve(adv["id"], "Wanjiru Kamau", "Scout today – spray early if you see damage. ’",
                         citation="Citing plots:HH-DS-003 and weather_cache:MUTUINI@2026-10-14", languages=["en", "sw"])
    out = [o for o in approval.outbox() if o["advisory_id"] == adv["id"]]
    assert {o["language"] for o in out} == {"en", "sw"} and all(o["sms_parts"] >= 1 for o in out)
    en = next(o for o in out if o["language"] == "en")
    assert "–" not in en["message"] and "’" not in en["message"] and r["messages"]["en"] == en["message"]
    with TestClient(app) as c:
        prof = c.get("/households/HH-DS-003/profile").json()["plot"]
        assert prof["language"] == "sw" and prof["farmer_last_seen"] is None      # Grace prefers Kiswahili
        c.get("/farms/HH-DS-003/notifications")                                     # officer look: not "seen"
        assert c.get("/households/HH-DS-003/profile").json()["plot"]["farmer_last_seen"] is None
        c.get("/farms/HH-DS-003/notifications", params={"seen": True})              # farmer opened the app
        assert c.get("/households/HH-DS-003/profile").json()["plot"]["farmer_last_seen"]
        assert c.post("/farms/HH-DS-003/language", json={"language": "both"}).status_code == 200
        assert c.post("/farms/HH-DS-003/language", json={"language": "sheng"}).status_code == 422
        assert c.get("/households/HH-DS-003/profile").json()["plot"]["language"] == "both"

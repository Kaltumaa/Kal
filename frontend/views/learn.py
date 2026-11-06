"""Learn: pests, pesticides, weeds, soils, greenhouse, plus a 'what can I grow?' tool.

The same documents are what the advisory agent reads through the third-party filesystem MCP server.
"""
from __future__ import annotations

import html
import random

import pandas as pd
import streamlit as st

import api_client as api
import ui

SOILS = ["red loam", "black cotton", "sandy loam", "clay loam"]
GREENHOUSE = {"best": "Best", "yes": "Good", "nursery": "Nursery only", "no": "Field crop"}

STATUS_LABEL = {"TOO_HUMID": ("Too humid", "red"), "HUMID": ("A bit humid", "orange"), "IDEAL": ("Ideal", "green"),
                "DRY": ("A bit dry", "orange"), "TOO_DRY": ("Too dry", "red")}
GH_CROPS = ["Tomato", "Capsicum", "Cucumber", "Kale", "Spinach", "Strawberry"]


def show_assessment(a: dict) -> None:
    label, color = STATUS_LABEL[a["status"]]
    m = st.columns(3)
    m[0].metric("VPD", f"{a['vpd_kpa']:.2f} kPa", help="Vapour pressure deficit; 0.8–1.2 kPa is ideal in the day")
    m[1].metric("Dew point", f"{a['dew_point_c']:.1f} °C")
    m[2].metric(f"Best for {a['crop'] or 'most crops'}", f"{a['ideal_temp_c'][0]}–{a['ideal_temp_c'][1]} °C")
    st.markdown(f":{color}-badge[{label}] {a['meaning']}")
    st.markdown("\n".join(f"- {x}" for x in a["actions"]))


def greenhouse_check() -> None:
    with ui.section():
        st.markdown("**Check my greenhouse**")
        t_type, t_sensor = st.tabs(["Type readings", "Sensor feed"])
        with t_type:
            c = st.columns(3)
            crop = c[0].selectbox("Crop", GH_CROPS)
            temp = c[1].number_input("Temperature (°C)", -5.0, 60.0, 24.0, step=0.5)
            rh = c[2].number_input("Humidity (%)", 0.0, 100.0, 75.0, step=1.0)
            if st.button("Check", type="primary"):
                try:
                    st.session_state["gh_last"] = api.greenhouse_check(temp, rh, crop)
                except api.ApiError as exc:
                    st.error(str(exc.detail))
            if st.session_state.get("gh_last"):
                show_assessment(st.session_state["gh_last"])
        with t_sensor:
            rows = api.greenhouse_history("GH-1")
            sensor = [r for r in rows if r["source"] == "sensor"]
            if sensor:
                latest = sensor[0]
                st.caption(f"Latest from {latest['device_id'] or 'sensor'} at "
                           f"{latest['recorded_at'][:16].replace('T', ' ')} UTC")
                show_assessment(api.greenhouse_assess(latest["temp_c"], latest["rh_pct"]))
                trend = pd.DataFrame({"VPD (kPa)": [r["vpd_kpa"] for r in sensor[::-1]]},
                                     index=pd.RangeIndex(1, len(sensor) + 1, name="Reading"))
                st.line_chart(trend, height=170, color="#18181B", x_label="Reading", y_label="VPD (kPa)")
            else:
                st.caption("No sensor connected yet. Any device on this network can send readings:")
            st.code('curl -X POST http://<this-computer>:8000/greenhouse/readings -H "Content-Type: application/json" '
                    '-d \'{"greenhouse_id": "GH-1", "device_id": "esp32-1", "temp_c": 26.5, "rh_pct": 82}\'',
                    language="bash")
            if st.session_state.get("role", "officer") == "officer":
                if st.button("Demo: simulate a sensor reading"):
                    api.greenhouse_sensor_reading(round(random.uniform(18, 32), 1), round(random.uniform(45, 95)),
                                                  "demo-sensor")
                    st.rerun()
                st.caption("Demo only: no real sensor is connected; this sends a random reading through the same "
                           "endpoint a device would use.")


ui.header("Learn","Guides for officers and farmers. The advisory agent reads the same library.")
topics = api.knowledge_topics()
names = ["What can I grow?"] + [t["title"] for t in topics]
ICONS = {"What can I grow?": "potted_plant", "Pests & diseases": "bug_report", "Pesticides & safe use": "sanitizer",
         "Weeds": "grass", "Soils": "landscape", "Greenhouse growing": "home_work", "Crop calendar": "calendar_month",
         "Pest action thresholds": "target", "When it is safe to spray": "water_drop"}


GRID_CSS = """<style>
.cp-grid {display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 3rem; margin: 0 0 1rem;}
.cp-crop {border-top: 1px solid #F4F4F5; padding-top: 1.5rem; display: flex; flex-direction: column; gap: 0.5rem; font-size: 0.9375rem; color: #52525B; line-height: 1.625;}
.cp-crop .top {display: flex; justify-content: space-between; align-items: baseline; gap: 8px;}
.cp-crop .name {font-weight: 600; font-size: 1.25rem; letter-spacing: -0.025em; color: #18181B;}
.cp-crop .fit, .cp-crop .pill {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: #15803D;}
.cp-crop .fit {white-space: nowrap;} .cp-crop .fit.wait, .cp-crop .pill.wait {color: #B45309;} .cp-crop .fit.bad {color: #B91C1C;}
.cp-crop .pill::before {content: "•"; margin-right: 0.35rem;}
.cp-crop .k {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: #A1A1AA; margin-right: 0.4rem;}
.cp-crop .chk.bad {color: #18181B;} .cp-crop .chk.bad .k {color: #B45309;}
.cp-crop .tip {color: #71717A; padding-top: 0.5rem; border-top: 1px solid #F4F4F5; margin-top: auto;}
</style>"""
CHECK_LABEL = {"rain": "Rain", "temp": "Temperature", "soil": "Soil"}
# The fit score in plain words (the number stays in the backend; farmers see what it means).
FIT_WORDS = [(85, "Very suitable", "go"), (70, "Suitable", "go"), (40, "Possible with care", "wait"),
             (0, "Not suitable this season", "bad")]
NO_SEARCH = {"When it is safe to spray", "Pest action thresholds"}


def fit_words(score: int) -> tuple[str, str]:
    return next((w, cls) for floor, w, cls in FIT_WORDS if score >= floor)


search_markdown = ui.search_markdown



def crop_card(r: dict) -> str:
    """One crop as an HTML card: name and fit, plant-now pill, three plain checks, harvest month and a tip."""
    esc = html.escape
    pill = ("<span class='pill go'>Plant now</span>" if r["plant_now"] is True else
            "<span class='pill wait'>Wait for planting rain</span>" if r["plant_now"] is False else "")
    checks = "".join(f"<div class='chk{'' if c['ok'] else ' bad'}'><span class='k'>{'Not ideal' if not c['ok'] else CHECK_LABEL[c['kind']]}</span>"
                     f"{esc(c['text'])}</div>" for c in r.get("checks", []))
    meta = [f"Harvest ≈ <b>{esc(r['harvest_if_planted_now'])}</b>"] if r["harvest_if_planted_now"] else []
    meta.append(f"{r['days_to_maturity']} days")
    if r["greenhouse"] in ("best", "yes"):
        meta.append("greenhouse-friendly")
    words, cls = fit_words(r["score"])
    return (f"<div class='cp-crop'><div class='top'><span class='name'>{esc(r['crop'])}</span>"
            f"<span class='fit {cls}'>{words}</span></div>{pill}{checks}"
            f"<div class='meta'>{' · '.join(meta)}</div><div class='tip'>{esc(r['notes'])}</div></div>")


def crop_grid(items: list[dict]) -> None:
    st.markdown("<div class='cp-grid'>" + "".join(crop_card(r) for r in items) + "</div>", unsafe_allow_html=True)


def what_can_i_grow() -> None:
    outlook = {o["zone_id"]: o for o in api.season_outlook()}
    mine = st.session_state.get("farm_info", {}).get(st.session_state.get("my_farm") or "", {}).get("zone_id")
    zones = list(outlook)
    c = st.columns([1.3, 1, 1.4], vertical_alignment="bottom")
    ward = c[0].selectbox("Ward", zones, format_func=str.title, index=zones.index(mine) if mine in zones else 0)
    o = outlook[ward]
    gh = c[1].segmented_control("Greenhouse", ["No", "Yes"], default="No") == "Yes"
    adjust = c[2].toggle("Adjust the numbers myself")
    rain, temp, soil = o["expected_rain_mm"], o["mean_temp_c"], o["dominant_soil"]
    if adjust:
        a = st.columns(3)
        rain = a[0].number_input("Season rain (mm)", 100, 1500, int(rain), step=10)
        temp = a[1].number_input("Average temp (°C)", 8.0, 35.0, float(temp), step=0.5)
        soil = a[2].selectbox("Soil", SOILS, index=SOILS.index(soil))
    zone_now = next((z for z in api.overview()["zones"] if z["zone_id"] == ward), None)
    rain_7d = zone_now["rain_7d_mm"] if zone_now else None
    week = f" · :material/rainy: **{rain_7d:.0f} mm** forecast this week" if rain_7d is not None else ""
    diff = o["rain_vs_normal_pct"] - 100
    with ui.section():
        st.markdown(f"**{ward.title()} · {o['season']}**  \n"
                    f":material/water_drop: **{rain:.0f} mm** season rain"
                    + ("" if adjust else f" ({diff:+d}% vs normal)")
                    + f" · :material/thermostat: **{temp:.1f} °C** average · :material/landscape: **{soil.title()}**"
                    + week + (" · :material/home: greenhouse" if gh else ""))
        st.caption(("Your own numbers" if adjust else f"Source: {o['source']}") + " · `reference:season_outlook.csv`")
    try:
        results = api.suitability(rain, temp, soil, gh, rain_7d)
    except api.ApiError as exc:
        st.error(str(exc.detail))
        return
    q = st.text_input("Search crops", placeholder="e.g. beans, tomato", key="search-grow",
                      label_visibility="collapsed", icon=":material/search:")
    if q:
        results = [r for r in results if q.lower().strip() in r["crop"].lower()]
        if not results:
            st.info(f"No crop matches \"{q}\".")
            return
    st.markdown(GRID_CSS, unsafe_allow_html=True)
    best = [r for r in results if r["score"] >= 70 and r["plant_now"] is not False]
    later = [r for r in results if r["score"] >= 70 and r["plant_now"] is False]
    maybe = [r for r in results if 40 <= r["score"] < 70]
    poor = [r for r in results if r["score"] < 40]
    groups = [("Best choices now", "Suits this season and there is enough rain this week to plant.", best),
              ("Good fit, wait for planting rain", "Suits the season, but this week is too dry to plant. "
               "Plant after the next good rain.", later),
              ("Possible, with care", "Grows here, but one condition is not ideal: see the “Not ideal” line.",
               maybe)]
    for title, sub, items in groups:
        if items:
            st.markdown(f"##### {title} ({len(items)})")
            st.caption(sub)
            crop_grid(items)
    if poor:
        with st.expander(f"Not recommended this season ({len(poor)}): {', '.join(r['crop'] for r in poor)}"):
            crop_grid(poor)
    with st.expander("See all crops in one table"):
        st.dataframe(pd.DataFrame([{
            "Crop": r["crop"], "Fit": fit_words(r["score"])[0],
            "Plant now?": "—" if r["plant_now"] is None else ("Yes" if r["plant_now"] else "Not yet"),
            "Harvest if planted now": r["harvest_if_planted_now"] or "—",
            "Greenhouse": GREENHOUSE[r["greenhouse"]], "Drought tolerance": r["drought_tolerance"].title(),
            "Why": " ".join(r["reasons"])} for r in results]),
            hide_index=True, width="stretch")
    st.caption("Rain, temperature and soil are this area's conditions against what each crop needs. A “Not ideal” "
               "line is a condition that is not ideal here: the crop can still grow, but expect less, or follow the "
               "tip on that line.")
    st.caption("How suitable each crop is comes from a fixed crop table (rainfall, temperature, soil, greenhouse), "
               "not a guess. "
               "\"Plant now\" compares this week's forecast with each crop's planting-rain need "
               "(about 25 mm for most crops; 15 mm for sorghum and cowpeas).")


BLURB = {"What can I grow?": ("green", "Best crops for your area's season, soil and greenhouse"),
         "Pests & diseases": ("orange", "Spot Fall Armyworm, blight, aphids and bean fly early"),
         "Pesticides & safe use": ("red", "Registered options, protective gear, harvest waits"),
         "Weeds": ("green", "Striga, couch grass and when weeding matters most"),
         "Soils": ("orange", "pH targets, soil tests and soil care by type"),
         "Greenhouse growing": ("blue", "Temperature and humidity targets, plus a greenhouse check"),
         "Pest action thresholds": ("red", "When a confirmed pest is close enough to act on"),
         "When it is safe to spray": ("blue", "Spray-safety score bands and washout rules")}
# The crop calendar has its own page under My farm (per crop grown), so it is not a Learn slide.
topics = [t for t in topics if t["slug"] != "crop-calendar" and t["title"] != "Crop calendar"]
names = ["What can I grow?"] + [t["title"] for t in topics]
choice = st.session_state.get("learn_topic", names[0])
if choice not in names:
    choice = names[0]
for row in range(0, len(names), 3):
    cols = st.columns(3)
    for col, name in zip(cols, names[row:row + 3]):
        color, blurb = BLURB.get(name, ("green", ""))
        with ui.section(col):
            st.markdown(f"**{name}**")
            st.caption(blurb)
            if st.button("Viewing" if name == choice else "Open", key=f"topic-{name}", width="stretch",
                         type="primary" if name == choice else "secondary", disabled=name == choice):
                st.session_state["learn_topic"] = name
                st.rerun()
st.divider()
st.subheader(choice)
if choice == names[0]:
    what_can_i_grow()
else:
    topic = topics[names.index(choice) - 1]
    if topic["slug"] == "greenhouse":
        greenhouse_check()
    md = api.knowledge_topic(topic["slug"])
    q = "" if choice in NO_SEARCH else st.text_input(f"Search {choice.lower()}", key=f"search-{topic['slug']}",
                                                     placeholder="Type a word, e.g. armyworm, gloves, pH",
                                                     label_visibility="collapsed", icon=":material/search:")
    found = search_markdown(md, q) if q else md
    with ui.section():
        if found is None:
            st.info(f"Nothing in this guide mentions \"{q}\".")
        else:
            st.markdown(found)

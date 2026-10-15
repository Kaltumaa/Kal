"""Learn: pests, pesticides, weeds, soils, greenhouse, plus a 'what can I grow?' tool.

The same documents are what the advisory agent reads through the third-party filesystem MCP server.
"""
from __future__ import annotations

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
    with st.container(border=True):
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
                st.line_chart(trend, height=170, color="#1F7A4D", x_label="Reading", y_label="VPD (kPa)")
            else:
                st.caption("No sensor connected yet. Any device on this network can send readings:")
            st.code('curl -X POST http://<this-computer>:8000/greenhouse/readings -H "Content-Type: application/json" '
                    '-d \'{"greenhouse_id": "GH-1", "device_id": "esp32-1", "temp_c": 26.5, "rh_pct": 82}\'',
                    language="bash")
            if st.button("Simulate a sensor reading"):
                api.greenhouse_sensor_reading(round(random.uniform(18, 32), 1), round(random.uniform(45, 95)),
                                              "demo-sensor")
                st.rerun()
            st.caption("No real sensor is connected in this demo; the button sends a random reading through the same "
                       "endpoint a device would use.")


ui.header("Learn","Guides for officers and farmers. The advisory agent reads the same library.")
topics = api.knowledge_topics()
names = ["What can I grow?"] + [t["title"] for t in topics]
CARD = {  # title -> (material icon, colour, one-line description)
    "What can I grow?": ("potted_plant", "green", "Best crops for your ward's season, soil and greenhouse"),
    "Pests & diseases": ("bug_report", "orange", "Spot Fall Armyworm, blight, aphids and bean fly early"),
    "Pesticides & safe use": ("sanitizer", "red", "Registered options, protective gear, harvest waits"),
    "Weeds": ("grass", "green", "Striga, couch grass and when weeding matters most"),
    "Soils": ("landscape", "orange", "Soils around Nairobi, pH and keeping soil healthy"),
    "Greenhouse growing": ("home_work", "blue", "Best greenhouse crops, plus a humidity and heat check"),
    "Crop calendar": ("calendar_month", "blue", "When each crop grows, flowers and is ready"),
    "Pest action thresholds": ("target", "red", "When a pest is close enough to act on"),
    "When it is safe to spray": ("water_drop", "blue", "How rain changes whether spraying works"),
}
choice = st.session_state.get("learn_topic", names[0])
for start in range(0, len(names), 3):
    cols = st.columns(3)
    for col, name in zip(cols, names[start:start + 3]):
        icon, color, blurb = CARD.get(name, ("article", "green", ""))
        active = name == choice
        with col.container(border=True, height=150):
            st.markdown(f"**:{color}[:material/{icon}:]&nbsp; {name}**")
            st.caption(blurb)
            if st.button("Viewing" if active else "Open", key=f"topic-{name}", type="primary" if active else "secondary",
                         width="stretch", disabled=active):
                st.session_state["learn_topic"] = name
                st.rerun()
st.divider()
st.subheader(choice)

if choice == names[0]:
    outlook = {o["zone_id"]: o for o in api.season_outlook()}
    c = st.columns([1.2, 1, 1, 1, 1], vertical_alignment="bottom")
    ward = c[0].selectbox("Ward", list(outlook), format_func=str.title)
    o = outlook[ward]
    gh = c[4].selectbox("Greenhouse", ["No", "Yes"]) == "Yes"
    adjust = st.toggle("Adjust the numbers myself")
    if adjust:
        rain = c[1].number_input("Season rain (mm)", 100, 1500, int(o["expected_rain_mm"]), step=10)
        temp = c[2].number_input("Average temp (°C)", 8.0, 35.0, o["mean_temp_c"], step=0.5)
        soil = c[3].selectbox("Soil", SOILS, index=SOILS.index(o["dominant_soil"]))
    else:
        rain, temp, soil = o["expected_rain_mm"], o["mean_temp_c"], o["dominant_soil"]
        c[1].metric("Season rain", f"{rain:.0f} mm", f"{o['rain_vs_normal_pct'] - 100:+d}% vs normal")
        c[2].metric("Average temp", f"{temp:.1f} °C")
        c[3].metric("Soil", soil.title())
    st.caption(f"{o['season']} outlook for {ward.title()} · {o['source']} · `reference:season_outlook.csv`")
    try:
        results = api.suitability(rain, temp, soil, gh)
    except api.ApiError as exc:
        st.error(str(exc.detail))
        st.stop()
    st.dataframe(pd.DataFrame([{
        "Crop": r["crop"], "Fit": r["score"], "Greenhouse": GREENHOUSE[r["greenhouse"]],
        "Days to harvest": r["days_to_maturity"], "Drought tolerance": r["drought_tolerance"].title(),
        "Why": "; ".join(r["reasons"]), "Tip": r["notes"]} for r in results]),
        hide_index=True, width="stretch", height=460,
        column_config={"Fit": st.column_config.ProgressColumn("Fit", min_value=0, max_value=100, format="%d"),
                       "Why": st.column_config.TextColumn(width="large"), "Tip": st.column_config.TextColumn(width="medium")})
    st.caption("Scores come from a fixed crop table (rainfall, temperature, soil, greenhouse), not a guess.")
else:
    slug = topics[names.index(choice) - 1]["slug"]
    if slug == "greenhouse":
        greenhouse_check()
    with st.container(border=True):
        st.markdown(api.knowledge_topic(slug))

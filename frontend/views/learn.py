"""Learn: pests, pesticides, weeds, soils, greenhouse, plus a 'what can I grow?' tool.

The same documents are what the advisory agent reads through the third-party filesystem MCP server.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui

SOILS = ["red loam", "black cotton", "sandy loam", "clay loam"]
GREENHOUSE = {"best": "Best", "yes": "Good", "nursery": "Nursery only", "no": "Field crop"}

ui.header("Learn", "Guides for officers and farmers. The advisory agent reads the same library.")
topics = api.knowledge_topics()
names = ["What can I grow?"] + [t["title"] for t in topics]
choice = st.segmented_control("Topic", names, default=names[0], label_visibility="collapsed")

if choice in (None, names[0]):
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
    with st.container(border=True):
        st.markdown(api.knowledge_topic(slug))

"""Crop calendar: where each crop on the plot is in its growth stages, and which days are pest-watch days.

One calendar per crop the farmer grows (the main crop and the one grown with it), picked with a button.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import api_client as api
import ui

role, mine = st.session_state.get("role", "officer"), st.session_state.get("my_farm")
ui.header("Crop calendar", "Each crop's growth stages from its planting date, and the days to watch for pests.")
if role == "farmer" and mine:
    hid = mine
    st.markdown(f"**{ui.farm_label(hid)}**")
else:
    hid = st.selectbox("Farm", list(ui.names()), format_func=ui.farm_label)

p = api.household_profile(hid)
plot, calendars = p["plot"], p.get("calendars") or {}
days = plot.get("days_since_planting")
if not calendars:
    st.info("No crop recorded on this plot yet, so there is no calendar. Log a planting in Plot history.",
            icon=":material/help:")
    st.stop()

crops = list(calendars)
pick = st.segmented_control("Crop", crops, default=crops[0], key=f"cal-crop-{hid}",
                            help="Every crop growing on this plot. Pick one to see its calendar.") or crops[0]
cal_info = calendars[pick]
days = cal_info.get("days")                       # each crop from its own planting date
m = st.columns(3)
m[0].metric("Crop", pick + (" (main)" if cal_info.get("main") else ""))
m[1].metric("Planted", cal_info.get("planted") or "Not yet")
m[2].metric("Stage today", "Harvested" if cal_info.get("harvested") else
            ("Not planted" if days is None else f"{ui.stage_label(cal_info['stage_now'])}, day {days}"))

stages = cal_info["stages"]
if not stages:
    st.info(f"No calendar for {pick} in the Nairobi crop table yet.", icon=":material/help:")
    st.stop()
cal = pd.DataFrame([{"Stage": s["stage"].replace("_", " ").title(), "start": s["start_day"], "end": s["end_day"],
                     "Watch for": ", ".join(s["pests_to_watch"]) or "—",
                     "Pest risk": "Watch for pests" if s["pests_to_watch"] else "Lower risk"} for s in stages])
bars = alt.Chart(cal).mark_bar(cornerRadius=6, height=26).encode(
    x=alt.X("start:Q", title="Days after planting"), x2="end:Q",
    y=alt.Y("Stage:N", sort=None, title=None, axis=alt.Axis(labelOverlap=False, labelLimit=220, labelFontSize=12)),
    color=alt.Color("Pest risk:N", scale=alt.Scale(domain=["Watch for pests", "Lower risk"],
                                                   range=["#E9A23B", "#7DBE95"]), legend=alt.Legend(orient="top")),
    tooltip=["Stage", "start", "end", "Watch for"])
layers = [bars]
if days is not None:
    layers.append(alt.Chart(pd.DataFrame({"day": [days]})).mark_rule(color="#D64545", strokeWidth=3).encode(x="day:Q"))
    layers.append(alt.Chart(pd.DataFrame({"day": [days], "t": [f"Today (day {days})"]})).mark_text(
        align="left", dx=6, dy=-8, color="#D64545", fontWeight="bold").encode(x="day:Q", text="t:N", y=alt.value(0)))
st.altair_chart(alt.layer(*layers).properties(height=46 * len(cal) + 50), width="stretch")
st.dataframe(cal[["Stage", "start", "end", "Watch for"]].rename(columns={"start": "From day", "end": "To day"}),
             hide_index=True, width="stretch")
st.caption("Calendar for the Nairobi highlands (~1,700 m). Orange stages are when the pests in the pest-action "
           "thresholds can damage this crop. Each crop uses its own planting date from the field log; a crop "
           "grown with the main crop and not logged separately uses the main crop's date.")

"""Plot history (read-only): past seasons, rotation risk and the field log. The log grows when a farmer ticks a
reminder done."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui

ACTION_LABEL = {"PLANTING": "Planting", "VARIETY": "Variety / seed", "FERTILISER": "Fertiliser", "IRRIGATION": "Irrigation",
                "WEEDING": "Weeding", "SPRAYING": "Spraying", "HARVEST": "Harvest", "OBSERVATION": "Observation"}

role, mine = st.session_state.get("role", "officer"), st.session_state.get("my_farm")
ui.header("Plot history", "What has been grown and done on this plot. Past seasons shape the advice "
                          "(crop rotation, planting date, crop stage).")
if role == "farmer" and mine:
    hid = mine
    st.markdown(f"**{ui.farm_label(hid)}**")
else:
    hid = st.selectbox("Farm", list(ui.names()), format_func=ui.farm_label)

profile = api.household_profile(hid)
plot, rot = profile["plot"], profile["rotation"]
left, right = st.columns([1.1, 1], gap="large")
with left:
    st.subheader("Seasons on this plot")
    seasons = (plot.get("crop_history") or []) + [f"{plot.get('active_crop') or 'Nothing yet'} (this season)"]
    st.markdown(" → ".join(f"**{x}**" for x in seasons))
    color = {"HIGH": "red", "ELEVATED": "orange", "LOW": "green"}.get(rot.get("risk"), "gray")
    st.markdown(f":{color}-badge[Rotation: {(rot.get('risk') or 'unknown').title()}] {rot.get('note') or ''}")
    st.caption(f"Crop stage now: {ui.stage_label(plot.get('growth_stage'))}"
               + (f" · day {plot['days_since_planting']} after planting" if plot.get("days_since_planting") is not None
                  else ""))

    st.subheader("Field log")
    log = api.farm_actions(hid)
    if log:
        st.dataframe(pd.DataFrame([{
            "Date": a["action_date"], "Action": ACTION_LABEL.get(a["action"], a["action"]), "Crop": a["crop"] or "",
            "Details": a["details"] or "", "Entered by": f"{a['entered_by']} ({a['entered_by_role']})"} for a in log]),
            hide_index=True, width="stretch")
    else:
        st.caption("Nothing logged yet for this plot.")

with right:
    with st.container(border=True):
        st.markdown("**How the field log grows**")
        st.markdown("- Farmers tick their **Reminders** done; each finished job is added here.\n"
                    "- Entries show who reported them.\n"
                    "- Past seasons and the planting date come from the farm record the agent reads.")
        if role == "farmer":
            st.page_link("views/reminders.py", label="Open my reminders", icon=":material/alarm:")
    st.caption("This page is read-only. The agent never recommends buying inputs; logged inputs are history only.")

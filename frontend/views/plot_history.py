"""Plot history: past seasons, rotation risk and the field log. Farmers add entries (and finished reminders);
the officer view is read-only."""
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

CROPS = ["Maize", "Beans", "Kale", "Potato", "Tomato", "Sorghum", "Cowpeas", "Sweet Potato", "Groundnut"]
with right:
    if role == "farmer":
        with st.form("log-action", clear_on_submit=True, border=True):
            st.markdown("**Add to my plot history**")
            c = st.columns(2)
            action = c[0].selectbox("What did you do?", list(ACTION_LABEL), format_func=ACTION_LABEL.get)
            when = c[1].date_input("When", value=pd.Timestamp(st.session_state.get("demo_today", "2026-10-15")).date())
            crop = st.selectbox("Crop (needed for planting)", ["—"] + CROPS)
            details = st.text_input("Details", max_chars=300,
                                    placeholder="e.g. DH04 seed, 50 kg CAN top-dress, 2 h drip irrigation")
            if st.form_submit_button("Save to my plot history", type="primary", width="stretch"):
                try:
                    r = api.log_farm_action(hid, action, when.isoformat(), None if crop == "—" else crop, details,
                                            "farmer", None)
                    st.toast("Saved." + (" Your crop and planting date are updated, so the next advice uses them."
                                         if r["updated_record"] else ""), icon=":material/check:")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))
        st.caption("Saved as reported by you (farmer). Planting updates your farm record, so your officer's next "
                   "advice uses the new crop and date. You can also tick **Reminders** done to add entries.")
    else:
        with st.container(border=True):
            st.markdown("**How the field log grows**")
            st.markdown("- Farmers add what they did (planting, weeding, fertiliser, irrigation, spraying, harvest).\n"
                        "- Farmers' finished **Reminders** are added too.\n"
                        "- Each entry shows who reported it.")
        st.caption("Read-only for the officer. Logged inputs are history only; the agent never recommends buying "
                   "inputs.")

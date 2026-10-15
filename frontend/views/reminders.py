"""Farmer reminders: set your own reminders; tick one done and it goes into your plot's field log."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui

LABEL = {"WEEDING": "Weeding", "FERTILISER": "Fertiliser / top-dress", "IRRIGATION": "Irrigation",
         "SPRAYING": "Spraying", "OBSERVATION": "Check the crop (scouting)", "HARVEST": "Harvest",
         "VARIETY": "Buy / prepare seed"}

hid = st.session_state.get("my_farm")
ui.header("Reminders", "Set reminders for jobs on your farm. When you tick one done, it is added to your plot's "
                       "field log.")
if not hid:
    st.info("Reminders are for farmers. Switch \"I am\" to a farmer to use them.")
    st.stop()

left, right = st.columns([1, 1.4], gap="large")
with left:
    with st.form("new-reminder", clear_on_submit=True, border=True):
        st.markdown("**New reminder**")
        due = st.date_input("Select target date for reminder",
                            value=pd.Timestamp(st.session_state.get("demo_today", "2026-10-15")).date())
        what = st.selectbox("What to do", list(LABEL), format_func=LABEL.get)
        note = st.text_input("Note (optional)", max_chars=200, placeholder="e.g. second weeding, east side")
        if st.form_submit_button("Add reminder", type="primary", width="stretch"):
            try:
                api.create_reminder(hid, due.isoformat(), what, note)
                st.toast("Reminder added.", icon=":material/alarm:")
                st.rerun()
            except api.ApiError as exc:
                st.error(str(exc.detail))
    st.caption("A new reminder is private and not logged. Ticking it done records the job in your field log and "
               "the desk's activity log.")

with right:
    st.markdown("**My reminders**")
    items = api.reminders(hid)
    if not items:
        st.caption("No reminders yet.")
    for r in items:
        with st.container(border=True):
            c = st.columns([3, 1.4], vertical_alignment="center")
            c[0].markdown(f"**{LABEL.get(r['action'], r['action'])}** · due {r['due_date']}"
                          + (f"  \n<span class='cp-muted'>{r['note']}</span>" if r["note"] else ""),
                          unsafe_allow_html=True)
            if r["done"]:
                c[1].markdown(":green-badge[Done] ")
                c[1].caption(f"in field log #{r['field_log_id']}")
            elif c[1].checkbox("Mark reminder as done", key=f"rem-{r['id']}"):
                try:
                    api.reminder_done(r["id"])
                    st.toast("Done. Added to your field log.", icon=":material/check:")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))

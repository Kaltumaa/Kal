"""Sent messages (with the manual backup form). The audit trail lives in the database, the API (/telemetry)
and the backend terminal, not in the officer's menu."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui


def outbox() -> None:
    ui.header("Sent messages", "Officer-signed messages (simulated SMS), and the backup form for when the database is down.")
    degraded = not api.health()["ok"]
    t_sent, t_backup = st.tabs(["Sent", "Manual backup form"])
    with t_sent:
        if degraded:
            st.warning("Unavailable while the database is degraded. Use the manual backup form.")
        else:
            out = api.outbox()
            if not out:
                st.caption("No messages sent yet.")
            for o in out:
                with st.container(border=True):
                    st.markdown(f"**{o['household_id']}** <span class='cp-muted'>· signed by {o['officer_signature']}"
                                f" · {o['queued_at'][:16].replace('T', ' ')} UTC</span>", unsafe_allow_html=True)
                    st.write(o["message"])
    with t_backup:
        if degraded:
            st.error("Database failed its integrity check. Record decisions here; they sync later.")
        with st.form("manual"):
            c = st.columns(3)
            name = c[0].text_input("Your full name")
            hid = c[1].text_input("Household ID")
            verdict = c[2].selectbox("Decision", ["HOLD", "PLANT", "SPRAY"])
            note = st.text_area("Field note", max_chars=500, height=80)
            if st.form_submit_button("Save", type="primary"):
                try:
                    st.success(f"Saved ({api.manual_fallback(name, hid, verdict, note)['status']}).")
                except api.ApiError as exc:
                    st.error(str(exc.detail))
        manual = api.manual_fallback_list()
        if manual:
            st.dataframe(pd.DataFrame(manual), hide_index=True, width="stretch")

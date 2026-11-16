"""The signed-in officer's escalations: farms where the agent was not sure and asked for a manual diagnosis."""
from __future__ import annotations

import streamlit as st

import api_client as api
import auth
import ui

u = auth.require("extension_officer", "institution")
ui.header("Escalations", "The agent was not sure (unclear photo, low confidence, forecasts disagreeing) and asked "
                         "for your diagnosis instead of guessing.")
status = st.segmented_control("Show", ["OPEN", "RESOLVED"], default="OPEN",
                              format_func={"OPEN": "Waiting", "RESOLVED": "Resolved"}.get) or "OPEN"
try:
    items = api.escalations(auth.token(), status)
except api.ApiError as exc:
    auth.show_error(exc)
    st.stop()
if not items:
    st.info("Nothing here." if status == "RESOLVED" else "No escalations waiting for you.",
            icon=":material/task_alt:")
for e in items:
    with ui.section():
        st.markdown(f"**{ui.farm_label(e['household_id'])}** · {e.get('sub_county') or ''} · "
                    f"{e['created_at'][:16].replace('T', ' ')}")
        st.markdown("\n".join(f"- {r}" for r in e["reasons"]))
        st.caption(e["question"])
        if e["status"] == "RESOLVED":
            st.success(f"{e['resolved_by']}: {e['diagnosis']}")
        elif u["role"] == "extension_officer":
            with st.form(f"resolve-{e['id']}"):
                dx = st.text_area("Your diagnosis", height=80)
                if st.form_submit_button("Resolve", type="primary"):
                    try:
                        api.resolve_escalation(auth.token(), e["id"], dx)
                        st.rerun()
                    except api.ApiError as exc:
                        auth.show_error(exc)

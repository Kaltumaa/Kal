"""Activity log (audit trail) and Sent messages (with the manual backup form)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui


def telemetry() -> None:
    ui.header("Activity log", "Every tool call, model call, blocked attempt and officer decision.")
    try:
        rows = api.telemetry()
    except api.ApiError as exc:
        st.warning(f"Unavailable: {exc.detail}")
        return
    if not rows:
        st.caption("Nothing logged yet.")
        return
    df = pd.DataFrame(rows)
    runs = ["All runs"] + sorted(df["run_id"].unique().tolist(), reverse=True)
    pick = st.selectbox("Run", runs)
    if pick != "All runs":
        df = df[df["run_id"] == pick]
    m = st.columns(4)
    m[0].metric("Actions logged", len(df))
    m[1].metric("MCP tool calls", int(df["server"].isin(["crop-pilot", "filesystem"]).sum()))
    m[2].metric("Model tokens", f'{int(df.loc[df["server"] == "ollama", "token_estimate"].fillna(0).sum()):,}')
    m[3].metric("Blocked attempts", int((df["status"] == "blocked").sum()))
    view = df[["ts", "run_id", "server", "tool", "actor", "status", "latency_ms", "token_estimate", "approved_by",
               "inputs_json", "output_json"]].rename(columns={
        "ts": "Time", "run_id": "Run", "server": "Server", "tool": "Tool", "actor": "Actor", "status": "Status",
        "latency_ms": "ms", "token_estimate": "Tokens", "approved_by": "Approved by", "inputs_json": "Inputs",
        "output_json": "Output"})
    st.dataframe(view, hide_index=True, width="stretch", height=480,
                 column_config={"ms": st.column_config.NumberColumn(format="%.0f")})


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

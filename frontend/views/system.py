"""Activity log (readable audit trail) and Sent messages (with the manual backup form)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui


STEP_TEXT = {
    "planner": "Planned the steps", "get_plot_context": "Read and cleaned the farm record",
    "get_rainfall_outlook": "Checked the rain forecast", "get_pest_reports": "Checked confirmed pest reports",
    "get_weather_pattern": "Checked the season's rainfall pattern", "read_text_file": "Read a guidance document",
    "read_file": "Read a guidance document", "list_directory": "Looked through the guidance library",
    "draft_advisory": "Saved the draft for review", "schedule_followup": "Booked a follow-up for the officer",
    "self_check": "Self-checked the draft", "approve_and_dispatch": "Officer signed; SMS queued",
    "reject": "Officer rejected the draft", "execution_complete": "Run closed", "close_followup": "Follow-up done",
    "review_field_scan": "Officer reviewed a farmer photo", "log_plot_action": "Plot history entry added",
    "update_forecast": "New rain forecast recorded", "ward_batch": "Drafted a whole ward",
}
WHO_TEXT = {"crop-pilot": "Mkulima Hub tools (MCP)", "filesystem": "Guidance library (MCP)", "ollama": "Local AI",
            "guard": "Safety guard", "graph": "Workflow", "officer": "Officer", "farmer": "Farmer", "feed": "Data feed",
            "none": "Safety guard"}


def _step(tool: str) -> str:
    if tool.startswith("chat:"):
        return "AI " + ("chose the next step" if "gatherer" in tool else "wrote the explanation and SMS")
    if tool.startswith("vision:"):
        return "Local AI described a plant photo"
    return STEP_TEXT.get(tool, tool.replace("_", " "))


def activity_log() -> None:
    ui.header("Activity log", "Every step the agent took and every decision a person made, with who approved it.")
    try:
        rows = api.telemetry()
    except api.ApiError as exc:
        st.warning(f"Unavailable: {exc.detail}")
        return
    if not rows:
        st.caption("Nothing logged yet. Run the agent from the Review queue.")
        return
    df = pd.DataFrame(rows)
    names = ui.names()
    runs = {}
    for r in rows:
        if r["run_id"].startswith("run-") and r["run_id"] not in runs:
            hid = next((x["inputs_json"] for x in rows if x["run_id"] == r["run_id"] and x["tool"] == "planner"), "")
            farm = next((h for h in names if h in (hid or "")), None)
            runs[r["run_id"]] = f"{names.get(farm, 'Farm')} · {r['ts'][5:16].replace('T', ' ')}"
    pick = st.selectbox("Show", ["Everything"] + list(runs), format_func=lambda k: k if k == "Everything" else runs[k])
    if pick != "Everything":
        df = df[df["run_id"] == pick]
    m = st.columns(4)
    m[0].metric("Steps logged", len(df))
    m[1].metric("Tool calls (MCP)", int(df["server"].isin(["crop-pilot", "filesystem"]).sum()))
    m[2].metric("Blocked by safety guard", int((df["status"] == "blocked").sum()))
    m[3].metric("Signed by an officer", int(df["approved_by"].notna().sum()))
    view = pd.DataFrame({
        "Time": df["ts"].str[11:19], "What happened": df["tool"].map(_step), "Done by": df["server"].map(WHO_TEXT)
        .fillna(df["server"]), "Tool": df["tool"], "Result": df["status"].map({"ok": "✓ ok", "blocked": "⛔ blocked",
                                                                                  "error": "⚠ problem"}),
        "Person": df["actor"].where(df["actor"] != "agent", ""), "Approved by": df["approved_by"].fillna("")})
    st.dataframe(view, hide_index=True, width="stretch", height=440)
    with st.expander("Technical details (inputs, outputs, timing, tokens)"):
        st.dataframe(df[["id", "ts", "run_id", "server", "tool", "actor", "status", "latency_ms", "token_estimate",
                         "approved_by", "call_hash", "inputs_json", "output_json"]], hide_index=True, width="stretch",
                     height=360)


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
                    st.markdown(f"**{ui.farm_label(o['household_id'])}** <span class='cp-muted'>· signed by {o['officer_signature']}"
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

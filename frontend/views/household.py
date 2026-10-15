"""Household page: one plot's history against its crop calendar, its ward's weather pattern and its advice."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import api_client as api
import ui

ui.header("Households", "One plot at a time: its history, where it is in the crop calendar, and the advice it got.")
try:
    ids = api.households()
except api.ApiError as exc:
    st.error(str(exc.detail))
    st.stop()
top = st.columns([1.2, 3], vertical_alignment="bottom")
hid = top[0].selectbox("Household", ids)
if top[1].button("Draft new advice for this household", icon=":material/edit_note:"):
    with st.spinner("Agent working… (1–3 min on CPU)"):
        try:
            res = api.run_agent(hid, "")
            st.toast(f"Draft ready: {res['advisory'].get('verdict') or 'no advice'}. Sign it in the Review queue.",
                     icon=":material/check:")
        except api.ApiError as exc:
            st.error(str(exc.detail))
p = api.household_profile(hid)
plot, rot, pat = p["plot"], p["rotation"], p.get("pattern") or {}
crop = plot.get("active_crop") or "No crop recorded"
days = plot.get("days_since_planting")
stage = (plot.get("growth_stage") or "—").replace("_", " ").title()

m = st.columns(4)
m[0].metric("Crop", crop)
m[1].metric("Ward", (plot.get("zone_id") or "—").title())
m[2].metric("Days since planting", days if days is not None else "Not planted")
m[3].metric("Stage", stage)
if plot.get("injection_detected"):
    st.error("This household's notes contained instruction-like text and were redacted. Verify the record in person.",
             icon=":material/gpp_bad:")

st.subheader("Crop calendar")
if p["calendar"]:
    cal = pd.DataFrame([{"Stage": s["stage"].replace("_", " ").title(), "start": s["start_day"], "end": s["end_day"],
                         "Watch for": ", ".join(s["pests_to_watch"]) or "—",
                         "Pest risk": "Watch for pests" if s["pests_to_watch"] else "Lower risk"} for s in p["calendar"]])
    bars = alt.Chart(cal).mark_bar(cornerRadius=6, height=26).encode(
        x=alt.X("start:Q", title="Days after planting"), x2="end:Q", y=alt.Y("Stage:N", sort=None, title=None, axis=alt.Axis(labelOverlap=False, labelLimit=220, labelFontSize=12)),
        color=alt.Color("Pest risk:N", scale=alt.Scale(domain=["Watch for pests", "Lower risk"],
                                                       range=["#E9A23B", "#7DBE95"]), legend=alt.Legend(orient="top")),
        tooltip=["Stage", "start", "end", "Watch for"])
    layers = [bars]
    if days is not None:
        today_rule = alt.Chart(pd.DataFrame({"day": [days]})).mark_rule(color="#D64545", strokeWidth=3).encode(x="day:Q")
        label = alt.Chart(pd.DataFrame({"day": [days], "t": [f"Today (day {days})"]})).mark_text(
            align="left", dx=6, dy=-8, color="#D64545", fontWeight="bold").encode(x="day:Q", text="t:N", y=alt.value(0))
        layers += [today_rule, label]
    st.altair_chart(alt.layer(*layers).properties(height=46 * len(cal) + 50), width="stretch")
    st.caption("Calendar for the Nairobi highlands (~1,700 m). Orange stages are when pests listed in the "
               "pest-action thresholds can damage this crop.")
else:
    st.info("No crop recorded, so there is no calendar yet. The agent will ask for a field visit.", icon=":material/help:")

left, right = st.columns(2, gap="large")
with left:
    with st.container(border=True):
        st.markdown("**Plot history**")
        seq = rot.get("sequence") or " > ".join((plot.get("crop_history") or []) + [f"{crop} (now)"])
        st.markdown(f"`{seq}`")
        color = {"HIGH": "red", "ELEVATED": "orange", "LOW": "green"}.get(rot.get("risk"), "gray")
        st.markdown(f":{color}-badge[Rotation risk: {(rot.get('risk') or 'unknown').title()}]")
        if rot.get("note"):
            st.caption(rot["note"])
        if plot.get("data_quality"):
            with st.expander(f"Record repairs ({len(plot['data_quality'])})"):
                st.markdown("\n".join(f"- {q}" for q in plot["data_quality"]))
with right:
    with st.container(border=True):
        st.markdown("**Ward weather pattern**")
        if pat.get("season_anomaly_pct") is not None:
            st.markdown(f"Season outlook **{pat['season_expected_mm']:.0f} mm** "
                        f"({pat['season_anomaly_pct']:+d}% vs normal) · last 20 days at "
                        f"**{pat.get('recent_pct_of_normal')}%** of normal")
        onset = {"FALSE_START_RISK": ("orange", "False-start risk"), "LATE": ("orange", "Rains late"),
                 "ONSET": ("green", "Rains started"), "NOT_YET": ("gray", "Rains not started")}.get(pat.get("onset"),
                                                                                                 ("gray", "Unknown"))
        st.markdown(f":{onset[0]}-badge[{onset[1]}]")
        for line in pat.get("advice", []):
            st.caption(line)

st.subheader("Advice for this household")
if p["advisories"]:
    st.dataframe(pd.DataFrame([{"Drafted": a["created_at"][:16].replace("T", " "), "Advice": a["verdict"] or "—",
                                "Status": ui.STATUS_TEXT.get(a["status"], a["status"]),
                                "Signed by": a.get("officer_signature") or "", "Message": a["farmer_message"]}
                               for a in p["advisories"]]), hide_index=True, width="stretch")
else:
    st.caption("No advice drafted yet.")
if p["followups"]:
    st.markdown("**Follow-ups**")
    st.dataframe(pd.DataFrame([{"Due": f["due_date"], "What": f["kind"].replace("_", " ").title(),
                                "Why": f["reason"], "Status": f["status"].title(), "Closed by": f.get("closed_by") or ""}
                               for f in p["followups"]]), hide_index=True, width="stretch")

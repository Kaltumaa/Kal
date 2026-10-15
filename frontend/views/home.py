"""Dashboard: this week's rainfall and pest picture across Dagoretti South, and what needs the officer."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui


def ward_advice(z: dict) -> str:
    if z["washout_risk"]:
        return "Hold: heavy rain"
    if z["planting_window"] == "OPEN":
        return "Plant now"
    return "Wait for rains"


ui.header("Dashboard", "Rainfall and verified pest signals across Dagoretti South this week.")
try:
    ov, advs, scans = api.overview(), api.advisories(), api.scans()
except api.ApiError as exc:
    st.error(str(exc.detail))
    st.stop()

to_review = sum(a["status"] in ("PENDING_REVIEW", "SECURITY_LOCK") for a in advs)
verified = [a for a in ov["alerts"] if a["verified"]]
c = st.columns(4)
c[0].metric("Drafts to review", to_review)
c[1].metric("Messages sent", sum(a["status"] == "APPROVED" for a in advs))
c[2].metric("Verified pest alerts", len(verified))
c[3].metric("Photos to check", sum(s["status"] == "UNVERIFIED" for s in scans))

st.subheader("Wards this week")
wards = pd.DataFrame([{
    "Ward": z["zone_id"].title(), "Advice": ward_advice(z), "Rain next 24 h (mm)": z["rain_24h_mm"],
    "Rain next 7 days (mm)": z["rain_7d_mm"], "Spray safety": z["spray_safety_index"], "Storm risk": z["storm_risk"].title(),
} for z in ov["zones"]])
st.dataframe(wards, hide_index=True, width="stretch", column_config={
    "Spray safety": st.column_config.ProgressColumn("Spray safety", min_value=0, max_value=100, format="%d",
                                                    help="Below 40 = unsafe: rain would wash the product off"),
})

left, right = st.columns([1.4, 1], gap="large")
with left:
    st.subheader("Map")
    pts = [{"lat": h["lat"], "lon": h["lon"], "color": "#1F7A4D", "size": 60} for h in ov["households"]
           if h["lat"] is not None]
    pts += [{"lat": a["lat"], "lon": a["lon"], "color": "#D64545", "size": 180} for a in verified if a["lat"] is not None]
    st.map(pd.DataFrame(pts), latitude="lat", longitude="lon", color="color", size="size", zoom=12, height=340)
    st.caption("Green: households · Red: verified pest alerts")
with right:
    st.subheader("Pest reports")
    alerts = pd.DataFrame([{"Pest": a["pest"], "Ward": a["zone_id"].title(), "Severity": a["severity"].title(),
                            "Verified": bool(a["verified"]), "Date": a["reported_at"]} for a in ov["alerts"]])
    st.dataframe(alerts, hide_index=True, width="stretch", height=340)
    st.caption("Only verified reports are used by the agent.")

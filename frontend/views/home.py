"""Dashboard: in plain words, what should happen in each ward this week, and what is waiting for the officer."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import api_client as api
import ui


def field_work(z: dict) -> tuple[str, str]:
    """(headline, reason) for planting / field work in a ward."""
    if z["washout_risk"]:
        return ":red[:material/block: **Hold all field work**]", f"Heavy rain coming: {z['rain_72h_mm']:.0f} mm in 3 days."
    if z["planting_window"] == "OPEN":
        return ":green[:material/grass: **Good time to plant**]", f"{z['rain_7d_mm']:.0f} mm of rain expected this week."
    return (":orange[:material/hourglass_top: **Too dry to plant yet**]",
            f"Only {z['rain_7d_mm']:.0f} mm expected this week; planting needs about 25 mm.")


def spraying(z: dict) -> str:
    return {"SAFE": ":green[OK to spray]", "CAUTION": ":orange[Spray only if no rain in the next 6 hours]",
            "UNSAFE": ":red[Do not spray: rain would wash it off]"}[z["spray_band"]]


ui.header("This week in Dagoretti South", "What to tell farmers in each ward, and what is waiting for you.")
try:
    ov, advs, scans = api.overview(), api.advisories(), api.scans()
except api.ApiError as exc:
    st.error(str(exc.detail))
    st.stop()
today = date.fromisoformat(ov["today"])

# --- What is waiting for you -----------------------------------------------------------------------
to_sign = sum(a["status"] == "PENDING_REVIEW" for a in advs)
locked = sum(a["status"] == "SECURITY_LOCK" for a in advs)
photos = sum(s["status"] == "UNVERIFIED" for s in scans)
st.subheader("Waiting for you")
if not (to_sign or locked or photos):
    st.success("All caught up. Draft advice for a ward from the **Review queue**.", icon=":material/task_alt:")
todo = st.columns(3) if (to_sign or locked or photos) else []
for col, (page, label, icon, n) in zip(todo, [
        ("views/queue.py", f"{to_sign} message{'s' if to_sign != 1 else ''} to check and sign", ":material/edit_note:", to_sign),
        ("views/queue.py", f"{locked} suspicious record{'s' if locked != 1 else ''} to review", ":material/gpp_maybe:", locked),
        ("views/scan.py", f"{photos} farmer photo{'s' if photos != 1 else ''} to confirm", ":material/photo_camera:", photos)]):
    with col:
        st.page_link(page, label=label, icon=icon, disabled=not n)

# --- Ward by ward -----------------------------------------------------------------------------------
st.subheader("Ward by ward")
recent_pests: dict[str, list[dict]] = {}
for a in ov["alerts"]:
    if a["verified"] and (today - date.fromisoformat(a["reported_at"][:10])).days <= 30:
        recent_pests.setdefault(a["zone_id"], []).append(a)
households = pd.DataFrame(ov["households"])

for row in range(0, len(ov["zones"]), 3):
    cols = st.columns(3)
    for col, z in zip(cols, ov["zones"][row:row + 3]):
        headline, reason = field_work(z)
        pests = recent_pests.get(z["zone_id"], [])
        pest_line = ("No confirmed pests in the last month" if not pests else
                     ", ".join(sorted({p["pest"] for p in pests})) + " confirmed")
        n = int((households["zone_id"] == z["zone_id"]).sum()) if not households.empty else 0
        with col.container(border=True):
            st.markdown(f"#### {z['zone_id'].title()}")
            st.markdown(headline)
            st.caption(reason)
            st.markdown(f":material/water_drop: {spraying(z)}")
            st.markdown(f":material/bug_report: {':red[' + pest_line + ']' if pests else pest_line}")
            st.caption(f"{n} household{'s' if n != 1 else ''} on the desk's list")

# --- Details ----------------------------------------------------------------------------------------
with st.expander("Map of households and confirmed pest reports"):
    pts = [{"lat": h["lat"], "lon": h["lon"], "color": "#1F7A4D", "size": 60} for h in ov["households"]
           if h["lat"] is not None]
    pts += [{"lat": a["lat"], "lon": a["lon"], "color": "#D64545", "size": 180}
            for zone in recent_pests.values() for a in zone if a["lat"] is not None]
    st.map(pd.DataFrame(pts), latitude="lat", longitude="lon", color="color", size="size", zoom=12, height=320)
    st.caption("Green: households · Red: pest reports confirmed by an officer in the last month")
with st.expander("Rainfall numbers behind this page"):
    st.dataframe(pd.DataFrame([{"Ward": z["zone_id"].title(), "Next 24 h (mm)": z["rain_24h_mm"],
                                "Next 3 days (mm)": z["rain_72h_mm"], "Next 7 days (mm)": z["rain_7d_mm"],
                                "Storm risk": z["storm_risk"].title(), "Spray-safety score (0–100)": z["spray_safety_index"],
                                "Forecast issued": z["forecast_issued_at"]} for z in ov["zones"]]),
                 hide_index=True, width="stretch")
    st.caption("Synthetic CHIRPS-style forecast for the demo. The spray-safety score falls with rain in the next "
               "24–72 hours and storm risk; below 40 means do not spray.")

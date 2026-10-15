"""Dashboard: in plain words, what should happen in each ward this week, and what is waiting for the officer."""
from __future__ import annotations

import html
from datetime import date

import pandas as pd
import streamlit as st

import api_client as api
import ui

MAIN_CROPS = {"Maize", "Beans", "Potato", "Kale"}


def tag(text: str, color: str) -> str:
    return f'<span class="cp-tag t-{color}">{html.escape(text)}</span>'


def do_this(z: dict) -> tuple[str, str]:
    """(tag html, reason) for field work in a ward."""
    if z["washout_risk"]:
        return tag("Hold all field work", "red"), f"Heavy rain: {z['rain_72h_mm']:.0f} mm in the next 3 days."
    if MAIN_CROPS <= set(z["plant_now"]):
        return tag("Plant now", "green"), f"{z['rain_7d_mm']:.0f} mm of rain expected this week."
    if z["plant_now"]:
        return (tag("Dry-season crops only", "orange"),
                f"Only {z['rain_7d_mm']:.0f} mm this week: too dry for maize and beans (they need about 25 mm).")
    return tag("Too dry to plant", "gray"), f"Only {z['rain_7d_mm']:.0f} mm expected this week."


def spraying(z: dict) -> str:
    return {"SAFE": tag("OK", "green"), "CAUTION": tag("Only if no rain for 6 h", "orange"),
            "UNSAFE": tag("Don't spray", "red")}[z["spray_band"]]


ui.header("This week", "What to tell farmers in each ward, and what is waiting for you.")
try:
    ov, advs, scans = api.overview(), api.advisories(), api.scans()
except api.ApiError as exc:
    st.error(str(exc.detail))
    st.stop()
today = date.fromisoformat(ov["today"])
recent_pests: dict[str, list[dict]] = {}
for a in ov["alerts"]:
    if a["verified"] and (today - date.fromisoformat(a["reported_at"][:10])).days <= 30:
        recent_pests.setdefault(a["zone_id"], []).append(a)

to_sign = sum(a["status"] == "PENDING_REVIEW" for a in advs)
locked = sum(a["status"] == "SECURITY_LOCK" for a in advs)
photos = sum(s["status"] == "UNVERIFIED" for s in scans)
k = st.columns(4)
k[0].metric("Messages to sign", to_sign)
k[1].metric("Suspicious records", locked)
k[2].metric("Farmer photos to confirm", photos)
k[3].metric("Pest outbreaks confirmed", sum(len(v) for v in recent_pests.values()), help="Officer-verified, last 30 days")
links = st.columns(4)
if to_sign or locked:
    links[0].page_link("views/queue.py", label="Open review queue", icon=":material/arrow_forward:")
if photos:
    links[2].page_link("views/scan.py", label="Check photos", icon=":material/arrow_forward:")

st.subheader("Ward by ward")
rows = []
for z in ov["zones"]:
    action, reason = do_this(z)
    plantable = z["plant_now"] if MAIN_CROPS <= set(z["plant_now"]) else [c for c in z["plant_now"] if c not in MAIN_CROPS]
    pests = sorted({p["pest"] for p in recent_pests.get(z["zone_id"], [])})
    rows.append(
        f'<tr><td><b>{html.escape(z["zone_id"].title())}</b></td>'
        f'<td>{action}<small>{html.escape(reason)}</small></td>'
        f'<td>{html.escape(", ".join(plantable)) if plantable else "—"}</td>'
        f'<td>{spraying(z)}</td>'
        f'<td>{tag(", ".join(pests), "red") if pests else tag("None", "gray")}</td></tr>')
st.markdown('<div class="cp-wards"><table><thead><tr><th>Ward</th><th>Do this</th><th>Can plant now</th>'
            '<th>Spraying</th><th>Pests confirmed</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>",
            unsafe_allow_html=True)
st.caption("Pests: confirmed by an officer in the last 30 days. Planting: maize, beans and potato need about 25 mm of "
           "rain in a week; sorghum and cowpeas about 15 mm.")

left, right = st.columns(2, gap="large")
with left:
    with st.expander("Map of households and pest reports"):
        pts = [{"lat": h["lat"], "lon": h["lon"], "color": "#1F7A4D", "size": 60} for h in ov["households"]
               if h["lat"] is not None]
        pts += [{"lat": a["lat"], "lon": a["lon"], "color": "#D64545", "size": 180}
                for zone in recent_pests.values() for a in zone if a["lat"] is not None]
        st.map(pd.DataFrame(pts), latitude="lat", longitude="lon", color="color", size="size", zoom=12, height=300)
        st.caption("Green: households · Red: confirmed pest reports")
with right:
    with st.expander("Rainfall numbers behind this page"):
        st.dataframe(pd.DataFrame([{"Ward": z["zone_id"].title(), "24 h (mm)": z["rain_24h_mm"],
                                    "3 days (mm)": z["rain_72h_mm"], "7 days (mm)": z["rain_7d_mm"],
                                    "Storm": z["storm_risk"].title(), "Spray score": z["spray_safety_index"]}
                                   for z in ov["zones"]]), hide_index=True, width="stretch")
        st.caption("Synthetic CHIRPS-style forecast. Spray score below 40 means do not spray.")

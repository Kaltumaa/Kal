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
    if MAIN_CROPS <= set(z["plant_now"]) and z["pattern"].get("onset") == "FALSE_START_RISK":
        return (tag("Plant in two batches", "orange"),
                f"{z['rain_7d_mm']:.0f} mm coming, but after a dry spell: plant half now, half after the next wet week.")
    if MAIN_CROPS <= set(z["plant_now"]):
        return tag("Plant now", "green"), f"{z['rain_7d_mm']:.0f} mm of rain expected this week."
    if z["plant_now"]:
        return (tag("Dry-season crops only", "orange"),
                f"Only {z['rain_7d_mm']:.0f} mm this week: too dry for maize and beans (they need about 25 mm).")
    return tag("Too dry to plant", "gray"), f"Only {z['rain_7d_mm']:.0f} mm expected this week."


def season_cell(p: dict) -> str:
    cls, pct = p.get("season_class"), p.get("season_anomaly_pct")
    season = {"BELOW": tag(f"{abs(pct)}% below normal", "orange"), "ABOVE": tag(f"{pct}% above normal", "orange"),
              "NEAR": tag("Near normal", "green")}.get(cls, tag("Unknown", "gray"))
    rains = {"FALSE_START_RISK": "Rain after a dry spell: false-start risk", "LATE": "Rains running late",
             "ONSET": "Rains have started", "NOT_YET": "Rains not started yet"}.get(p.get("onset"), "")
    recent = p.get("recent_pct_of_normal")
    detail = f"{rains} (last 20 days at {recent}% of normal)" if recent is not None else rains
    return f"{season}<small>{html.escape(detail)}</small>"


def spraying(z: dict) -> str:
    return {"SAFE": tag("OK", "green"), "CAUTION": tag("Only if no rain for 6 h", "orange"),
            "UNSAFE": tag("Don't spray", "red")}[z["spray_band"]]


ui.header("This week", "What to tell farmers in each ward, and what is waiting for you.")
try:
    ov, advs, scans, fups = api.overview(), api.advisories(), api.scans(), api.followups()
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
due_week = [f for f in fups if (date.fromisoformat(f["due_date"]) - today).days <= 7]
k[2].metric("Follow-ups due this week", len(due_week), help="Scheduled by the agent after each draft")
k[3].metric("Farmer photos to confirm", photos)
links = st.columns(4)
if to_sign or locked:
    links[0].page_link("views/queue.py", label="Open review queue", icon=":material/arrow_forward:")
if photos:
    links[3].page_link("views/scan.py", label="Check photos", icon=":material/arrow_forward:")

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
        f'<td>{season_cell(z["pattern"])}</td>'
        f'<td>{spraying(z)}</td>'
        f'<td>{tag(", ".join(pests), "red") if pests else tag("None", "gray")}</td></tr>')
st.markdown('<div class="cp-wards"><table><thead><tr><th>Ward</th><th>Do this</th><th>Can plant now</th>'
            '<th>Season &amp; rains</th><th>Spraying</th><th>Pests confirmed</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>",
            unsafe_allow_html=True)
st.caption("Pests: confirmed by an officer in the last 30 days. Planting: maize, beans and potato need about 25 mm of "
           "rain in a week; sorghum and cowpeas about 15 mm.")

st.subheader("Desk follow-ups")
if not fups:
    st.caption("No follow-ups yet. The agent schedules one after every draft (re-scout, re-check after rain, "
               "field visit...).")
else:
    fl, fr = st.columns([2.2, 1], gap="large")
    fl.dataframe(pd.DataFrame([{"Due": f["due_date"], "Household": f["household_id"],
                                "What": f["kind"].replace("_", " ").title(), "Why": f["reason"]} for f in fups]),
                 hide_index=True, width="stretch", height=min(300, 38 + 35 * len(fups)))
    with fr.form("close-followup"):
        pick = st.selectbox("Mark as done", fups, format_func=lambda f: f"{f['due_date']} · {f['household_id']} · "
                                                                        f"{f['kind'].replace('_', ' ').title()}")
        who = st.text_input("Your full name")
        if st.form_submit_button("Done", type="primary", width="stretch"):
            try:
                api.close_followup(pick["id"], who)
                st.rerun()
            except api.ApiError as exc:
                st.error(str(exc.detail))

st.subheader("Rainfall pattern")
pc = st.columns([1, 3], gap="large")
ward = pc[0].selectbox("Ward", [z["zone_id"] for z in ov["zones"]], format_func=str.title, key="pattern_ward")
zp = next(z for z in ov["zones"] if z["zone_id"] == ward)["pattern"]
if zp.get("season_expected_mm"):
    pc[0].metric("Season outlook", f"{zp['season_expected_mm']:.0f} mm", f"{zp['season_anomaly_pct']:+d}% vs normal",
                 delta_color="off")
for line in zp.get("advice", []):
    pc[0].caption(line)
if zp["dekads"]:
    chart = pd.DataFrame([{"10-day period": d["period"], "This year (mm)": d["rain_mm"], "Normal (mm)": d["normal_mm"]}
                          for d in zp["dekads"]]).set_index("10-day period")
    pc[1].bar_chart(chart, stack=False, color=["#1F7A4D", "#C9D6CC"], height=260)
    pc[1].caption("Rain in each 10-day period (CHIRPS-style, synthetic) against the long-term average.")

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
        with st.form("new-forecast"):
            st.markdown("**A new forecast arrived?** Record it; drafts built on the old one are blocked until re-run.")
            f = st.columns(5)
            wz = f[0].selectbox("Ward", [z["zone_id"] for z in ov["zones"]], format_func=str.title)
            cur = next(z for z in ov["zones"] if z["zone_id"] == wz)
            r24 = f[1].number_input("24 h", 0.0, 500.0, float(cur["rain_24h_mm"]))
            r72 = f[2].number_input("3 days", 0.0, 800.0, float(cur["rain_72h_mm"]))
            r7d = f[3].number_input("7 days", 0.0, 1500.0, float(cur["rain_7d_mm"]))
            storm = f[4].selectbox("Storm", ["LOW", "MODERATE", "HIGH"], index=["LOW", "MODERATE", "HIGH"].index(cur["storm_risk"]))
            if st.form_submit_button("Save forecast"):
                try:
                    res = api.update_forecast(wz, r24, max(r72, r24), max(r7d, r72, r24), storm)
                    st.success(f"Saved. Drafts now out of date: {len(res['drafts_now_out_of_date'])}.")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))

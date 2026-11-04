"""Dashboard: in plain words, what should happen in each ward this week, where the pests are, and what is waiting
for the officer."""
from __future__ import annotations

import html
from datetime import date

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import api_client as api
import ui

MAIN_CROPS = {"Maize", "Beans", "Potato", "Kale"}
ACCENT = {"green": "#1F7A4D", "orange": "#D98E04", "red": "#C0392B", "gray": "#9AA79F"}
MONTHS = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
          "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}


def tag(text: str, color: str) -> str:
    return f'<span class="cp-tag t-{color}">{html.escape(text)}</span>'


def chips(items: list[str], cls: str = "") -> str:
    return "".join(f'<span class="cp-chip {cls}">{html.escape(i)}</span>' for i in items)


def do_this(z: dict) -> tuple[str, str, str]:
    """(action, colour, reason) for field work in a ward."""
    if z["washout_risk"]:
        return "Hold all field work", "red", f"Heavy rain: {z['rain_72h_mm']:.0f} mm in the next 3 days."
    if MAIN_CROPS <= set(z["plant_now"]) and z["pattern"].get("onset") == "FALSE_START_RISK":
        return ("Plant in two batches", "orange",
                f"{z['rain_7d_mm']:.0f} mm coming after a dry spell: plant half now, half after the next wet week.")
    if MAIN_CROPS <= set(z["plant_now"]):
        return "Plant now", "green", f"{z['rain_7d_mm']:.0f} mm of rain expected this week."
    if z["plant_now"]:
        return ("Dry-season crops only", "orange",
                f"Only {z['rain_7d_mm']:.0f} mm this week: too dry for maize and beans (they need about 25 mm).")
    return "Too dry to plant", "gray", f"Only {z['rain_7d_mm']:.0f} mm expected this week."


def rains_text(p: dict) -> str:
    rains = {"FALSE_START_RISK": "Rain after a dry spell (false-start risk)", "LATE": "Rains running late",
             "ONSET": "Rains have started", "NOT_YET": "Rains not started yet"}.get(p.get("onset"), "")
    recent = p.get("recent_pct_of_normal")
    return f"{rains}; last 20 days at {recent}% of normal" if recent is not None else rains


def ward_card(z: dict, pests: list[dict]) -> str:
    action, color, reason = do_this(z)
    p = z["pattern"]
    plantable = z["plant_now"] if MAIN_CROPS <= set(z["plant_now"]) else [c for c in z["plant_now"] if c not in MAIN_CROPS]
    pct = p.get("season_anomaly_pct")
    season = f"{pct:+d}%" if pct is not None else "—"
    spray_label, spray_color = ui.spray_status(z)
    names = sorted({a["pest"] for a in pests})
    pest_html = chips(names, "red") if names else chips(["No confirmed pests"], "ok")
    return (f'<div class="cp-ward" style="--accent:{ACCENT[color]}"><div class="wh">'
            f'<span class="wn">{html.escape(z["zone_id"].title())}</span>{tag(action, color)}</div>'
            f'<div class="why">{html.escape(reason)}</div>'
            f'<div class="cp-stats"><div class="cp-stat"><span>This week</span><b>{z["rain_7d_mm"]:.0f} mm</b></div>'
            f'<div class="cp-stat"><span>Next 3 days</span><b>{z["rain_72h_mm"]:.0f} mm</b></div>'
            f'<div class="cp-stat"><span>Season</span><b>{season}</b></div></div>'
            f'<div class="cp-row"><span class="lbl">Spraying</span>{tag(spray_label, spray_color)}</div>'
            f'<div class="cp-row"><span class="lbl">Can plant</span>'
            f'{chips(plantable) if plantable else chips(["Nothing this week"], "gray")}</div>'
            f'<div class="cp-row"><span class="lbl">Pests</span>{pest_html}</div>'
            f'<div class="cp-row" style="color:#66756B">{html.escape(rains_text(p))}</div></div>')


def period_label(period: str) -> str:
    """'2026-09 D1' -> 'Sep 1–10'."""
    try:
        ym, d = period.split()
        return f"{MONTHS[ym[5:7]]} {({'D1': '1–10', 'D2': '11–20', 'D3': '21–end'})[d]}"
    except (ValueError, KeyError):
        return period


ui.header("This week", "What to tell farmers in each ward, where the pests are, and what is waiting for you.")
try:
    ov, advs, scans, fups = api.overview(), api.advisories(), api.scans(), api.followups()
except api.ApiError as exc:
    st.error(str(exc.detail))
    st.stop()
today = date.fromisoformat(ov["today"])
active = [a for a in ov["alerts"] if a.get("active")]
by_zone: dict[str, list[dict]] = {}
for a in active:
    by_zone.setdefault(a["zone_id"], []).append(a)

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

# --- Ward by ward -------------------------------------------------------------------------------------------
st.subheader("Ward by ward")
st.markdown('<div class="cp-wgrid">' + "".join(ward_card(z, by_zone.get(z["zone_id"], [])) for z in ov["zones"])
            + "</div>", unsafe_allow_html=True)
st.caption("Pests: confirmed by an officer in the last 30 days. Planting: maize, beans and potato need about 25 mm of "
           "rain in a week; sorghum and cowpeas about 15 mm. Season: expected short-rains total against normal.")

# --- Pest map -----------------------------------------------------------------------------------------------
st.subheader("Pest map")
unconfirmed = [a for a in ov["alerts"] if not a["verified"] and a["lat"] is not None]
old = [a for a in ov["alerts"] if a["verified"] and not a.get("active") and a["lat"] is not None]
mc, lc = st.columns([2.3, 1], gap="large")
with lc:
    if active:
        st.markdown(f"**{len(active)} confirmed report{'s' if len(active) != 1 else ''} in the last 30 days**")
        for a in sorted(active, key=lambda x: (x["severity"] != "HIGH", x["age_days"] or 0)):
            sev = {"HIGH": "red", "MEDIUM": "orange", "LOW": "gray"}[a["severity"]]
            where = ("location approximate (ward only)" if a.get("placed_at") == "ward centre"
                     else f"acts within {a['action_radius_km']:.0f} km")
            st.markdown(f'<div class="cp-row">{tag(a["severity"].title(), sev)} <b>{html.escape(a["pest"])}</b>, '
                        f'{html.escape(a["zone_id"].title())}<br><span class="cp-muted">{a["age_days"]} days ago · '
                        f'{where} · {html.escape(a["source"] or "")}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="cp-callout">✅ <b>No confirmed pest reports in the last 30 days.</b><br>No farm has '
                    'a reason to spray right now. Keep scouting; a confirmed report will appear here and on the '
                    'map.</div>', unsafe_allow_html=True)
    if unconfirmed:
        st.markdown(f'<div class="cp-callout warn">{len(unconfirmed)} unconfirmed report'
                    f'{"s" if len(unconfirmed) != 1 else ""} (grey on the map), e.g. from WhatsApp groups. They are '
                    'not used for advice until an officer confirms them.</div>', unsafe_allow_html=True)
with mc:
    farms = [{"lat": h["lat"], "lon": h["lon"], "title": h["farmer_name"] or h["household_id"],
              "detail": f"{(h['crop'] or 'no crop')} · {ui.stage_label(h['stage']).lower()}"}
             for h in ov["households"] if h["lat"] is not None]
    def pest_point(a: dict) -> dict:
        approx = a.get("placed_at") == "ward centre"
        return {"lat": a["lat"], "lon": a["lon"], "r": a["action_radius_km"] * 1000, "title": a["pest"],
                "detail": f"Confirmed, {a['severity'].lower()} · {a['age_days']} days ago · "
                          + ("location approximate (ward only)" if approx else
                             f"farms within {a['action_radius_km']:.0f} km are at risk")}
    exact = [pest_point(a) for a in active if a["lat"] is not None and a.get("placed_at") != "ward centre"]
    approx = [pest_point(a) for a in active if a.get("placed_at") == "ward centre"]
    reach = exact
    grey = [{"lat": a["lat"], "lon": a["lon"], "title": f"{a['pest']} (unconfirmed)",
             "detail": f"{a['source']} · not used for advice"} for a in unconfirmed]
    stale = [{"lat": a["lat"], "lon": a["lon"], "title": f"{a['pest']} (older than 30 days)",
              "detail": "No longer triggers spraying"} for a in old]
    wards = [{"lat": z["lat"], "lon": z["lon"], "name": z["zone_id"].title()} for z in ov["zones"]]
    layers = [
        pdk.Layer("ScatterplotLayer", reach, get_position="[lon, lat]", get_radius="r", get_fill_color=[192, 57, 43, 10],
                  get_line_color=[192, 57, 43, 110], stroked=True, line_width_min_pixels=1, pickable=False),
        pdk.Layer("ScatterplotLayer", farms, get_position="[lon, lat]", get_radius=55, radius_min_pixels=5,
                  get_fill_color=[31, 122, 77, 230], get_line_color=[255, 255, 255], stroked=True,
                  line_width_min_pixels=1, pickable=True),
        pdk.Layer("ScatterplotLayer", stale, get_position="[lon, lat]", get_radius=90, radius_min_pixels=6,
                  get_fill_color=[240, 180, 170, 200], pickable=True),
        pdk.Layer("ScatterplotLayer", grey, get_position="[lon, lat]", get_radius=90, radius_min_pixels=6,
                  get_fill_color=[150, 160, 154, 220], pickable=True),
        pdk.Layer("ScatterplotLayer", reach, get_position="[lon, lat]", get_radius=110, radius_min_pixels=8,
                  get_fill_color=[192, 57, 43, 255], get_line_color=[255, 255, 255], stroked=True,
                  line_width_min_pixels=2, pickable=True),
        pdk.Layer("ScatterplotLayer", approx, get_position="[lon, lat]", get_radius=110, radius_min_pixels=8,
                  get_fill_color=[255, 255, 255, 255], get_line_color=[192, 57, 43, 255], stroked=True,
                  line_width_min_pixels=3, pickable=True),
        pdk.Layer("TextLayer", wards, get_position="[lon, lat]", get_text="name", get_size=13, get_color=[27, 42, 33],
                  get_pixel_offset=[0, -18], font_weight=700),
    ]
    view = pdk.ViewState(latitude=sum(w["lat"] for w in wards) / len(wards),
                         longitude=sum(w["lon"] for w in wards) / len(wards), zoom=11.8)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_style="light",
                             tooltip={"html": "<b>{title}</b><br/>{detail}"}), height=400)
    st.markdown('<div class="cp-legend"><span><i style="background:#1F7A4D"></i>Farm</span>'
                '<span><i style="background:#C0392B"></i>Confirmed pest (ring: action radius)</span>'
                '<span><i style="background:#fff;border:3px solid #C0392B;width:7px;height:7px"></i>'
                'Confirmed, location approximate</span>'
                '<span><i style="background:#96A09A"></i>Unconfirmed report</span>'
                '<span><i style="background:#F0B4AA"></i>Confirmed, older than 30 days</span></div>',
                unsafe_allow_html=True)

# --- Rainfall pattern ---------------------------------------------------------------------------------------
st.subheader("Rainfall pattern")
ward_ids = [z["zone_id"] for z in ov["zones"]]
ward = st.segmented_control("Ward", ward_ids, default=ward_ids[0], format_func=str.title, key="pattern_ward",
                            label_visibility="collapsed") or ward_ids[0]
zp = next(z for z in ov["zones"] if z["zone_id"] == ward)["pattern"]
stats = []
if zp.get("season_expected_mm"):
    stats += [("Season outlook", f"{zp['season_expected_mm']:.0f} mm"),
              ("Against normal", f"{zp['season_anomaly_pct']:+d}% (normal {zp.get('season_normal_mm', 0):.0f} mm)")]
if zp.get("recent_pct_of_normal") is not None:
    stats.append(("Last 20 days", f"{zp['recent_pct_of_normal']}% of normal"))
stats.append(("Rains", {"FALSE_START_RISK": "False-start risk", "LATE": "Running late", "ONSET": "Started",
                        "NOT_YET": "Not started"}.get(zp.get("onset"), "—")))
st.markdown('<div class="cp-stats" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:6px 0 4px">'
            + "".join(f'<div class="cp-stat"><span>{html.escape(k)}</span><b style="white-space:normal">'
                      f'{html.escape(v)}</b></div>' for k, v in stats) + "</div>", unsafe_allow_html=True)
if zp["dekads"]:
    rows = []
    for d in zp["dekads"]:
        rows += [{"Period": period_label(d["period"]), "order": d["period"], "Rain (mm)": d["rain_mm"],
                  "Series": "This year"},
                 {"Period": period_label(d["period"]), "order": d["period"], "Rain (mm)": d["normal_mm"],
                  "Series": "Normal"}]
    df = pd.DataFrame(rows)
    order = list(dict.fromkeys(df.sort_values("order")["Period"]))
    chart = alt.Chart(df).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
        x=alt.X("Period:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=12)),
        xOffset=alt.XOffset("Series:N", sort=["This year", "Normal"]),
        y=alt.Y("Rain (mm):Q", title="Rain (mm)"),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["This year", "Normal"], range=["#1F7A4D", "#C9D6CC"]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["Period", "Series", "Rain (mm)"])
    st.altair_chart(chart.properties(height=260), width="stretch")
    st.caption("Rain in each 10-day period (CHIRPS-style, synthetic) against the long-term average for that period.")
for line in zp.get("advice", []):
    st.markdown(f'<div class="cp-callout">{html.escape(line)}</div>', unsafe_allow_html=True)

# --- Follow-ups ---------------------------------------------------------------------------------------------
st.subheader("Desk follow-ups")
if not fups:
    st.caption("No follow-ups yet. The agent schedules one after every draft (re-scout, re-check after rain, "
               "field visit...).")
else:
    fl, fr = st.columns([2.2, 1], gap="large")
    fl.dataframe(pd.DataFrame([{"Due": f["due_date"], "Farm": ui.farm_label(f["household_id"]),
                                "What": f["kind"].replace("_", " ").title(), "Why": f["reason"]} for f in fups]),
                 hide_index=True, width="stretch", height=min(300, 38 + 35 * len(fups)))
    with fr.form("close-followup"):
        pick = st.selectbox("Mark as done", fups, format_func=lambda f: f"{f['due_date']} · {ui.farm_label(f['household_id'])} · "
                                                                        f"{f['kind'].replace('_', ' ').title()}")
        who = st.text_input("Your full name")
        if st.form_submit_button("Done", type="primary", width="stretch"):
            try:
                api.close_followup(pick["id"], who)
                st.rerun()
            except api.ApiError as exc:
                st.error(str(exc.detail))

# --- All numbers and a new forecast -------------------------------------------------------------------------
with st.expander("All rainfall numbers", icon=":material/table:"):
    st.dataframe(pd.DataFrame([{"Ward": z["zone_id"].title(), "Next 24 h (mm)": z["rain_24h_mm"],
                                "Next 3 days (mm)": z["rain_72h_mm"], "Next 7 days (mm)": z["rain_7d_mm"],
                                "Storm": z["storm_risk"].title(), "Wind (km/h)": z.get("wind_kmh"),
                                "Spraying": ui.spray_status(z)[0], "Spray score": z["spray_safety_index"],
                                "Season vs normal": f"{z['pattern'].get('season_anomaly_pct', 0):+d}%",
                                "Forecast issued": str(z["forecast_issued_at"])[:10]} for z in ov["zones"]]),
                 hide_index=True, width="stretch",
                 column_config={"Spray score": st.column_config.ProgressColumn("Spray score", min_value=0,
                                                                               max_value=100, format="%d")})
    st.caption("Synthetic CHIRPS-style forecast. A spray score below 40 means do not spray.")
with st.expander("A new forecast arrived? Record it", icon=":material/edit_note:"):
    with st.form("new-forecast"):
        st.markdown("Record it; drafts built on the old one are blocked until re-run.")
        f = st.columns(5)
        wz = f[0].selectbox("Ward", ward_ids, format_func=str.title)
        cur = next(z for z in ov["zones"] if z["zone_id"] == wz)
        r24 = f[1].number_input("24 h", 0.0, 500.0, float(cur["rain_24h_mm"]))
        r72 = f[2].number_input("3 days", 0.0, 800.0, float(cur["rain_72h_mm"]))
        r7d = f[3].number_input("7 days", 0.0, 1500.0, float(cur["rain_7d_mm"]))
        storm = f[4].selectbox("Storm", ["LOW", "MODERATE", "HIGH"],
                               index=["LOW", "MODERATE", "HIGH"].index(cur["storm_risk"]))
        if st.form_submit_button("Save forecast"):
            try:
                res = api.update_forecast(wz, r24, max(r72, r24), max(r7d, r72, r24), storm)
                st.success(f"Saved. Drafts now out of date: {len(res['drafts_now_out_of_date'])}.")
                st.rerun()
            except api.ApiError as exc:
                st.error(str(exc.detail))

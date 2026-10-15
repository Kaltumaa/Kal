"""Household page: one plot's history against its crop calendar, its ward's weather pattern and its advice."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import api_client as api
import ui

role, mine = st.session_state.get("role", "officer"), st.session_state.get("my_farm")
officer = role == "officer"
if officer:
    ui.header("Farms", "One farm at a time: its history, where it is in the crop calendar, and the advice it got.")
    top = st.columns([1.4, 3], vertical_alignment="bottom")
    hid = top[0].selectbox("Farm", list(ui.names()), format_func=ui.farm_label)
    if top[1].button("Draft new advice for this farm", icon=":material/edit_note:"):
        with st.spinner("Agent working… (1–3 min on CPU)"):
            try:
                res = api.run_agent(hid, "")
                st.toast(f"Draft ready: {res['advisory'].get('verdict') or 'no advice'}. Review it below.",
                         icon=":material/check:")
            except api.ApiError as exc:
                st.error(str(exc.detail))
else:
    hid = mine
    ui.header("My farm", f"{ui.farm_label(hid)}: where your crop is in its calendar, your area's rain, and advice "
                         "from your extension officer.")
p = api.household_profile(hid)
plot, rot, pat = p["plot"], p["rotation"], p.get("pattern") or {}
crop = plot.get("active_crop") or "No crop recorded"
days = plot.get("days_since_planting")
stage = ui.stage_label(plot.get("growth_stage"))

m = st.columns(4)
m[0].metric("Crop", crop)
m[1].metric("Ward", (plot.get("zone_id") or "—").title())
m[2].metric("Days since planting", days if days is not None else "—")
m[3].metric("Stage", "Not planted" if plot.get("growth_stage") == "PRE_PLANTING" else stage)
if plot.get("injection_detected"):
    st.error("This farm's notes contained instruction-like text and were removed. Verify the record in person.",
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

draft = next((a for a in p["advisories"] if a["status"] in ("PENDING_REVIEW", "SECURITY_LOCK", "NEEDS_DATA")), None)
if not officer:
    ov = api.overview()
    zone = plot.get("zone_id")
    z = next((x for x in ov["zones"] if x["zone_id"] == zone), None)
    st.subheader("Alerts for my farm")
    alerts = []
    if z and z["washout_risk"]:
        alerts.append(("error", f"Heavy rain coming ({z['rain_72h_mm']:.0f} mm in 3 days): hold field work."))
    elif z and z["spray_band"] == "UNSAFE":
        alerts.append(("error", "Rain soon: don't spray now; it would wash off."))
    elif z and z["spray_band"] == "CAUTION":
        alerts.append(("warning", "Spray only if no rain is expected for the next 6 hours."))
    if pat.get("onset") == "FALSE_START_RISK":
        alerts.append(("warning", "Rain is returning after a dry spell: plant in two batches."))
    elif pat.get("onset") == "LATE":
        alerts.append(("info", "The rains are running late in your area. Keep your land ready."))
    pests_here = sorted({a["pest"] for a in ov["alerts"] if a["verified"] and a["zone_id"] == zone})
    if pests_here:
        alerts.append(("warning", f"Confirmed in your area: {', '.join(pests_here)}. Check your crop this week."))
    if rot.get("risk") in ("ELEVATED", "HIGH"):
        alerts.append(("warning", rot.get("sms_tip") or rot.get("note")))
    for kind, text in alerts or [("success", "No alerts for your farm right now.")]:
        getattr(st, kind)(text)

    st.subheader("Rainfall numbers")
    st.dataframe(pd.DataFrame([{"Area": ("▶ " if x["zone_id"] == zone else "") + x["zone_id"].title(),
                                "Next 24 h (mm)": x["rain_24h_mm"], "Next 3 days (mm)": x["rain_72h_mm"],
                                "Next 7 days (mm)": x["rain_7d_mm"], "Storm": x["storm_risk"].title(),
                                "Spraying": {"SAFE": "OK", "CAUTION": "Careful", "UNSAFE": "Don't"}[x["spray_band"]],
                                "Spray score": x["spray_safety_index"]} for x in ov["zones"]]),
                 hide_index=True, width="stretch",
                 column_config={"Spray score": st.column_config.ProgressColumn("Spray score", min_value=0,
                                                                               max_value=100, format="%d")})
    if pat.get("dekads"):
        st.markdown(f"**Rainfall pattern in {(zone or '').title()}** (10-day periods, this year vs normal)")
        st.bar_chart(pd.DataFrame([{"Period": d["period"], "This year (mm)": d["rain_mm"],
                                    "Normal (mm)": d["normal_mm"]} for d in pat["dekads"]]).set_index("Period"),
                     stack=False, color=["#1F7A4D", "#C9D6CC"], height=220)
    st.caption("CHIRPS-style rainfall data (synthetic for this demo).")

    sent = [a for a in p["advisories"] if a["status"] == "APPROVED"]
    st.subheader("Advice from your extension officer")
    if not sent:
        st.caption("No advice yet. When your extension officer approves advice for your farm, it appears here and "
                   "is sent to you by SMS.")
    for a in sent:
        with st.container(border=True):
            st.markdown(ui.badges(a["verdict"], a["status"]) + f"  <span class='cp-muted'>signed by "
                        f"{a['officer_signature']} · {(a['reviewed_at'] or '')[:10]}</span>", unsafe_allow_html=True)
            st.write(a["farmer_message"])
    st.stop()
if draft:
    with st.container(border=True):
        st.markdown("### 🤖 AI Generated Advisory Draft (Review Required)")
        st.markdown(ui.badges(draft["verdict"], draft["status"]) + "  Nothing has been sent to the farmer.")
        st.write(draft["rationale"])
        st.caption("Based on: " + " · ".join(ui.source_label(x, ui.names()) for x in draft["sources"]))
        can_send = draft["status"] == "PENDING_REVIEW" and not draft.get("forecast_changed")
        if draft.get("forecast_changed"):
            st.warning(f"The rainfall forecast changed since this draft ({draft['forecast_changed']}). Draft new "
                       "advice above before sending.", icon=":material/update:")
        elif draft["status"] != "PENDING_REVIEW":
            st.warning("This draft cannot be sent (security lock or missing data). Review it in the Review queue.",
                       icon=":material/block:")
        editing = st.session_state.get(f"edit-{draft['id']}", False)
        msg = st.text_area("SMS to the farmer", draft["farmer_message"] or "", max_chars=320, height=90,
                           disabled=not (editing and can_send), key=f"msg-{draft['id']}")
        if can_send:
            citation = st.text_area("Citation (required: the records this advice rests on)",
                                    ui.suggested_citation(draft, api.farm_actions(hid)), height=70, max_chars=600,
                                    key=f"cite-{draft['id']}")
            c = st.columns([1.4, 1.6, 1.2])
            name = c[0].text_input("Your full name (signature)", key=f"sig-{draft['id']}",
                                   placeholder="e.g. Wanjiru Kamau")
            ok = c[1].checkbox("I have checked the evidence and take responsibility for this advice.",
                               key=f"ok-{draft['id']}")
            b = st.columns([2.2, 1.3, 1])
            if b[0].button("🚀 Send Local Advisory Notification to Farmer", type="primary", key=f"send-{draft['id']}",
                           width="stretch"):
                if not ok:
                    st.error("Tick the confirmation box first.")
                else:
                    try:
                        r = api.approve(draft["id"], name, msg, citation)
                        st.toast(f"Signed by {r['officer']}. SMS queued (simulated).", icon=":material/check:")
                        st.session_state.pop(f"edit-{draft['id']}", None)
                        st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
            if b[1].button("✏️ Edit Text Advisory Field" if not editing else "Lock text", key=f"editbtn-{draft['id']}",
                           width="stretch"):
                st.session_state[f"edit-{draft['id']}"] = not editing
                st.rerun()

st.subheader("Advice history")
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

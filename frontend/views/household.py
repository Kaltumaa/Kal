"""Household page: one plot's history against its crop calendar, its ward's weather pattern and its advice."""
from __future__ import annotations

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
slope, soil, companion = plot.get("slope"), plot.get("soil"), plot.get("intercrop")
terrain = (f"{slope.capitalize()} slope · {soil}" if slope and soil else
           "Slope and soil not recorded yet")
terrain += f" · grown with {companion.lower()}" if companion else ""
st.caption(f":material/landscape: **Terrain:** {terrain}. Planting advice uses it: how to plant on a slope, "
           "whether flat clay will waterlog, and a layout tip for intercropped plots.")
if officer:
    with st.expander("Record slope, soil and companion crop (from your field visit)",
                     icon=":material/edit_location_alt:"):
        opts = api.terrain_options()
        with st.form(f"terrain-{hid}"):
            c = st.columns(4, vertical_alignment="bottom")
            new_slope = c[0].selectbox("Slope", opts["slopes"], format_func=str.capitalize,
                                       index=opts["slopes"].index(slope) if slope in opts["slopes"] else 0)
            new_soil = c[1].selectbox("Soil", opts["soils"], format_func=str.capitalize,
                                      index=opts["soils"].index(soil) if soil in opts["soils"] else 0)
            companions = ["None"] + [x for x in opts["companions"] if x != plot.get("active_crop")]
            new_comp = c[2].selectbox("Grown with", companions,
                                      index=companions.index(companion) if companion in companions else 0)
            who = c[3].text_input("Your full name")
            if st.form_submit_button("Save terrain"):
                try:
                    api.set_terrain(hid, new_slope, new_soil, who, None if new_comp == "None" else new_comp)
                    st.toast("Terrain saved. Draft new advice to use it.", icon=":material/check:")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))
if officer:
    info = st.session_state.get("farm_info", {}).get(hid, {})
    cell_list = api.cells()
    cell_name = next((c["name"] for c in cell_list if c["cell_id"] == info.get("cell_id")), None)
    with st.expander(f"Phone and Nyumba Kumi cell · {(info.get('phone_type') or 'phone type not recorded').replace('feature', 'feature phone')}"
                     f" · {'number on file' if info.get('has_phone') else 'no number'} · {cell_name or 'no cell'}",
                     icon=":material/call:"):
        st.caption("Feature-phone farmers get signed advice and photo results by SMS and, if you choose, a voice call. "
                   "A cell's lead farmer can send photos for neighbours without a smartphone.")
        with st.form(f"contact-{hid}"):
            c = st.columns([1.3, 1, 1.2, 1.3], vertical_alignment="bottom")
            phone = c[0].text_input("Phone (leave empty to keep)", placeholder="0712 345 678")
            types = ["feature", "smartphone"]
            ptype = c[1].selectbox("Phone", types, index=types.index(info["phone_type"])
                                   if info.get("phone_type") in types else 0,
                                   format_func=lambda t: "Feature phone" if t == "feature" else "Smartphone")
            cell_ids = [""] + [c_["cell_id"] for c_ in cell_list]
            cell_pick = c[2].selectbox("Nyumba Kumi cell", cell_ids,
                                       index=cell_ids.index(info.get("cell_id") or ""),
                                       format_func=lambda x: next((c_["name"] for c_ in cell_list if c_["cell_id"] == x),
                                                                  "No cell"))
            who_c = c[3].text_input("Your full name", key=f"contact-who-{hid}")
            if st.form_submit_button("Save contact"):
                try:
                    api.set_contact(hid, who_c, phone.strip() or None, ptype, cell_pick)
                    st.toast("Contact saved.", icon=":material/check:")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))
if plot.get("injection_detected"):
    st.error("This farm's notes contained instruction-like text and were removed. Verify the record in person.",
             icon=":material/gpp_bad:")

crops_here = list((p.get("calendars") or {}))
st.caption(":material/calendar_month: Crop calendar"
           + (f" for {' and '.join(c.lower() for c in crops_here)}" if crops_here else "")
           + ": open **Crop calendar** in the menu to see each crop's stages and pest-watch days.")

left, right = st.columns(2, gap="large")
with left:
    with ui.section():
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
    with ui.section():
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
    elif z and z.get("wind_too_strong"):
        alerts.append(("warning", f"Windy ({z['wind_kmh']:.0f} km/h): don't spray today, it would drift onto "
                                  "neighbours' crops. Spray early in the morning when it is calm."))
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
                                "Wind (km/h)": x.get("wind_kmh"), "Spraying": ui.spray_status(x)[0],
                                "Spray score": x["spray_safety_index"]} for x in ov["zones"]]),
                 hide_index=True, width="stretch",
                 column_config={"Spray score": st.column_config.ProgressColumn("Spray score", min_value=0,
                                                                               max_value=100, format="%d")})
    if pat.get("dekads"):
        st.markdown(f"**Rainfall pattern in {(zone or '').title()}** (10-day periods, this year vs normal)")
        st.bar_chart(pd.DataFrame([{"Period": d["period"], "This year (mm)": d["rain_mm"],
                                    "Normal (mm)": d["normal_mm"]} for d in pat["dekads"]]).set_index("Period"),
                     stack=False, color=["#18181B", "#E4E4E7"], height=220)
    st.caption("CHIRPS-style rainfall data (synthetic for this demo).")

    sent = [a for a in p["advisories"] if a["status"] == "APPROVED"]
    st.subheader("Advice from your extension officer")
    if not sent:
        st.caption("No advice yet. When your extension officer approves advice for your farm, it appears here and "
                   "is sent to you by SMS.")
    for a in sent:
        with ui.section():
            st.markdown(ui.badges(a["verdict"], a["status"]) + f"  <span class='cp-muted'>signed by "
                        f"{a['officer_signature']} · {(a['reviewed_at'] or '')[:10]}</span>", unsafe_allow_html=True)
            langs = (a.get("sent_languages") or "en").split(",")
            if "en" in langs:
                st.write(a["farmer_message"])
            if "sw" in langs and a.get("farmer_message_sw"):
                st.markdown(f"**Kiswahili:** {a['farmer_message_sw']}")
    st.stop()
if draft:
    with ui.section():
        st.markdown("### AI-generated advisory draft (review required)")
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
        msg_sw = st.text_area("Ujumbe kwa Kiswahili", draft.get("farmer_message_sw") or "", max_chars=320, height=90,
                              disabled=not (editing and can_send), key=f"msgsw-{draft['id']}",
                              placeholder="No Swahili draft.")
        if can_send:
            citation = st.text_area("Citation (required: the records this advice rests on)",
                                    ui.suggested_citation(draft, api.farm_actions(hid)), height=70, max_chars=600,
                                    key=f"cite-{draft['id']}")
            want_en, want_sw, lang_note = ui.language_defaults(plot)
            lc = st.columns(2)
            send_en = lc[0].checkbox("Send in English", value=want_en, key=f"en-{draft['id']}")
            send_sw = lc[1].checkbox("Send in Kiswahili", value=want_sw, key=f"sw-{draft['id']}",
                                     help="Both languages are covered by the same signature.")
            st.caption(lang_note)
            c = st.columns([1.4, 1.6, 1.2])
            name = c[0].text_input("Your full name (signature)", key=f"sig-{draft['id']}",
                                   placeholder="e.g. Wanjiru Kamau")
            ok = c[1].checkbox("I have checked the evidence and take responsibility for this advice.",
                               key=f"ok-{draft['id']}")
            b = st.columns([2.2, 1.3, 1])
            if b[0].button("Send advice to farmer", type="primary", key=f"send-{draft['id']}",
                           width="stretch"):
                if not ok:
                    st.error("Tick the confirmation box first.")
                else:
                    try:
                        langs = [lang for lang, on in (("en", send_en), ("sw", send_sw)) if on]
                        r = api.approve(draft["id"], name, msg, citation, msg_sw, langs)
                        st.toast(f"Signed by {r['officer']}. SMS queued (simulated).", icon=":material/check:")
                        st.session_state.pop(f"edit-{draft['id']}", None)
                        st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
            if b[1].button("Edit text" if not editing else "Lock text", key=f"editbtn-{draft['id']}",
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

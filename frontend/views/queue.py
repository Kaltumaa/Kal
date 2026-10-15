"""Review queue: run the agent, then a named officer signs or rejects each draft (the human gate)."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

import api_client as api
import ui

SERVER_LABEL = {"crop-pilot": "Mkulima Hub MCP", "filesystem": "Filesystem MCP", "ollama": "Local model",
                "guard": "Guard (blocked)", "officer": "Officer", "graph": "Workflow", "none": "Blocked"}


def ward_summary() -> None:
    ward = st.session_state.get("last_ward")
    if not ward:
        return
    mins = ward["total_s"] / 60
    st.success(f"**{ward['zone_id'].title()}**: {ward['households']} households drafted in {mins:.1f} min "
               f"(by hand: cross-checking each plot takes most of a season). All drafts are waiting for your signature.",
               icon=":material/groups:")


@st.fragment
def detail(adv: dict) -> None:
    ev = adv.get("evidence") or {}
    plot, rain, threat = ev.get("plot") or {}, ev.get("rain") or {}, ev.get("pest_threat")
    can_sign = adv["status"] == "PENDING_REVIEW"

    with st.container(border=True):
        stage = ui.stage_label(plot.get("growth_stage")).lower() if plot.get("growth_stage") else ""
        st.markdown(f"### {ui.names().get(adv['household_id'], adv['household_id'])}")
        urg, urg_color = ui.urgency(adv["verdict"], plot.get("growth_stage"))
        st.markdown(f":{urg_color}-badge[{urg}] "
                    f":{ui.STATUS_COLOR.get(adv['status'], 'gray')}-badge[{ui.STATUS_TEXT.get(adv['status'], '')}]"
                    + f'  <span class="cp-muted">&nbsp;'
                    f'{(plot.get("zone_id") or "—").title()} · {plot.get("active_crop") or "no crop recorded"}'
                    f'{" · " + stage if stage else ""}</span>', unsafe_allow_html=True)

        if adv.get("forecast_changed"):
            st.warning(f"The rainfall forecast changed since this draft: {adv['forecast_changed']}. It cannot be "
                       "signed. Re-run the agent with the new forecast, then reject this one with your name.",
                       icon=":material/update:")
            if st.button("Re-run with the new forecast", key=f"rerun-{adv['id']}", type="primary"):
                with st.spinner("Re-drafting with the new forecast… (1–3 min on CPU)"):
                    try:
                        res = api.run_agent(adv["household_id"], "Re-run: rainfall forecast changed")
                        st.session_state["select_advisory"] = res["advisory"].get("advisory_id")
                        st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
        if adv["status"] == "SECURITY_LOCK":
            st.error("Instruction-like text was found in this household's record (possible prompt injection). "
                     "It never reached the model. This draft cannot be signed: check the record, then reject it.",
                     icon=":material/gpp_bad:")
        elif adv["status"] == "NEEDS_DATA":
            st.info("The household profile is missing a crop or ward, so the agent stopped instead of guessing. "
                    "Schedule a field visit.", icon=":material/help:")

        if rain.get("spray_safety_index") is not None and adv["status"] != "NEEDS_DATA":
            m = st.columns(4)
            m[0].metric("Spraying", {"SAFE": "OK", "CAUTION": "Careful", "UNSAFE": "Don't"}.get(rain.get("spray_band"), "—"),
                        f'score {rain["spray_safety_index"]:.0f}/100',
                        delta_color="off")
            m[1].metric("Rain, 7 days", f'{rain.get("rain_7d_mm") or 0:.0f} mm')
            m[2].metric("Planting window", (rain.get("planting_window") or "—").title())
            m[3].metric("Nearest pest", f'{threat["distance_km"]} km' if threat else "None",
                        threat["pest"] if threat else None, delta_color="off")

        view = st.segmented_control("View", ["Message & send", "Farm & plot history", "Evidence", "Agent steps"],
                                    default="Message & send", key=f"view-{adv['id']}", label_visibility="collapsed")
        if view == "Farm & plot history":
            prof = api.household_profile(adv["household_id"])
            rot, pat = prof["rotation"], prof.get("pattern") or {}
            seasons = (prof["plot"].get("crop_history") or []) + [f"{prof['plot'].get('active_crop') or '—'} (now)"]
            st.markdown("**Seasons:** " + " → ".join(seasons))
            st.markdown(f"**Rotation:** {(rot.get('risk') or 'unknown').title()} — {rot.get('note') or ''}")
            if pat.get("season_anomaly_pct") is not None:
                st.markdown(f"**Area rainfall:** season outlook {pat['season_expected_mm']:.0f} mm "
                            f"({pat['season_anomaly_pct']:+d}% vs normal); last 20 days at "
                            f"{pat.get('recent_pct_of_normal')}% of normal")
            log = api.farm_actions(adv["household_id"])
            if log:
                st.markdown("**Field log (latest)**")
                st.dataframe(pd.DataFrame([{"ID": a["id"], "Date": a["action_date"], "Action": a["action"].title(),
                                            "Details": a["details"] or "", "By": a["entered_by"]} for a in log[:5]]),
                             hide_index=True, width="stretch")
            else:
                st.caption("No field-log entries yet for this farm.")
        if view == "Message & send":
            st.write(adv["rationale"])
            if can_sign:
                with st.form(f"sign-{adv['id']}", border=False):
                    msg = st.text_area("Message to the farmer", adv["farmer_message"] or "", max_chars=320, height=90)
                    citation = st.text_area("Citation (required: the records this advice rests on)",
                                            ui.suggested_citation(adv, api.farm_actions(adv["household_id"])),
                                            height=80, max_chars=600)
                    name = st.text_input("Your full name", placeholder="e.g. Wanjiru Kamau")
                    ok = st.checkbox("I have checked the evidence and take responsibility for this advice.")
                    b = st.columns([2.2, 1, 1])
                    sign = b[0].form_submit_button("🚀 Send Local Advisory Notification to Farmer", type="primary",
                                                   width="stretch")
                    reject = b[1].form_submit_button("Reject", width="stretch")
                    try:
                        if sign:
                            if not ok:
                                st.error("Tick the confirmation box to send.")
                            else:
                                r = api.approve(adv["id"], name, msg, citation)
                                st.session_state["just_sent"] = (ui.names().get(adv["household_id"], adv["household_id"]),
                                                                  r["officer"])
                                st.rerun()
                        if reject:
                            api.reject(adv["id"], name, "")
                            st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
            else:
                with st.form(f"reject-{adv['id']}", border=False):
                    c = st.columns([2, 2, 1], vertical_alignment="bottom")
                    name = c[0].text_input("Your full name")
                    reason = c[1].text_input("Reason")
                    if c[2].form_submit_button("Reject", width="stretch"):
                        try:
                            api.reject(adv["id"], name, reason)
                            st.rerun()
                        except api.ApiError as exc:
                            st.error(str(exc.detail))
            planned = [f for f in api.followups() if f["run_id"] == adv["run_id"]]
            if planned:
                f = planned[0]
                st.caption(f":material/event: Follow-up scheduled by the agent for {f['due_date']}: {f['reason']}")
        if view == "Evidence":
            st.markdown("**Based on**")
            st.markdown("\n".join(f"- {ui.source_label(x, ui.names())}  <span class='cp-muted'>`{x}`</span>"
                                   for x in adv["sources"]), unsafe_allow_html=True)
            if plot.get("data_quality"):
                st.markdown("**Record repairs**")
                st.markdown("\n".join(f"- {q}" for q in plot["data_quality"]))
            if adv["flags"]:
                st.markdown("**Notes from the system**")
                st.markdown("\n".join(f"- {ui.flag_label(f)}" for f in dict.fromkeys(adv["flags"])))
                with st.expander("Raw flags"):
                    st.caption(" · ".join(adv["flags"]))
            if adv.get("model_verdict") and adv["model_verdict"] != adv["rule_verdict"]:
                st.warning(f"The local model suggested {adv['model_verdict']}; the safety rules chose "
                           f"{adv['rule_verdict']}.")
        if view == "Agent steps":
            try:
                rows = sorted(api.telemetry(adv["run_id"]), key=lambda r: r["id"])
            except api.ApiError:
                rows = []
            st.markdown("".join(
                f'<div class="cp-step"><span class="who">{SERVER_LABEL.get(r["server"], r["server"])}</span>'
                f'<code>{html.escape(r["tool"])}</code><span class="cp-muted">'
                f'{"✓" if r["status"] == "ok" else r["status"]}</span></div>'
                for r in rows) or "No steps logged.", unsafe_allow_html=True)


ui.header("Review queue", "The agent drafts. You decide. Nothing reaches a farmer without your typed name.")
try:
    if not api.health()["ok"]:
        st.error("The database failed its integrity check. Use **Sent messages → Manual backup form**.")
        st.stop()
    advs = api.advisories()
except api.ApiError as exc:
    st.error(str(exc.detail))
    st.stop()

drafts = [a for a in advs if a["status"] in ("SECURITY_LOCK", "PENDING_REVIEW", "NEEDS_DATA")]
# Drafts waiting for a signature first; locked drafts (can only be rejected) last.
drafts.sort(key=lambda a: ({"PENDING_REVIEW": 0, "NEEDS_DATA": 1}.get(a["status"], 2), -a["id"]))

PLAN = {"PLANT": "🌱 Plant now", "SPRAY": "🧴 Spray now", "HOLD": "✋ Hold", "HARVEST": "🧺 Ready for harvest",
        "NEEDS_DATA": "❔ Needs farm data", "SECURITY_LOCK": "⛔ Record locked"}
DRAFT = {None: "—", "PENDING_REVIEW": "Waiting for you", "SECURITY_LOCK": "Locked", "NEEDS_DATA": "Field visit",
         "APPROVED": "Sent", "REJECTED": "Rejected"}

# --- One toolbar to draft advice ---------------------------------------------------------------------------
with st.container(border=True):
    c = st.columns([1.1, 2, 1.2], vertical_alignment="bottom")
    scope = c[0].segmented_control("Draft for", ["One farm", "Whole ward"], default="One farm")
    if scope == "Whole ward":
        ward = c[1].selectbox("Ward", sorted({f["zone_id"] for f in st.session_state.get("farm_info", {}).values()
                                             if f["zone_id"]}), format_func=str.title)
        if c[2].button("Draft for the ward", type="primary", width="stretch"):
            with st.spinner("Drafting for every farm in the ward… (1–3 min each on CPU)"):
                try:
                    st.session_state["last_ward"] = api.run_ward(ward)
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))
    else:
        hid = c[1].selectbox("Farm", list(ui.names()), format_func=ui.farm_label)
        if c[2].button("Draft advice", type="primary", width="stretch"):
            with st.spinner("Gathering plot, rainfall and pest evidence… (1–3 min on CPU)"):
                try:
                    res = api.run_agent(hid, "")
                    st.session_state["select_advisory"] = res["advisory"].get("advisory_id")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))
ward_summary()

sent = st.session_state.pop("just_sent", None)
if sent:
    st.toast(f"Sent to {sent[0]}, signed by {sent[1]}.", icon=":material/check_circle:")
    st.success(f"Sent to **{sent[0]}**, signed by **{sent[1]}**. It is in **Sent messages** and the farmer's "
               "Notifications.", icon=":material/check_circle:")
views = [f"Drafts to review ({len(drafts)})", "Every farm this week"]
default_view = views[0] if drafts else views[1]
picked = st.segmented_control("Show", views, default=default_view, label_visibility="collapsed")

if picked == views[1]:
    plan = api.farms_plan()

    def plain(text: str) -> str:
        for code, words in ui.STAGES.items():
            text = text.replace(code, words.lower())
        return text

    st.dataframe(pd.DataFrame([{
        "Farm": f"{f['farmer_name']} · {(f['zone_id'] or '—').title()}",
        "Do now": PLAN.get(f["plan"], f["plan"]),
        "Draft": DRAFT.get(f["draft_status"], f["draft_status"]),
        "Crop": f"{f['crop'] or '—'}, {ui.stage_label(f['stage']).lower()}"
                + (f", day {f['days']}" if f["days"] is not None else ""),
        "Why": plain(f["why"]), "Tip": f["notes"][0] if f["notes"] else ""} for f in plan]),
        hide_index=True, width="stretch", height=38 + 35 * len(plan),
        column_config={"Why": st.column_config.TextColumn(width="large"),
                       "Tip": st.column_config.TextColumn(width="medium")})
    st.caption("A preview from the safety rules using each farm's plot history, crop stage, area rainfall and confirmed "
               "pests. Nothing goes to a farmer until the agent drafts it and you sign. Use the toolbar above to draft.")
else:
    if not drafts:
        st.info("No drafts waiting. Pick a farm or ward in the toolbar above and draft advice.",
                icon=":material/inbox:")
        st.stop()
    left, right = st.columns([1.3, 2.2], gap="large")
    with left:
        table = pd.DataFrame([{"Farm": ui.names().get(a["household_id"], a["household_id"]),
                               "Do now": PLAN.get(a["verdict"] or a["status"], "—"),
                               "Status": "Forecast changed" if a.get("forecast_changed")
                               else ui.STATUS_TEXT[a["status"]]} for a in drafts])
        wanted = st.session_state.pop("select_advisory", None)
        default_row = next((i for i, a in enumerate(drafts) if a["id"] == wanted), 0)
        sel = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                           key="drafts", height=min(420, 38 + 35 * len(drafts)))
        rows = sel.selection.rows if sel and sel.selection else []
        chosen = drafts[rows[0]] if rows else drafts[default_row]
        st.caption(f"{len(drafts)} waiting · select a row")
    with right:
        detail(chosen)

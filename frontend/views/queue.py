"""Review queue: run the agent, then a named officer signs or rejects each draft (the human gate)."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

import api_client as api
import ui

SERVER_LABEL = {"crop-pilot": "Crop-Pilot MCP", "filesystem": "Filesystem MCP", "ollama": "Local model",
                "guard": "Guard (blocked)", "officer": "Officer", "graph": "Workflow", "none": "Blocked"}


def new_draft() -> None:
    with st.popover("New draft", icon=":material/add:", type="primary", width="stretch"):
        hid = st.selectbox("Household", api.households())
        note = st.text_input("Note for the agent (optional)", max_chars=300)
        if st.button("Run agent", type="primary", width="stretch"):
            with st.spinner("Gathering plot, rainfall and pest evidence… (1–3 min on CPU)"):
                try:
                    res = api.run_agent(hid, note)
                    st.session_state["select_advisory"] = res["advisory"].get("advisory_id")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))


def detail(adv: dict) -> None:
    ev = adv.get("evidence") or {}
    plot, rain, threat = ev.get("plot") or {}, ev.get("rain") or {}, ev.get("pest_threat")
    can_sign = adv["status"] == "PENDING_REVIEW"

    with st.container(border=True):
        stage = (plot.get("growth_stage") or "").replace("_", " ").lower()
        st.markdown(f"### {adv['household_id']}")
        st.markdown(ui.badges(adv["verdict"], adv["status"]) + f'  <span class="cp-muted">&nbsp;'
                    f'{(plot.get("zone_id") or "—").title()} · {plot.get("active_crop") or "no crop recorded"}'
                    f'{" · " + stage if stage else ""}</span>', unsafe_allow_html=True)

        if adv["status"] == "SECURITY_LOCK":
            st.error("Instruction-like text was found in this household's record (possible prompt injection). "
                     "It never reached the model. This draft cannot be signed: check the record, then reject it.",
                     icon=":material/gpp_bad:")
        elif adv["status"] == "NEEDS_DATA":
            st.info("The household profile is missing a crop or ward, so the agent stopped instead of guessing. "
                    "Schedule a field visit.", icon=":material/help:")

        if rain.get("spray_safety_index") is not None and adv["status"] != "NEEDS_DATA":
            m = st.columns(4)
            m[0].metric("Spray safety", f'{rain["spray_safety_index"]:.0f}', rain.get("spray_band", "").title(),
                        delta_color="off")
            m[1].metric("Rain, 7 days", f'{rain.get("rain_7d_mm") or 0:.0f} mm')
            m[2].metric("Planting window", (rain.get("planting_window") or "—").title())
            m[3].metric("Nearest pest", f'{threat["distance_km"]} km' if threat else "None",
                        threat["pest"] if threat else None, delta_color="off")

        t_msg, t_ev, t_trace = st.tabs(["Message & signature", "Evidence", "Agent steps"])
        with t_msg:
            st.write(adv["rationale"])
            if can_sign:
                with st.form(f"sign-{adv['id']}", border=False):
                    msg = st.text_area("Message to the farmer", adv["farmer_message"] or "", max_chars=320, height=90)
                    name = st.text_input("Your full name", placeholder="e.g. Wanjiru Kamau")
                    ok = st.checkbox("I have checked the evidence and take responsibility for this advice.")
                    b = st.columns([1, 1, 2])
                    sign = b[0].form_submit_button("Sign & send", type="primary", width="stretch")
                    reject = b[1].form_submit_button("Reject", width="stretch")
                    try:
                        if sign:
                            if not ok:
                                st.error("Tick the confirmation box to sign.")
                            else:
                                r = api.approve(adv["id"], name, msg)
                                st.toast(f"Signed by {r['officer']}. Message queued.", icon=":material/check:")
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
        with t_ev:
            st.markdown("**Sources**")
            st.markdown("\n".join(f"- `{s}`" for s in adv["sources"]))
            if plot.get("data_quality"):
                st.markdown("**Record repairs**")
                st.markdown("\n".join(f"- {q}" for q in plot["data_quality"]))
            if adv["flags"]:
                st.markdown("**Flags**")
                st.caption(" · ".join(adv["flags"]))
            if adv.get("model_verdict") and adv["model_verdict"] != adv["rule_verdict"]:
                st.warning(f"The local model suggested {adv['model_verdict']}; the safety rules chose "
                           f"{adv['rule_verdict']}.")
        with t_trace:
            try:
                rows = sorted(api.telemetry(adv["run_id"]), key=lambda r: r["id"])
            except api.ApiError:
                rows = []
            st.markdown("".join(
                f'<div class="cp-step"><span class="who">{SERVER_LABEL.get(r["server"], r["server"])}</span>'
                f'<code>{html.escape(r["tool"])}</code><span class="cp-muted">'
                f'{"" if r["status"] == "ok" else r["status"] + " · "}{r["latency_ms"] or 0:.0f} ms</span></div>'
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
drafts.sort(key=lambda a: ({"SECURITY_LOCK": 0, "PENDING_REVIEW": 1}.get(a["status"], 2), -a["id"]))

left, right = st.columns([1, 2], gap="large")
with left:
    new_draft()
    if not drafts:
        st.caption("No drafts waiting.")
        st.stop()
    table = pd.DataFrame([{"Household": a["household_id"], "Advice": a["verdict"] or "—",
                           "Status": ui.STATUS_TEXT[a["status"]]} for a in drafts])
    wanted = st.session_state.pop("select_advisory", None)
    default_row = next((i for i, a in enumerate(drafts) if a["id"] == wanted), 0)
    sel = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                       key="drafts", height=min(420, 38 + 35 * len(drafts)))
    rows = sel.selection.rows if sel and sel.selection else []
    chosen = drafts[rows[0]] if rows else drafts[default_row]
    st.caption(f"{len(drafts)} waiting · select a row to review")
with right:
    detail(chosen)

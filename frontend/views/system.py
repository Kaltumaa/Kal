"""Activity log (readable audit trail) and Sent messages (with the manual backup form)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import ui


STEP_TEXT = {
    "planner": "Planned the steps", "get_plot_context": "Read and cleaned the farm record",
    "get_rainfall_outlook": "Checked the rain forecast", "get_pest_reports": "Checked confirmed pest reports",
    "get_weather_pattern": "Checked the season's rainfall pattern", "read_text_file": "Read a guidance document",
    "read_file": "Read a guidance document", "list_directory": "Looked through the guidance library",
    "draft_advisory": "Saved the draft for review", "schedule_followup": "Booked a follow-up for the officer",
    "self_check": "Self-checked the draft", "approve_and_dispatch": "Officer signed; SMS queued",
    "reject": "Officer rejected the draft", "execution_complete": "Run closed", "close_followup": "Follow-up done",
    "review_field_scan": "Officer reviewed a farmer photo", "log_plot_action": "Plot history entry added",
    "update_forecast": "New rain forecast recorded", "ward_batch": "Drafted a whole ward",
    "place_call": "Phoned the farmer", "call_event": "Call answered or ended", "keypad": "Farmer pressed a key",
    "agronomist.chat": "DeepLeaf read a photo (second opinion)", "lead_photo_for_neighbour":
    "Lead farmer sent a neighbour's photo", "set_contact": "Phone / cell recorded",
}
WHO_TEXT = {"crop-pilot": "Mkulima Hub tools (MCP)", "filesystem": "Guidance library (MCP)", "ollama": "Local AI",
            "guard": "Safety guard", "graph": "Workflow", "officer": "Officer", "farmer": "Farmer", "feed": "Data feed",
            "none": "Safety guard", "voice": "Phone call (Africa's Talking)", "deepleaf": "DeepLeaf (cloud)"}


def _step(tool: str) -> str:
    if tool.startswith("chat:"):
        return "AI " + ("chose the next step" if "gatherer" in tool else "wrote the explanation and SMS")
    if tool.startswith("vision:"):
        return "Local AI described a plant photo"
    return STEP_TEXT.get(tool, tool.replace("_", " "))


def activity_log() -> None:
    ui.header("Activity log", "Every step the agent took and every decision a person made, with who approved it.")
    try:
        rows = api.telemetry()
    except api.ApiError as exc:
        st.warning(f"Unavailable: {exc.detail}")
        return
    if not rows:
        st.caption("Nothing logged yet. Run the agent from the Review queue.")
        return
    df = pd.DataFrame(rows)
    names = ui.names()
    runs = {}
    for r in rows:
        if r["run_id"].startswith("run-") and r["run_id"] not in runs:
            hid = next((x["inputs_json"] for x in rows if x["run_id"] == r["run_id"] and x["tool"] == "planner"), "")
            farm = next((h for h in names if h in (hid or "")), None)
            runs[r["run_id"]] = f"{names.get(farm, 'Farm')} · {r['ts'][5:16].replace('T', ' ')}"
    pick = st.selectbox("Show", ["Everything"] + list(runs), format_func=lambda k: k if k == "Everything" else runs[k])
    if pick != "Everything":
        df = df[df["run_id"] == pick]
    m = st.columns(4)
    m[0].metric("Steps logged", len(df))
    m[1].metric("Tool calls (MCP)", int(df["server"].isin(["crop-pilot", "filesystem"]).sum()))
    m[2].metric("Blocked by safety guard", int((df["status"] == "blocked").sum()))
    m[3].metric("Signed by an officer", int(df["approved_by"].notna().sum()))
    view = pd.DataFrame({
        "Time": df["ts"].str[11:19], "What happened": df["tool"].map(_step), "Done by": df["server"].map(WHO_TEXT)
        .fillna(df["server"]), "Tool": df["tool"], "Result": df["status"].map({"ok": "✓ ok", "blocked": "⛔ blocked",
                                                                                  "error": "⚠ problem"}),
        "Person": df["actor"].where(df["actor"] != "agent", ""), "Approved by": df["approved_by"].fillna("")})
    st.dataframe(view, hide_index=True, width="stretch", height=440)
    with st.expander("Technical details (inputs, outputs, timing, tokens)"):
        st.dataframe(df[["id", "ts", "run_id", "server", "tool", "actor", "status", "latency_ms", "token_estimate",
                         "approved_by", "call_hash", "inputs_json", "output_json"]], hide_index=True, width="stretch",
                     height=360)


def outbox() -> None:
    ui.header("Sent messages", "Officer-signed messages (simulated SMS), and the backup form for when the database is down.")
    degraded = not api.health()["ok"]
    t_sent, t_backup = st.tabs(["Sent", "Manual backup form"])
    with t_sent:
        if degraded:
            st.warning("Unavailable while the database is degraded. Use the manual backup form.")
        else:
            out = api.outbox()
            if not out:
                st.caption("No messages sent yet.")
            for o in out:
                with st.container(border=True):
                    lang = {"sw": "Kiswahili"}.get(o.get("language"), "English")
                    st.markdown(f"**{ui.farm_label(o['household_id'])}** <span class='cp-muted'>· signed by {o['officer_signature']}"
                                f" · {o['queued_at'][:16].replace('T', ' ')} UTC · {lang} · SMS"
                                + (f", {o['sms_parts']} part{'s' if o['sms_parts'] != 1 else ''}" if o.get("sms_parts")
                                   else "") + "</span>", unsafe_allow_html=True)
                    st.write(o["message"])
            other = api.sms_messages()
            if other:
                st.markdown("##### Other SMS (photo results, confirmed reports, farmers' SMS commands)")
                for m in other[:40]:
                    arrow = "← from" if m["direction"] == "IN" else "→ to"
                    st.markdown(f"<span class='cp-muted'>{m['created_at'][:16].replace('T', ' ')} UTC · {arrow} "
                                f"{ui.farm_label(m['household_id'])} · {m['kind'].replace('_', ' ')}"
                                + (f" · signed by {m['sent_by']}" if m.get("sent_by") not in (None, "system") else "")
                                + f" · {m.get('sms_parts') or 1} SMS part(s)</span>  \n{m['body']}",
                                unsafe_allow_html=True)
    with t_backup:
        if degraded:
            st.error("Database failed its integrity check. Record decisions here; they sync later.")
        with st.form("manual"):
            c = st.columns(3)
            name = c[0].text_input("Your full name")
            hid = c[1].text_input("Household ID")
            verdict = c[2].selectbox("Decision", ["HOLD", "PLANT", "SPRAY"])
            note = st.text_area("Field note", max_chars=500, height=80)
            if st.form_submit_button("Save", type="primary"):
                try:
                    st.success(f"Saved ({api.manual_fallback(name, hid, verdict, note)['status']}).")
                except api.ApiError as exc:
                    st.error(str(exc.detail))
        manual = api.manual_fallback_list()
        if manual:
            st.dataframe(pd.DataFrame(manual), hide_index=True, width="stretch")


CALL_BADGE = {"QUEUED": ":gray-badge[Queued]", "SENT": ":blue-badge[Ringing]", "ANSWERED": ":blue-badge[Answered, no key]",
              "ACKNOWLEDGED": ":green-badge[Heard it (1)]",
              "VISIT_REQUESTED": ":orange-badge[Needs help (2)]",
              "NO_ANSWER": ":red-badge[No answer]", "FAILED": ":red-badge[Call failed]"}


def _spoken(xml: str) -> str:
    import re
    xml = xml.split("</GetDigits>")[0]          # the line after the menu only plays if no key is pressed
    return " ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", xml)) or "(call ended)"


def phone_calls() -> None:
    ui.header("Phone calls", "Signed advice and photo results read out to farmers on feature phones. The farmer "
                             "presses 1 if they understood, 2 if they need help from their Nyumba Kumi lead farmer, "
                             "0 to hear it again.")
    v = api.integrations()["voice"]
    if v["channel"] == "SIMULATED" and v.get("auto_simulate"):
        st.info("**Simulated phone company.** No telecom account is used: a built-in simulator answers each call after "
                "2 seconds, presses a key after 5 (" + {"random": "usually 1, sometimes 2", "none": "no key"}.get(
                    v.get("sim_digit"), f"key {v.get('sim_digit')}") + "), and hangs up, posting to the same "
                "webhook Africa's Talking would. Keys, times and costs below are simulated, not real farmers.",
                icon=":material/science:")
        if st.button("Refresh", icon=":material/refresh:"):
            st.rerun()
    elif v["channel"] == "SIMULATED":
        st.info("**Simulated calls.** No Africa's Talking keys are set, so no phone rings. Use the buttons to play the "
                "farmer's phone: they run the same code a real call does. Missing: " + ", ".join(v["missing"]) + ".",
                icon=":material/science:")
    else:
        st.success("Calls go out through **Africa's Talking**.", icon=":material/call:")
    calls = api.voice_calls()
    if not calls:
        st.caption("No calls yet. Tick 'Also phone the farmer' when you sign advice or verify a photo.")
        return
    counts = {k: sum(c["status"] == k for c in calls) for k in ("ACKNOWLEDGED", "VISIT_REQUESTED", "NO_ANSWER")}
    m = st.columns(4)
    m[0].metric("Calls", len(calls))
    m[1].metric("Heard it", counts["ACKNOWLEDGED"])
    m[2].metric("Needs help (2)", counts["VISIT_REQUESTED"])
    m[3].metric("No answer", counts["NO_ANSWER"])
    heard = st.session_state.pop("call_heard", None)
    for c in calls:
        with st.container(border=True):
            top = st.columns([3, 1.2], vertical_alignment="center")
            lang = "Kiswahili" if c["language"] == "sw" else "English"
            what = "Signed advice" if c["kind"] == "advice" else f"Photo #{c['related_id']} result"
            top[0].markdown(f"**{ui.farm_label(c['household_id'])}** · {what} · {lang} "
                            f"<span class='cp-muted'>· signed by {c['officer']} · {c['created_at'][:16].replace('T', ' ')}"
                            f" UTC · {'simulated' if c['channel'] == 'SIMULATED' else 'Africa’s Talking'}</span>",
                            unsafe_allow_html=True)
            top[1].markdown(CALL_BADGE.get(c["status"], c["status"]))
            st.markdown(f"> {c['script']}")
            if c.get("ended_at"):
                cost = f" · {c['amount']:.2f} {c.get('currency') or ''}" if c.get("amount") is not None else ""
                sim = " (simulated)" if c["channel"] == "SIMULATED" else ""
                st.caption(f"Call ended{sim}: {int(c['duration_seconds'] or 0)} s{cost} · keys pressed: "
                           f"{c.get('digits') or 'none'} · {c.get('hangup_cause') or ''}")
            if c.get("error") and c["status"] in ("FAILED", "NO_ANSWER"):
                st.caption(f"Problem: {c['error']}")
            if heard and heard[0] == c["id"]:
                st.caption("The farmer heard: " + " … ".join(_spoken(x) for x in heard[1]))
            b = st.columns(5)
            if c["channel"] == "SIMULATED" and c["status"] in ("SENT", "ANSWERED") and not v.get("auto_simulate"):
                for col, (label, answer, digit) in zip(b, [("Answer · press 1", True, "1"),
                                                           ("Answer · press 2", True, "2"),
                                                           ("Answer · press 0", True, "0"),
                                                           ("No answer", False, None)]):
                    if col.button(label, key=f"sim-{c['id']}-{label}", width="stretch"):
                        try:
                            r = api.simulate_call(c["id"], answer, digit)
                            st.session_state["call_heard"] = (c["id"], r["xml"])
                            st.rerun()
                        except api.ApiError as exc:
                            st.error(str(exc.detail))
            if c["status"] in ("NO_ANSWER", "FAILED"):
                if b[0].button("Call again", key=f"retry-{c['id']}", icon=":material/call:", width="stretch"):
                    try:
                        api.retry_call(c["id"])
                        st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
            if c["status"] == "VISIT_REQUESTED":
                st.caption("The cell's lead farmer was alerted on their Nyumba Kumi page and by SMS, and a follow-up "
                           "was added to your Dashboard.")

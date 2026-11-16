"""AI assurance: how the agent is kept safe, honest and supervised, with live numbers from the audit trail."""
from __future__ import annotations

import streamlit as st

import api_client as api
import auth
import ui

auth.require("extension_officer", "institution")
ui.header("AI assurance", "How TALO's AI is kept safe, honest and supervised, counted from what actually happened.")
try:
    a = api.assurance()
except api.ApiError as exc:
    st.error(str(exc.detail))
    st.stop()

hg, hon, mv = a["human_gate"], a["honesty"], a["model_vs_rules"]
c = st.columns(4)
c[0].metric("Advice drafts", a["drafts"], help="Every draft the agent has written")
c[1].metric("Sent after an officer signed", f"{hg['sent_with_named_officer']} / {hg['sent']}",
            help="Nothing reaches a farmer without a named officer; the database refuses it")
c[2].metric("Said it was unsure", hon["admitted_uncertainty"] + hon["missing_data_halts"],
            help="Escalated to an officer or halted for missing data instead of guessing")
c[3].metric("Recovered from failures", a["recoveries"]["total"], help="Retries, failovers and fallbacks logged")
if not a["drafts"]:
    st.info("No advice has been drafted on this database yet. Draft advice from the Review queue and these numbers "
            "fill in.", icon=":material/info:")

tk = a["tokens"]
with ui.section():
    st.subheader("Tokens per answer (from the logs)")
    t = st.columns(4)
    t[0].metric("Model", tk["model"], help="Runs locally in Ollama: no per-token bill")
    t[1].metric("Tokens per answer", f"{tk['avg_tokens']:,}", delta=f"max {tk['max_tokens']:,}", delta_color="off",
                help="Prompt + completion tokens reported by Ollama, summed per agent run")
    t[2].metric("Model calls per answer", tk["avg_model_calls"], delta=f"max {tk['max_model_calls']}",
                delta_color="off")
    t[3].metric("Tool calls per answer", tk["avg_tool_calls"], help="MCP calls: ours and the filesystem server")
    st.caption(f"{tk['runs_with_model']} of {tk['runs']} runs used the model (the rest ran on the fixed rules). "
               "Every call is in the Activity log" + (f"; latest run {tk['latest']}." if tk["latest"] else "."))

left, right = st.columns(2)
with left:
    with ui.section():
        st.subheader("Human in charge")
        st.markdown(f"""
- **{hg['sent_with_named_officer']}** sent, each signed by a named officer citing the draft's own records
- **{hg['rejected_by_officer']}** rejected by an officer; **{hg['waiting_for_officer']}** waiting
- The agent has **no tool that can send**; only an officer's signature releases a message
""")
    with ui.section():
        st.subheader("Honest about what it does not know")
        st.markdown(f"""
- **{hon['admitted_uncertainty']}** drafts where it said *"I may be wrong"* and asked an officer
  (blurry photo, unsure leaf scan, forecasts disagreeing, a past officer correction)
- **{hon['missing_data_halts']}** farms where it stopped because data was missing
- **{hon['learned_from_officer_feedback']}** drafts that took an officer's earlier rejection into account
- Escalations: **{hon['escalations_open']}** open, **{hon['escalations_resolved']}** resolved by an officer
""")
with right:
    with ui.section():
        st.subheader("Checks itself")
        sc = a["self_check"]
        st.markdown(f"""
- Self-check outcomes: **{sc.get('pass', 0)}** passed, **{sc.get('retry', 0)}** retried with fresh evidence,
  **{sc.get('escalate', 0)}** escalated, **{sc.get('downgrade', 0)}** withheld
- AI model vs safety rules: the model agreed **{mv['agreed']}** of **{mv['model_gave_verdict']}** times; the rules
  overruled it **{mv['overruled_by_rules']}** times, and each draft says so
- Every draft cites its sources (**{a['citations']['avg_sources']}** on average); the database rejects a draft with none
""")
    with ui.section():
        st.subheader("Secure by design")
        sec = a["security"]
        st.markdown(f"""
- **{sec['prompt_injection_caught']}** prompt-injection attempts caught; **{sec['locked_records']}** records locked
- The AI model runs **on this computer** (Ollama): farmer data is not sent to a cloud AI
- Photos sent for a second opinion are stripped of GPS, with a hashed farmer id
""")
if a["recent_uncertain"]:
    with ui.section():
        st.subheader("Latest times it asked for help")
        for d in a["recent_uncertain"]:
            st.markdown(f"<span class='cp-muted'>#{d['id']} · {ui.farm_label(d['household_id'])} · "
                        f"{d['created_at'][:16].replace('T', ' ')}</span>  \n{d['why']}…", unsafe_allow_html=True)
st.caption("Counted live from the audit tables (pending_advisories, escalations, recovery_log, tool_calls). "
           "Offline evaluation: EVALS.md.")
ui.partners()

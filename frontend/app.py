"""Crop-Pilot Control Desk (Streamlit). Talks to the backend ONLY over HTTP via api_client.

Run:  streamlit run frontend/app.py
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

import api_client as api

st.set_page_config(page_title="Crop-Pilot Control Desk", page_icon="🌱", layout="wide")

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1280px;}
.cp-hero {background: linear-gradient(120deg, #14532D 0%, #1F7A4D 55%, #3E9B5F 100%); color: #fff;
  border-radius: 16px; padding: 22px 26px; margin-bottom: 14px;}
.cp-hero h1 {color: #fff; font-size: 1.75rem; margin: 0 0 4px 0; padding: 0;}
.cp-hero p {color: #E3F1E7; margin: 0; font-size: .95rem;}
.cp-pill {display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;
  margin: 8px 6px 0 0; background: rgba(255,255,255,.16); color: #fff; border: 1px solid rgba(255,255,255,.28);}
.cp-status {display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 6px 0;}
.cp-chip {background: #fff; border: 1px solid #DDE5DA; border-radius: 10px; padding: 8px 12px; font-size: .85rem;}
.cp-chip b {display: block; font-size: .7rem; color: #5B6B60; text-transform: uppercase; letter-spacing: .04em;}
.cp-dot {display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px;}
.ok {background: #22A06B;} .warn {background: #E2A100;} .bad {background: #D64545;}
.cp-card {background: #fff; border: 1px solid #DDE5DA; border-radius: 14px; padding: 16px 18px; margin-bottom: 10px;}
.cp-card.lock {border: 2px solid #D64545; background: #FFF7F7;}
.cp-head {display: flex; align-items: center; gap: 12px; flex-wrap: wrap;}
.cp-verdict {font-weight: 800; font-size: 1.05rem; padding: 6px 14px; border-radius: 10px; letter-spacing: .03em;}
.v-PLANT {background: #DCF5E5; color: #14632F;} .v-SPRAY {background: #FFF1D6; color: #8A5300;}
.v-HOLD {background: #E3EBF7; color: #1E4C8F;} .v-NONE {background: #EEE; color: #555;}
.cp-status-pill {font-size: .72rem; font-weight: 700; padding: 3px 9px; border-radius: 999px; border: 1px solid;}
.s-PENDING_REVIEW {color: #8A5300; border-color: #E9C46A; background: #FFF8E6;}
.s-SECURITY_LOCK {color: #fff; border-color: #D64545; background: #D64545;}
.s-NEEDS_DATA {color: #555; border-color: #BBB; background: #F3F3F3;}
.s-APPROVED {color: #14632F; border-color: #7CCB97; background: #E8F7EE;}
.s-REJECTED {color: #444; border-color: #999; background: #EEE;}
.cp-meta {color: #5B6B60; font-size: .88rem;}
.cp-grid {display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 12px 0 4px 0;}
.cp-kv {background: #F7FAF6; border: 1px solid #E5ECE2; border-radius: 10px; padding: 8px 10px;}
.cp-kv b {display: block; font-size: .68rem; color: #5B6B60; text-transform: uppercase; letter-spacing: .04em;}
.cp-kv span {font-size: 1.02rem; font-weight: 700; color: #1B2A21;}
.cp-src {display: inline-block; font-family: ui-monospace, Menlo, monospace; font-size: .76rem; background: #EEF4EC;
  border: 1px solid #D5E2D1; border-radius: 6px; padding: 2px 7px; margin: 2px 4px 2px 0; color: #24452F;}
.cp-flag {display: inline-block; font-size: .72rem; background: #F4F1FA; border: 1px solid #DDD3F0; color: #4B3A78;
  border-radius: 6px; padding: 1px 6px; margin: 2px 4px 2px 0;}
.cp-sms {background: #E7F6EC; border-radius: 16px 16px 16px 4px; padding: 12px 14px; font-size: .92rem;
  border: 1px solid #CDE9D6; max-width: 460px;}
.cp-sms small {display: block; color: #5B6B60; margin-top: 6px; font-size: .72rem;}
.cp-step {display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px dashed #E5ECE2;
  font-size: .85rem;}
.cp-srv {font-size: .68rem; font-weight: 700; border-radius: 6px; padding: 2px 6px; min-width: 86px; text-align: center;}
.srv-crop-pilot {background: #DCF5E5; color: #14632F;} .srv-filesystem {background: #EDE7FB; color: #4B2E99;}
.srv-ollama {background: #FFEFD9; color: #8A4B00;} .srv-guard, .srv-none {background: #FDE2E2; color: #A12A2A;}
.srv-officer {background: #E0ECFB; color: #1E4C8F;} .srv-graph {background: #EEE; color: #555;}
.cp-lockbox {background: #D64545; color: #fff; border-radius: 10px; padding: 10px 14px; margin: 8px 0; font-weight: 600;}
.cp-count {background: #fff; border: 1px solid #DDE5DA; border-radius: 12px; padding: 10px 14px; text-align: center;}
.cp-count span {display: block; font-size: 1.6rem; font-weight: 800;} .cp-count b {font-size: .75rem; color: #5B6B60;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

e = html.escape
VERDICT_ICON = {"PLANT": "🌱 PLANT", "SPRAY": "🧴 SPRAY", "HOLD": "✋ HOLD"}
STATUS_LABEL = {"PENDING_REVIEW": "Awaiting signature", "SECURITY_LOCK": "Security lock",
                "NEEDS_DATA": "Needs field data", "APPROVED": "Signed & sent", "REJECTED": "Rejected"}


def verdict_html(v: str | None) -> str:
    return f'<span class="cp-verdict v-{v or "NONE"}">{VERDICT_ICON.get(v, "— NO ADVICE")}</span>'


def status_html(s: str) -> str:
    return f'<span class="cp-status-pill s-{s}">{e(STATUS_LABEL.get(s, s))}</span>'


def kv(label: str, value) -> str:
    return f'<div class="cp-kv"><b>{e(label)}</b><span>{e(str(value))}</span></div>'


def trace_html(rows: list[dict]) -> str:
    out = []
    for r in sorted(rows, key=lambda x: x["id"]):
        srv = r["server"]
        label = {"crop-pilot": "OUR MCP", "filesystem": "3RD-PARTY MCP", "ollama": "LOCAL LLM", "guard": "GUARD",
                 "officer": "OFFICER", "graph": "GRAPH", "none": "BLOCKED"}.get(srv, srv.upper())
        status = "✅" if r["status"] == "ok" else ("⛔" if r["status"] == "blocked" else "⚠️")
        who = f' · <i>{e(r["actor"])}</i>' if r["actor"] != "agent" else ""
        out.append(f'<div class="cp-step"><span class="cp-srv srv-{e(srv)}">{label}</span>{status} '
                   f'<code>{e(r["tool"])}</code><span class="cp-meta">{r["latency_ms"] or 0:.0f} ms{who}</span></div>')
    return "".join(out) or '<span class="cp-meta">No trace.</span>'


# ------------------------------------------------------------------------------------------- header
st.markdown(
    '<div class="cp-hero"><h1>🌱 Crop-Pilot Control Desk</h1>'
    "<p>Ministry of Agriculture · Nairobi County Extension Office · Dagoretti South Division</p>"
    '<span class="cp-pill">Climate-smart advisory · Plant / Spray / Hold</span>'
    '<span class="cp-pill">🔒 Human-in-the-loop: every message needs a named officer</span>'
    '<span class="cp-pill">🇰🇪 Local data · local model</span></div>', unsafe_allow_html=True)

try:
    health = api.health()
except api.ApiError as exc:
    st.error(f"Backend unreachable: {exc.detail}. Start it with `make run`.")
    st.stop()

degraded = not health["ok"]


def chip(label, text, cls):
    return f'<div class="cp-chip"><b>{label}</b><span class="cp-dot {cls}"></span>{e(text)}</div>'


st.markdown('<div class="cp-status">'
            + chip("Database", "Healthy" if health["database"]["ok"] else "Corrupt: manual mode",
                   "ok" if health["database"]["ok"] else "bad")
            + chip("Local model", f'{health["llm_model"]} · {"online" if health["llm_available"] else "offline (rules only)"}',
                   "ok" if health["llm_available"] else "warn")
            + chip("Third-party MCP", "filesystem server ready" if health["npx_available"] else "npx missing",
                   "ok" if health["npx_available"] else "warn")
            + chip("Outbound channel", "SMS (simulated) · officer-gated", "ok")
            + "</div>", unsafe_allow_html=True)

tab_gate, tab_tel, tab_out = st.tabs(["🛂  Review queue", "📈  Agent telemetry", "📤  Sent messages & recovery"])

# ------------------------------------------------------------------------------------------- tab 1
with tab_gate:
    if degraded:
        st.error("**Database failed its integrity check.** The agent is paused to avoid advising on corrupt records. "
                 "Record decisions in the manual backup form under **Sent messages & recovery**.")
    else:
        all_adv = api.advisories()
        counts = {s: sum(a["status"] == s for a in all_adv) for s in STATUS_LABEL}
        left, right = st.columns([1, 2.4], gap="large")

        with left:
            st.markdown("#### Draft new advice")
            with st.form("run", border=True):
                hid = st.selectbox("Household", api.households())
                note = st.text_area("Officer note (optional)", max_chars=300, height=80,
                                    placeholder="e.g. Farmer called about leaf damage")
                go = st.form_submit_button("▶  Run agent", type="primary", width="stretch")
            if go:
                with st.status("Agent working… (local model, about 1–3 min on CPU)", expanded=True) as box:
                    st.write("Gathering plot, rainfall and pest evidence through MCP tools…")
                    try:
                        res = api.run_agent(hid, note)
                        st.session_state["last_run"] = res
                        box.update(label=f"Draft ready in {res['elapsed_s']} s. Waiting for your signature.",
                                   state="complete", expanded=False)
                    except api.ApiError as exc:
                        box.update(label="Run failed", state="error")
                        st.error(str(exc.detail))
            last = st.session_state.get("last_run")
            if last:
                adv = last["advisory"]
                st.markdown(f'<div class="cp-card"><div class="cp-meta">Last run · {e(last["run_id"])}</div>'
                            f'<div style="margin:8px 0">{verdict_html(adv.get("verdict"))} '
                            f'{status_html(adv.get("status", ""))}</div>'
                            f'<div class="cp-meta">Frozen at human gate: <b>{"yes" if last["frozen_at_human_gate"] else "no"}</b>'
                            f' · LLM used: <b>{"yes" if last["llm_used"] else "no"}</b></div></div>',
                            unsafe_allow_html=True)

            st.markdown("#### Queue")
            c1, c2 = st.columns(2)
            c1.markdown(f'<div class="cp-count"><span>{counts["PENDING_REVIEW"]}</span><b>Awaiting</b></div>',
                        unsafe_allow_html=True)
            c2.markdown(f'<div class="cp-count"><span style="color:#D64545">{counts["SECURITY_LOCK"]}</span>'
                        f'<b>Locked</b></div>', unsafe_allow_html=True)
            c3, c4 = st.columns(2)
            c3.markdown(f'<div class="cp-count"><span>{counts["NEEDS_DATA"]}</span><b>Need data</b></div>',
                        unsafe_allow_html=True)
            c4.markdown(f'<div class="cp-count"><span style="color:#1F7A4D">{counts["APPROVED"]}</span>'
                        f'<b>Sent</b></div>', unsafe_allow_html=True)

        with right:
            drafts = [a for a in all_adv if a["status"] in ("SECURITY_LOCK", "PENDING_REVIEW", "NEEDS_DATA")]
            drafts.sort(key=lambda a: (a["status"] != "SECURITY_LOCK", -a["id"]))
            st.markdown(f"#### Drafts waiting for a named officer ({len(drafts)})")
            if not drafts:
                st.info("Nothing waiting. Run the agent for a household on the left.")
            for adv in drafts:
                ev = adv.get("evidence") or {}
                plot, rain, threat = ev.get("plot") or {}, ev.get("rain") or {}, ev.get("pest_threat")
                lock = adv["status"] == "SECURITY_LOCK"
                stage = (plot.get("growth_stage") or "—").replace("_", " ").title()
                head = (f'<div class="cp-card{" lock" if lock else ""}"><div class="cp-head">'
                        f'{verdict_html(adv["verdict"])}<b style="font-size:1.05rem">{e(adv["household_id"])}</b>'
                        f'{status_html(adv["status"])}<span class="cp-meta">#{adv["id"]} · '
                        f'{e(str(plot.get("zone_id") or "—"))} · {e(str(plot.get("active_crop") or "no crop"))} · '
                        f'{e(stage)}</span></div>')
                if lock:
                    head += ('<div class="cp-lockbox">🚨 Possible prompt injection: instruction-like text was found in '
                             'this household\'s record. The notes were redacted and never reached the model. This draft '
                             'cannot be signed. Check the record, then reject it.</div>')
                if adv["status"] == "NEEDS_DATA":
                    head += ('<div class="cp-meta" style="margin-top:8px">⚪ The profile is missing a crop or zone. '
                             'The agent stopped instead of guessing. Schedule a field visit.</div>')
                if rain.get("spray_safety_index") is not None:
                    head += '<div class="cp-grid">' + "".join([
                        kv("Spray safety", f'{rain["spray_safety_index"]:.0f} · {rain.get("spray_band")}'),
                        kv("Rain 72 h", f'{rain.get("rain_72h_mm")} mm'),
                        kv("Rain 7 days", f'{rain.get("rain_7d_mm")} mm'),
                        kv("Planting window", rain.get("planting_window") or "—"),
                        kv("Nearest threat", f'{threat["pest"]} · {threat["distance_km"]} km' if threat else "None verified"),
                        kv("Days planted", plot.get("days_since_planting") if plot.get("days_since_planting") is not None
                           else "not planted"),
                    ]) + "</div>"
                head += "</div>"
                st.markdown(head, unsafe_allow_html=True)

                can_sign = adv["status"] == "PENDING_REVIEW"
                details = st.expander("Review evidence & sign" if can_sign else "Review & reject",
                                      expanded=adv is drafts[0])
                c1, c2 = details.columns([1.15, 1])
                with c1:
                    st.markdown("**Why**")
                    st.write(adv["rationale"])
                    st.markdown("**Sources cited**<br>" + "".join(f'<span class="cp-src">{e(s)}</span>'
                                                                  for s in adv["sources"]), unsafe_allow_html=True)
                    if adv["flags"]:
                        st.markdown("**Flags**<br>" + "".join(f'<span class="cp-flag">{e(f)}</span>'
                                                              for f in adv["flags"]), unsafe_allow_html=True)
                    if adv.get("model_verdict") and adv["model_verdict"] != adv["rule_verdict"]:
                        st.warning(f"The local model suggested **{adv['model_verdict']}**. The safety rules chose "
                                   f"**{adv['rule_verdict']}**. Check the evidence.")
                with c2:
                    st.markdown("**Message to farmer (preview)**")
                    if can_sign:
                        st.markdown(f'<div class="cp-sms">{e(adv["farmer_message"] or "")}'
                                    f'<small>SMS to {e(adv["household_id"])} · not sent</small></div>',
                                    unsafe_allow_html=True)
                    else:
                        st.caption("No farmer message. This draft cannot be sent; reject it once the record is fixed.")
                    if plot.get("data_quality"):
                        with st.expander(f"🧹 Data repairs ({len(plot['data_quality'])})"):
                            for q in plot["data_quality"]:
                                st.markdown(f"- {e(q)}")
                    with st.expander("🔎 Agent trace"):
                        try:
                            st.markdown(trace_html(api.telemetry(adv["run_id"])), unsafe_allow_html=True)
                        except api.ApiError as exc:
                            st.caption(str(exc.detail))

                with details.form(f"review-{adv['id']}", border=True):
                    msg = None
                    if can_sign:
                        msg = st.text_area("Final message (you can edit before signing)", adv["farmer_message"] or "",
                                           max_chars=320, height=90)
                    f1, f2 = st.columns([1.3, 1])
                    name = f1.text_input("Your full name (signature)", key=f"name-{adv['id']}",
                                         placeholder="e.g. Wanjiru Kamau")
                    reason = f2.text_input("Reason (if rejecting)", key=f"reason-{adv['id']}")
                    confirm = False
                    if can_sign:
                        confirm = st.checkbox("I have checked the evidence and take responsibility for this advice.",
                                              key=f"confirm-{adv['id']}")
                    b1, b2, _ = st.columns([1, 1, 2])
                    do_approve = b1.form_submit_button("✅ Sign & send", type="primary", disabled=not can_sign,
                                                       width="stretch") if can_sign else False
                    do_reject = b2.form_submit_button("✖ Reject", width="stretch")
                    try:
                        if do_approve:
                            if not confirm:
                                st.error("Tick the confirmation box to sign.")
                            else:
                                r = api.approve(adv["id"], name, msg)
                                st.success(f"Signed by {r['officer']}. Queued as SMS #{r['outbox_id']} (simulated).")
                                st.rerun()
                        if do_reject:
                            r = api.reject(adv["id"], name, reason)
                            st.info(f"Rejected by {r['officer']}.")
                            st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
                st.write("")

# ------------------------------------------------------------------------------------------- tab 2
with tab_tel:
    if degraded:
        st.warning("Telemetry is unavailable while the database is degraded.")
    else:
        rows = api.telemetry()
        if not rows:
            st.info("No calls logged yet.")
        else:
            df = pd.DataFrame(rows)
            runs = ["All runs"] + sorted(df["run_id"].unique().tolist(), reverse=True)
            pick = st.selectbox("Run", runs)
            if pick != "All runs":
                df = df[df["run_id"] == pick]
            m = st.columns(5)
            m[0].metric("Logged actions", len(df))
            m[1].metric("MCP tool calls", int(df["server"].isin(["crop-pilot", "filesystem"]).sum()))
            m[2].metric("LLM tokens", f'{int(df.loc[df["server"] == "ollama", "token_estimate"].fillna(0).sum()):,}')
            m[3].metric("Blocked attempts", int((df["status"] == "blocked").sum()))
            m[4].metric("Signed by officer", int(df["approved_by"].notna().sum()))
            g1, g2 = st.columns(2)
            with g1:
                st.markdown("**Mean latency by step (ms)**")
                st.bar_chart(df.groupby("tool")["latency_ms"].mean().sort_values(ascending=False), color="#1F7A4D",
                             horizontal=True)
            with g2:
                st.markdown("**Actions by server**")
                st.bar_chart(df["server"].value_counts(), color="#3E9B5F", horizontal=True)
            st.markdown("**Audit log**")
            st.dataframe(df[["id", "ts", "run_id", "server", "tool", "actor", "status", "latency_ms", "token_estimate",
                             "approved_by", "call_hash", "inputs_json", "output_json"]],
                         width="stretch", height=420, hide_index=True)

# ------------------------------------------------------------------------------------------- tab 3
with tab_out:
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        st.markdown("#### Sent messages")
        st.caption("Only officer-signed messages can appear here. The channel is simulated; no real SMS is sent.")
        if degraded:
            st.warning("Unavailable while the database is degraded.")
        else:
            out = api.outbox()
            if not out:
                st.info("No messages sent yet.")
            for o in out:
                st.markdown(f'<div class="cp-card"><div class="cp-meta">#{o["id"]} · {e(o["household_id"])} · '
                            f'{e(o["channel"])} · {e(o["queued_at"][:19].replace("T", " "))} UTC</div>'
                            f'<div class="cp-sms" style="margin-top:8px">{e(o["message"])}'
                            f'<small>Signed by {e(o["officer_signature"])}</small></div></div>',
                            unsafe_allow_html=True)
    with right:
        st.markdown("#### Manual backup form" + (" · ACTIVE" if degraded else ""))
        st.caption("Use when the database is corrupt. Entries go to a local append-only file to be synced later.")
        with st.form("manual", border=True):
            m_name = st.text_input("Officer full name")
            m_hid = st.text_input("Household ID")
            m_verdict = st.selectbox("Decision", ["HOLD", "PLANT", "SPRAY"])
            m_note = st.text_area("Field note", max_chars=500, height=80)
            if st.form_submit_button("Save to manual queue", width="stretch"):
                try:
                    r = api.manual_fallback(m_name, m_hid, m_verdict, m_note)
                    st.success(f"Saved ({r['status']}).")
                except api.ApiError as exc:
                    st.error(str(exc.detail))
        manual = api.manual_fallback_list()
        if manual:
            st.dataframe(pd.DataFrame(manual), width="stretch", hide_index=True)

    with st.expander("Reviewed advisories (history)"):
        if not degraded:
            done = [a for a in api.advisories() if a["status"] in ("APPROVED", "REJECTED")]
            if done:
                st.dataframe(pd.DataFrame(done)[["id", "household_id", "verdict", "status", "officer_signature",
                                                 "reviewed_at", "review_note"]], width="stretch", hide_index=True)
            else:
                st.caption("None yet.")

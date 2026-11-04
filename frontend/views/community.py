"""Community board: farmers and officers discuss pests, weather, soil and greenhouses.

Posts are not verified signals and the advisory agent never reads them, until an extension officer confirms a pest
report: that creates a verified pest alert, and the officer's answer (with today's spray-safety reading for the ward)
is posted on the board and texted to farmers who reported by SMS. Instruction-like posts are held.
"""
from __future__ import annotations

import streamlit as st

import api_client as api
import ui

WARDS = ["RIRUTA", "WAITHAKA", "MUTUINI", "NGANDO", "UTHIRU"]
PESTS = ["Fall Armyworm", "Late Blight", "Aphids", "Bean fly", "Maize Lethal Necrosis", "Tomato leaf miner (Tuta)"]
role, mine = st.session_state.get("role", "officer"), st.session_state.get("my_farm")
my_zone = st.session_state.get("farm_info", {}).get(mine or "", {}).get("zone_id")

ui.header("Community", "Ask and share what you see in your fields. Pest reports an officer confirms become official "
                       "alerts.")


def report_review(r: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{r['author']}** · {(r.get('zone_id') or 'ward not given').title()}"
                    f"{' · :blue-badge[via SMS]' if r.get('source') == 'sms' else ''}  \n"
                    f"<span class='cp-muted'>{r['created_at'][:16].replace('T', ' ')}</span>", unsafe_allow_html=True)
        st.write(r["body"])
        with st.form(f"report-{r['id']}", border=False):
            c = st.columns([1.4, 1, 1])
            pest = c[0].selectbox("Pest or disease", PESTS, key=f"rp-{r['id']}")
            sev = c[1].selectbox("Severity", ["MEDIUM", "HIGH", "LOW"], key=f"rs-{r['id']}")
            zone = c[2].selectbox("Ward", WARDS, format_func=str.title, key=f"rz-{r['id']}",
                                  index=WARDS.index(r["zone_id"]) if r.get("zone_id") in WARDS else 0)
            note = st.text_input("Note to the farmer (optional)", key=f"rn-{r['id']}", max_chars=400)
            f = st.columns([1.5, 1, 1])
            name = f[0].text_input("Your full name", key=f"rname-{r['id']}")
            confirm = f[1].form_submit_button("✅ Confirm pest", type="primary", width="stretch")
            reject = f[2].form_submit_button("Not confirmed", width="stretch")
            try:
                if confirm or reject:
                    res = api.review_report(r["id"], name, "CONFIRMED" if confirm else "NOT_CONFIRMED",
                                            pest if confirm else None, sev, zone, note)
                    st.session_state["report_done"] = res
                    st.rerun()
            except api.ApiError as exc:
                st.error(str(exc.detail))


if role == "officer":
    done = st.session_state.pop("report_done", None)
    if done:
        safety = done.get("spray_safety")
        if done["status"] == "CONFIRMED" and safety:
            st.success(f"Confirmed and added as a verified pest alert. **Spray safety in that ward today: "
                       f"{safety['label']}** (score {safety['index']:.0f}/100). Your answer is posted"
                       + (" and texted to the farmer." if done.get("sms_id") else "."), icon=":material/check_circle:")
        else:
            st.info("Marked as not confirmed. Your answer is posted" + (" and texted to the farmer."
                    if done.get("sms_id") else "."), icon=":material/info:")
    reports = api.community_reports()
    st.markdown(f"#### Pest reports to confirm ({len(reports)})")
    st.caption("Farmers' pest posts, including ones sent by SMS. Confirming one makes it a verified alert that the "
               "advice uses, and tells farmers today's spray-safety reading for that ward. Check it first (a visit, a "
               "call or a photo).")
    for r in reports:
        report_review(r)
    if not reports:
        st.caption("Nothing waiting.")
    st.divider()

topics = api.forum_topics()
left, right = st.columns([2, 1], gap="large")
with right:
    with st.form("post", clear_on_submit=True):
        st.markdown("**New post**")
        author = st.text_input("Your name", max_chars=40)
        topic = st.selectbox("Topic", topics)
        ward = st.selectbox("Ward", WARDS, format_func=str.title,
                            index=WARDS.index(my_zone) if my_zone in WARDS else 0)
        body = st.text_area("Message", max_chars=800, height=110)
        if st.form_submit_button("Post", type="primary", width="stretch"):
            try:
                if api.forum_post(author, topic, body, ward, mine)["held"]:
                    st.warning("Held for a moderator to check.")
                else:
                    st.toast("Posted", icon=":material/check:")
            except api.ApiError as exc:
                st.error(str(exc.detail))
    st.caption("Posts are not verified. An officer checks pest reports; to send a photo, use AI Scan. No data? Text "
               "PROBLEM and what you see (see Notifications).")

with left:
    pick = st.segmented_control("Topic", ["All"] + topics, default="All", label_visibility="collapsed")
    posts = api.forum(None if pick in (None, "All") else pick)
    if not posts:
        st.caption("No posts in this topic yet.")
    for p in posts:
        officer = p["role"] == "officer"
        badge = {"CONFIRMED": f" · :green-badge[Confirmed by {p.get('reviewed_by')}]",
                 "NOT_CONFIRMED": f" · :gray-badge[Checked: not confirmed]"}.get(p.get("review_status") or "", "")
        with st.chat_message("assistant" if officer else "user",
                             avatar=":material/verified:" if officer else ":material/person:"):
            st.markdown(f"**{p['author']}**{' · Extension officer' if officer else ''}{badge}"
                        f"{' · :blue-badge[via SMS]' if p.get('source') == 'sms' else ''}  \n"
                        f"<span class='cp-muted'>{p['topic']}"
                        f"{' · ' + p['zone_id'].title() if p.get('zone_id') else ''}"
                        f" · {p['created_at'][:16].replace('T', ' ')}</span>", unsafe_allow_html=True)
            if p["held"]:
                st.caption(p["body"])
            else:
                st.write(p["body"])

"""Farmer notifications: advice the officer signed, photo results, and the farmer's own reminders that are due."""
from __future__ import annotations

import streamlit as st

import api_client as api
import ui

LANGUAGE = {"en": "English", "sw": "Kiswahili"}
ICON = {"advice": ":material/sms:", "photo": ":material/photo_camera:", "reminder": ":material/alarm:"}

hid = st.session_state.get("my_farm")
ui.header("Notifications", "Messages from your extension officer, results for photos you sent, and reminders due.")
if not hid:
    st.info("Notifications are for farmers. Switch \"I am\" to a farmer.")
    st.stop()
items = api.notifications(hid, seen=True)
pref = (api.household_profile(hid)["plot"].get("language") or "en")
order = ["sw", "en"] if pref == "sw" else ["en", "sw"]
c = st.columns([1.4, 3], vertical_alignment="center")
choice = c[0].selectbox("My messages in", ["en", "sw", "both"], index=["en", "sw", "both"].index(pref),
                        format_func={"en": "English", "sw": "Kiswahili", "both": "English and Kiswahili"}.get)
c[1].caption("Your officer sends advice in this language. It also comes by SMS, so you get it without internet.")
if choice != pref:
    api.set_language(hid, choice)
    st.toast("Saved. Your officer will see your choice.", icon=":material/check:")
    st.rerun()
if not items:
    st.info("Nothing yet. When your extension officer sends advice or checks a photo, it appears here.",
            icon=":material/notifications:")
for n in items:
    with st.container(border=True):
        st.markdown(f"{ICON.get(n['kind'], '')} **{n['title']}**  <span class='cp-muted'>· "
                    f"{(n['when'] or '')[:16].replace('T', ' ')} · from {n['from']}</span>", unsafe_allow_html=True)
        messages = sorted(n.get("messages") or [{"language": "en", "text": n["body"]}],
                          key=lambda m: order.index(m["language"]) if m["language"] in order else 9)
        for m in messages:
            if len(messages) > 1:
                st.caption(LANGUAGE.get(m["language"], m["language"]))
            st.write(m["text"])
        if n.get("what"):
            st.markdown(f"**What it is:** {n['what']}")
        if n.get("steps"):
            st.markdown("**What to do:**\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(n["steps"], 1)))


with st.expander("No internet? Use SMS", icon=":material/sms:", expanded=False):
    st.markdown("Text these from any phone (no data needed). Your officer's advice and photo results also come by "
                "SMS.\n\n"
                "- `LOG WEEDING whole plot` · `LOG PLANT BEANS` · `LOG SPRAY maize`: saves to your plot history\n"
                "- `REMIND 2026-10-20 SPRAY maize` or `REMIND tomorrow WEED`: sets a reminder\n"
                "- `PROBLEM holes in my maize leaves`: your officer checks it and replies by SMS\n\n"
                "In Kiswahili: `REKODI PALILIA`, `KUMBUSHA kesho NYUNYIZA`, `SHIDA ...`. A photo needs internet: send "
                "it in AI Scan when you have a connection, or ask your officer to take one on a visit.")
    st.caption("Demo phone: a real SMS gateway would receive these from your number.")
    with st.form("sms-demo", clear_on_submit=True):
        c = st.columns([3, 1], vertical_alignment="bottom")
        text = c[0].text_input("Your SMS", placeholder="LOG WEEDING whole plot")
        if c[1].form_submit_button("Send SMS", width="stretch") and text.strip():
            try:
                r = api.sms_inbound(hid, text)
                st.toast(r["reply"], icon=":material/sms:")
            except api.ApiError as exc:
                st.error(str(exc.detail))
    thread = api.sms_messages(hid)[:12]
    for m in thread:
        who = "You" if m["direction"] == "IN" else ("Extension officer" if m["sent_by"] not in (None, "system")
                                                     else "Mkulima Hub")
        st.markdown(f"<span class='cp-muted'>{m['created_at'][:16].replace('T', ' ')} · {who}</span>  \n{m['body']}",
                    unsafe_allow_html=True)

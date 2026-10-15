"""Farmer notifications: advice the officer signed, photo results, and the farmer's own reminders that are due."""
from __future__ import annotations

import streamlit as st

import api_client as api
import ui

ICON = {"advice": ":material/sms:", "photo": ":material/photo_camera:", "reminder": ":material/alarm:"}

hid = st.session_state.get("my_farm")
ui.header("Notifications", "Messages from your extension officer, results for photos you sent, and reminders due.")
if not hid:
    st.info("Notifications are for farmers. Switch \"I am\" to a farmer.")
    st.stop()
items = api.notifications(hid)
if not items:
    st.info("Nothing yet. When your extension officer sends advice or checks a photo, it appears here.",
            icon=":material/notifications:")
for n in items:
    with st.container(border=True):
        st.markdown(f"{ICON.get(n['kind'], '')} **{n['title']}**  <span class='cp-muted'>· "
                    f"{(n['when'] or '')[:16].replace('T', ' ')} · from {n['from']}</span>", unsafe_allow_html=True)
        st.write(n["body"])

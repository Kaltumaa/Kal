"""Community board: farmers and officers discuss pests, weather, soil and greenhouses.

Posts are not verified signals and the advisory agent never reads them. Instruction-like posts are held.
"""
from __future__ import annotations

import streamlit as st

import api_client as api
import ui

ui.header("Community", "Ask and share what you see in your fields. Confirmed problems become official alerts.")
topics = api.forum_topics()
left, right = st.columns([2, 1], gap="large")

with right:
    with st.form("post", clear_on_submit=True):
        st.markdown("**New post**")
        author = st.text_input("Your name", max_chars=40)
        topic = st.selectbox("Topic", topics)
        body = st.text_area("Message", max_chars=800, height=110)
        if st.form_submit_button("Post", type="primary", width="stretch"):
            try:
                if api.forum_post(author, topic, body)["held"]:
                    st.warning("Held for a moderator to check.")
                else:
                    st.toast("Posted", icon=":material/check:")
            except api.ApiError as exc:
                st.error(str(exc.detail))
    st.caption("Posts are not verified. To report a pest officially, use Field scan.")

with left:
    pick = st.segmented_control("Topic", ["All"] + topics, default="All", label_visibility="collapsed")
    posts = api.forum(None if pick in (None, "All") else pick)
    if not posts:
        st.caption("No posts in this topic yet.")
    for p in posts:
        officer = p["role"] == "officer"
        with st.chat_message("assistant" if officer else "user",
                             avatar=":material/verified:" if officer else ":material/person:"):
            st.markdown(f"**{p['author']}**{' · Extension officer' if officer else ''}  \n"
                        f"<span class='cp-muted'>{p['topic']} · {p['created_at'][:16].replace('T', ' ')}</span>",
                        unsafe_allow_html=True)
            if p["held"]:
                st.caption(p["body"])
            else:
                st.write(p["body"])

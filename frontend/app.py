"""Mkulima Hub (Streamlit, multi-page). Talks to the backend ONLY over HTTP via api_client.

Two views: the extension officer (all farms; the only one who can approve advice) and a farmer (their own farm).
The view switch is a demo convenience, not authentication.

Run:  streamlit run frontend/app.py
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import api_client as api
import cloud
import ui
from views import system

st.set_page_config(page_title="Mkulima Hub", page_icon="🌱", layout="wide")
ui.setup()
st.logo(str(Path(__file__).parent / "assets" / "logo.svg"), size="large")

cloud.ensure_backend()
try:
    health = api.health()
    farms = api.farms() if health["ok"] else []
except api.ApiError as exc:
    st.error(f"Backend unreachable. Run `make run`. ({exc.detail})")
    st.stop()
st.session_state["farm_names"] = {f["household_id"]: f["farmer_name"] for f in farms}
st.session_state["farm_info"] = {f["household_id"]: f for f in farms}

with st.sidebar:
    options = ["officer"] + [f["household_id"] for f in farms]
    role = st.selectbox("I am", options, key="role_pick",
                        format_func=lambda o: "Extension officer" if o == "officer"
                        else f"Farmer: {ui.farm_label(o)}")
st.session_state["role"] = "officer" if role == "officer" else "farmer"
st.session_state["my_farm"] = None if role == "officer" else role

if st.session_state["role"] == "officer":
    pages = {
        "Advisory": [
            st.Page("views/home.py", title="Dashboard", icon=":material/dashboard:", default=True),
            st.Page("views/queue.py", title="Review queue", icon=":material/fact_check:"),
            st.Page("views/household.py", title="Farms", icon=":material/home_pin:"),
            st.Page("views/plot_history.py", title="Plot history", icon=":material/history:"),
            st.Page("views/scan.py", title="Verify photos", icon=":material/photo_camera:"),
        ],
        "Farmer hub": [
            st.Page("views/learn.py", title="Learn", icon=":material/menu_book:"),
            st.Page("views/community.py", title="Community", icon=":material/forum:"),
        ],
        "System": [
            st.Page(system.activity_log, title="Activity log", icon=":material/receipt_long:", url_path="activity"),
            st.Page(system.outbox, title="Sent messages", icon=":material/outbox:", url_path="sent"),
        ],
    }
else:
    try:
        count = len(api.notifications(st.session_state["my_farm"]))
    except api.ApiError:
        count = 0
    pages = {
        "My farm": [
            st.Page("views/household.py", title="My farm", icon=":material/home_pin:", default=True),
            st.Page("views/notifications.py", title=f"Notifications ({count})" if count else "Notifications",
                    icon=":material/notifications:"),
            st.Page("views/plot_history.py", title="Plot history", icon=":material/history:"),
            st.Page("views/reminders.py", title="Reminders", icon=":material/alarm:"),
            st.Page("views/scan.py", title="AI Scan", icon=":material/photo_camera:"),
        ],
        "Farmer hub": [
            st.Page("views/learn.py", title="Learn", icon=":material/menu_book:"),
            st.Page("views/community.py", title="Community", icon=":material/forum:"),
        ],
    }
nav = st.navigation(pages)

with st.sidebar:
    if st.session_state["role"] == "farmer":
        st.caption("Farmers see their own farm and advice an officer has signed. Only the extension officer can "
                   "approve advice.")
    rows = [("Database", health["database"]["ok"]), (f"Local AI · {health['llm_model']}", health["llm_available"]),
            ("Guidance library (MCP)", health["npx_available"])]
    st.markdown('<div class="cp-status"><b>System status</b>' + "".join(
        f'<div><span class="cp-dot {"ok" if ok else "warn"}"></span>{name}</div>' for name, ok in rows)
        + f'<div style="margin-top:6px">Demo date: {health["today"]}</div></div>', unsafe_allow_html=True)
    if cloud.hosted():
        st.caption("Online demo: the local AI models are off on free hosting, so drafts come from the fixed rules "
                   "and photos go to the officer without an AI suggestion. The full version runs on a laptop.")

nav.run()

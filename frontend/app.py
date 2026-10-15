"""Crop-Pilot Control Desk (Streamlit, multi-page). Talks to the backend ONLY over HTTP via api_client.

Run:  streamlit run frontend/app.py
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import api_client as api
import ui
from views import system

st.set_page_config(page_title="Crop-Pilot", page_icon="🌱", layout="wide")
ui.setup()
st.logo(str(Path(__file__).parent / "assets" / "logo.svg"), size="large")

nav = st.navigation({
    "Advisory": [
        st.Page("views/home.py", title="Dashboard", icon=":material/dashboard:", default=True),
        st.Page("views/queue.py", title="Review queue", icon=":material/fact_check:"),
        st.Page("views/scan.py", title="Field scan", icon=":material/photo_camera:"),
    ],
    "Farmer hub": [
        st.Page("views/learn.py", title="Learn", icon=":material/menu_book:"),
        st.Page("views/community.py", title="Community", icon=":material/forum:"),
    ],
    "System": [
        st.Page(system.telemetry, title="Activity log", icon=":material/monitoring:", url_path="telemetry"),
        st.Page(system.outbox, title="Sent messages", icon=":material/outbox:", url_path="sent"),
    ],
})

with st.sidebar:
    try:
        h = api.health()
    except api.ApiError as exc:
        st.error(f"Backend unreachable. Run `make run`. ({exc.detail})")
        st.stop()
    rows = [("Database", h["database"]["ok"]), (f"Model · {h['llm_model']}", h["llm_available"]),
            ("Filesystem MCP", h["npx_available"])]
    st.markdown('<div class="cp-status">' + "".join(
        f'<div><span class="cp-dot {"ok" if ok else "warn"}"></span>{name}</div>' for name, ok in rows)
        + '<div style="margin-top:6px">Dagoretti South extension desk</div></div>', unsafe_allow_html=True)

nav.run()

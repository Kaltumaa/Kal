"""TALO (Streamlit, multi-page). Talks to the backend ONLY over HTTP via api_client.

Everyone signs in first (JWT kept in st.session_state). The account decides the view: farmers see their own farm
(while an institution pays for their access), extension officers the desk, institutions the officers they manage and
the payment page.

Run:  streamlit run frontend/app.py
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import api_client as api
import auth
import cloud
import ui
from views import system

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="TALO · Good advice, good yield", page_icon=str(ASSETS / "talo-wordmark.png"),
                   layout="wide")
ui.setup()
st.logo(str(ASSETS / "talo-wordmark.png"), size="large", icon_image=str(ASSETS / "talo-wordmark.png"))

cloud.ensure_backend()
try:
    health = api.health()
    farms = api.farms() if health["ok"] else []
except api.ApiError as exc:
    st.error(f"Backend unreachable. Run `make run`. ({exc.detail})")
    st.stop()
st.session_state["farm_names"] = {f["household_id"]: f["farmer_name"] for f in farms}
st.session_state["farm_info"] = {f["household_id"]: f for f in farms}

auth.refresh()
account = auth.user()
account_page = st.Page("views/account.py", title="My account" if account else "Sign in",
                       icon=":material/account_circle:", url_path="account", default=account is None)

# --- Signed out: the sign-in / sign-up page is the only way in -------------------------------------------------------
if account is None:
    st.session_state["role"] = None
    st.session_state["my_farm"] = None
    st.navigation([account_page], position="hidden").run()
    st.stop()

# --- A farmer whose access no institution has paid for sees only their account --------------------------------------
if account["role"] == "farmer" and not (account.get("access") or {}).get("active"):
    st.session_state["role"], st.session_state["my_farm"] = "farmer", None
    with st.sidebar:
        st.markdown(f"**{account['full_name']}**")
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            auth.sign_out()
            st.rerun()
    st.navigation([account_page], position="hidden").run()
    st.stop()

with st.sidebar:
    if account:
        st.markdown(f"**{account['full_name']}**  \n<span class='cp-muted'>{auth.ROLE_LABEL[account['role']]}"
                    f"{' · Lead Farmer' if account.get('is_lead_farmer') else ''}"
                    f"{' · ' + account['sub_county'] if account.get('sub_county') else ''}</span>",
                    unsafe_allow_html=True)
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            auth.sign_out()
            st.rerun()
        role = {"extension_officer": "officer", "institution": "institution"}.get(
            account["role"], account.get("household_id") or "no_farm")
st.session_state["role"] = role if role in ("officer", "institution") else "farmer"
st.session_state["my_farm"] = None if role in ("officer", "institution", "no_farm") else role

if st.session_state["role"] == "institution":
    pages = {
        "Institution": [
            st.Page("views/institution.py", title="My officers", icon=":material/badge:", default=True),
            st.Page("views/escalations.py", title="Escalations", icon=":material/priority_high:"),
        ],
        "Account": [account_page],
    }
elif st.session_state["role"] == "farmer" and st.session_state["my_farm"] is None:
    pages = {"Farmer hub": [
        st.Page("views/learn.py", title="Learn", icon=":material/menu_book:", default=True),
        st.Page("views/community.py", title="Community", icon=":material/forum:")], "Account": [account_page]}
    st.sidebar.info("Your account is not linked to a farm yet. Ask your extension officer to register your farm.")
elif st.session_state["role"] == "officer":
    pages = {
        "Advisory": [
            st.Page("views/home.py", title="Dashboard", icon=":material/dashboard:", default=True),
            st.Page("views/queue.py", title="Review queue", icon=":material/fact_check:"),
            st.Page("views/household.py", title="Farms", icon=":material/home_pin:"),
            st.Page("views/crop_calendar.py", title="Crop calendar", icon=":material/calendar_month:"),
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
            st.Page(system.phone_calls, title="Phone calls", icon=":material/call:", url_path="calls"),
        ],
        "Account": [account_page],
    }
    pages["Advisory"].append(st.Page("views/escalations.py", title="Escalations", icon=":material/priority_high:"))
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
            st.Page("views/crop_calendar.py", title="Crop calendar", icon=":material/calendar_month:"),
            st.Page("views/plot_history.py", title="Plot history", icon=":material/history:"),
            st.Page("views/reminders.py", title="Reminders", icon=":material/alarm:"),
            st.Page("views/scan.py", title="AI Scan", icon=":material/photo_camera:"),
            st.Page("views/nyumba_kumi.py", title="Nyumba Kumi", icon=":material/groups:"),
        ],
        "Farmer hub": [
            st.Page("views/learn.py", title="Learn", icon=":material/menu_book:"),
            st.Page("views/community.py", title="Community", icon=":material/forum:"),
        ],
        "Account": [account_page],
    }
nav = st.navigation(pages)

with st.sidebar:
    if st.session_state["role"] == "farmer":
        st.caption("Farmers see their own farm and advice an officer has signed. Only the extension officer can "
                   "approve advice.")
    if st.session_state["role"] == "institution":
        st.caption("Institutions see their officers' performance and pay for the service. Officers approve advice.")
    rows = [("Database", health["database"]["ok"]), (f"Local AI · {health['llm_model']}", health["llm_available"]),
            ("Guidance library (MCP)", health["npx_available"])]
    st.markdown('<div class="cp-status"><b>System status</b>' + "".join(
        f'<div><span class="cp-dot {"ok" if ok else "warn"}"></span>{name}</div>' for name, ok in rows)
        + f'<div style="margin-top:6px">Demo date: {health["today"]}</div></div>', unsafe_allow_html=True)
    if cloud.hosted():
        st.caption("Online demo: the local AI models are off on free hosting, so drafts come from the fixed rules "
                   "and photos go to the officer without an AI suggestion. The full version runs on a laptop.")

nav.run()

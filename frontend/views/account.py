"""Sign in, and sign up as a farmer, an extension officer or an institution."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import api_client as api
import auth
import ui

COUNTY_DEFAULT = "Nairobi"
SUB_COUNTY_DEFAULT = "Dagoretti South"
LOCKUP = Path(__file__).resolve().parents[1] / "assets" / "talo-lockup.png"
# Wards we have farm data for, by sub-county (officers can narrow their area to some of them).
WARDS = {"Dagoretti South": ["Riruta", "Waithaka", "Mutuini", "Ngando", "Uthiru"]}
SUB_COUNTIES = {"Nairobi": ["Dagoretti North", "Dagoretti South", "Embakasi Central", "Embakasi East",
                            "Embakasi North", "Embakasi South", "Embakasi West", "Kamukunji", "Kasarani", "Kibra",
                            "Langata", "Makadara", "Mathare", "Roysambu", "Ruaraka", "Starehe", "Westlands"]}
KINDS = {"county_agric_department": "County Agriculture Department", "cooperative": "Cooperative",
         "ngo": "NGO", "other": "Other"}


def _signed_in(u: dict) -> None:
    ui.header("My account", "Your TALO account.")
    with ui.section():
        c = st.columns(3)
        c[0].metric("Name", u["full_name"])
        c[1].metric("Role", auth.ROLE_LABEL[u["role"]] + (" · Lead Farmer" if u.get("is_lead_farmer") else ""))
        c[2].metric("Sub-county", u.get("sub_county") or "—")
        st.caption(f"E-mail: {u['email']}" + (f" · Farm: {u['household_id']}" if u.get("household_id") else "")
                   + (f" · County: {u['county']}" if u.get("county") else ""))
    access = u.get("access")
    if access is not None:
        if access["active"]:
            st.success(f"Your access is paid for by {access['sponsor']}.", icon=":material/verified:")
        else:
            st.warning(f"Your account is ready, but you cannot use TALO yet. {access['reason']} Your county "
                       "agriculture department, cooperative or NGO pays KES 50 a month for each farmer; ask your "
                       "extension officer when your area will be covered.", icon=":material/hourglass_top:")
            if st.button("Check again", icon=":material/refresh:"):
                st.rerun()
    if st.button("Sign out", icon=":material/logout:"):
        auth.sign_out()
        st.rerun()


def _sign_in_form() -> None:
    with st.form("sign-in"):
        email = st.text_input("E-mail")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            try:
                auth.sign_in(api.login(email, password))
                st.rerun()
            except api.ApiError as exc:
                auth.show_error(exc)


def _done(session_or_msg: dict) -> None:
    if "access_token" in session_or_msg:
        auth.sign_in(session_or_msg)
        st.rerun()
    st.success(session_or_msg.get("message", "Account created."), icon=":material/hourglass_top:")


def _password_pair(key: str) -> str | None:
    c = st.columns(2)
    pw = c[0].text_input("Password (10+ characters)", type="password", key=f"{key}-pw")
    pw2 = c[1].text_input("Repeat password", type="password", key=f"{key}-pw2")
    return pw if pw == pw2 else None


def _farmer_form() -> None:
    farms = st.session_state.get("farm_info", {})
    with st.form("farmer-signup"):
        name = st.text_input("Full name", placeholder="Peter Njoroge")
        c = st.columns(2)
        email = c[0].text_input("E-mail")
        phone = c[1].text_input("Phone (optional)", placeholder="0712 345 678")
        farm = st.selectbox("My farm (ask your extension officer for the ID)", [None] + sorted(farms),
                            format_func=lambda h: "Not registered yet" if h is None else ui.farm_label(h))
        c = st.columns(2)
        county = c[0].text_input("County", value=COUNTY_DEFAULT)
        sub_county = c[1].text_input("Sub-county", value=SUB_COUNTY_DEFAULT,
                                     help="Used when your farm is not registered yet")
        pw = _password_pair("farmer")
        if st.form_submit_button("Create farmer account", type="primary", width="stretch"):
            if pw is None:
                st.error("The two passwords do not match.")
                return
            try:
                _done(api.register({"role": "farmer", "email": email, "password": pw, "full_name": name,
                                    "phone": phone or None, "household_id": farm, "county": county,
                                    "sub_county": sub_county}))
            except api.ApiError as exc:
                auth.show_error(exc)


def _officer_form() -> None:
    try:
        insts = api.institutions_public()
    except api.ApiError as exc:
        auth.show_error(exc)
        return
    st.caption("Work on your own: your account is ready as soon as you sign up. If you work with a County Agriculture "
               "Department, cooperative or NGO you can name it, and it will be able to see your work.")

    # Outside the form, so the rest of the form follows the chosen institution and sub-county.
    inst = st.selectbox("Institution (optional)", [None] + insts,
                        format_func=lambda i: "None, I work independently" if i is None
                        else f"{i['name']} · {i['county']} County")
    c = st.columns(2)
    if inst:
        county = inst["county"]
        c[0].text_input("County", value=county, disabled=True, help="Set by the institution you chose")
    else:
        county = c[0].text_input("County", value=COUNTY_DEFAULT)
    options = SUB_COUNTIES.get((county or "").strip().title(), [])
    if options:
        sub_county = c[1].selectbox("Sub-county you work in", options,
                                    index=options.index(SUB_COUNTY_DEFAULT) if SUB_COUNTY_DEFAULT in options else 0,
                                    accept_new_options=True)
    else:
        sub_county = c[1].text_input("Sub-county you work in")
    wards = []
    if WARDS.get(sub_county):
        wards = st.pills("Wards you cover (none selected = the whole sub-county)", WARDS[sub_county],
                         selection_mode="multi") or []

    with st.form("officer-signup"):
        name = st.text_input("Full name", placeholder="Wanjiru Kamau")
        c = st.columns(2)
        email = c[0].text_input("E-mail")
        phone = c[1].text_input("Phone (optional)", placeholder="0712 345 678")
        pw = _password_pair("officer")
        if st.form_submit_button("Create officer account", type="primary", width="stretch"):
            if pw is None:
                st.error("The two passwords do not match.")
                return
            if not (sub_county or "").strip():
                st.error("Choose the sub-county you work in.")
                return
            try:
                _done(api.register({"role": "extension_officer", "email": email, "password": pw, "full_name": name,
                                    "phone": phone or None, "institution_id": inst["id"] if inst else None,
                                    "county": county, "sub_county": sub_county,
                                    "wards": [w.upper() for w in wards] or None}))
            except api.ApiError as exc:
                auth.show_error(exc)


def _institution_form() -> None:
    st.caption("For a County Agriculture Department, cooperative or NGO. You see the work of the extension officers "
               "who name you when they sign up. Institutions are the only ones who pay: KES 50 a month for each farmer you give access to, by M-Pesa or card.")
    with st.form("institution-signup"):
        inst_name = st.text_input("Institution name", placeholder="Nairobi County Agriculture Department")
        c = st.columns(2)
        kind = c[0].selectbox("Type", list(KINDS), format_func=KINDS.get)
        county = c[1].text_input("County", value=COUNTY_DEFAULT)
        name = st.text_input("Your full name (account administrator)")
        c = st.columns(2)
        email = c[0].text_input("E-mail")
        phone = c[1].text_input("Phone (optional)")
        pw = _password_pair("inst")
        if st.form_submit_button("Create institution account", type="primary", width="stretch"):
            if pw is None:
                st.error("The two passwords do not match.")
                return
            try:
                _done(api.register({"role": "institution", "email": email, "password": pw, "full_name": name,
                                    "phone": phone or None, "institution_name": inst_name, "institution_kind": kind,
                                    "county": county}))
            except api.ApiError as exc:
                auth.show_error(exc)


u = auth.user()
if u:
    _signed_in(u)
    st.stop()

_, mid, _ = st.columns([1, 2.2, 1])
with mid:
    st.image(str(LOCKUP), width=230)
    st.markdown("#### Sign in, or create your account")
    st.caption("Farmers, extension officers and institutions each have their own account.")
    tabs = st.tabs(["Sign in", "Farmer", "Extension officer", "Institution"])
    with tabs[0]:
        _sign_in_form()
    with tabs[1]:
        _farmer_form()
    with tabs[2]:
        _officer_form()
    with tabs[3]:
        _institution_form()

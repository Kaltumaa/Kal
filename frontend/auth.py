"""Who is signed in. The JWT and the account live in st.session_state["auth"] for this browser session only."""
from __future__ import annotations

import streamlit as st

import api_client as api

ROLE_LABEL = {"farmer": "Farmer", "extension_officer": "Extension officer", "institution": "Institution"}


def current() -> dict | None:
    return st.session_state.get("auth")


def user() -> dict | None:
    a = current()
    return a["user"] if a else None


def signer_name() -> str:
    """Pre-fills signature boxes: an officer can only sign with their own account name (the API checks it)."""
    u = user()
    return u["full_name"] if u else ""


def token() -> str | None:
    a = current()
    return a["access_token"] if a else None


def sign_in(session: dict) -> None:
    st.session_state["auth"] = {"access_token": session["access_token"], "user": session["user"]}


def sign_out() -> None:
    st.session_state.pop("auth", None)


def refresh() -> None:
    """Re-read the account; an expired or revoked token signs the user out."""
    a = current()
    if not a:
        return
    try:
        a["user"] = api.me(a["access_token"])
    except api.ApiError as exc:
        if exc.status in (401, 403):
            sign_out()


def require(*roles: str) -> dict:
    """Stop the page unless someone with one of these roles is signed in."""
    u = user()
    if u is None:
        st.info("Sign in first (Account page in the sidebar).", icon=":material/login:")
        st.stop()
    if roles and u["role"] not in roles:
        st.warning(f"This page is for {' or '.join(ROLE_LABEL[r].lower() + 's' for r in roles)}.")
        st.stop()
    return u


def show_error(exc: api.ApiError) -> None:
    detail = exc.detail
    if isinstance(detail, list):          # FastAPI validation errors
        detail = "; ".join(f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
    if exc.status == 402:
        st.error(f"{detail} Pay for your farmers (KES 50 each) under **My officers → Farmers & payment**.", icon=":material/credit_card:")
    else:
        st.error(str(detail), icon=":material/error:")

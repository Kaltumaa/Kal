"""Shared look & feel: one small stylesheet plus helpers built on native Streamlit components."""
from __future__ import annotations

import streamlit as st

CSS = """
<style>
.block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}
[data-testid="stSidebar"] {background: #FFFFFF; border-right: 1px solid #E4E9E2;}
h1, h2, h3 {letter-spacing: -0.01em;}
.cp-sub {color: #66756B; margin: -0.6rem 0 1.4rem 0; font-size: 0.95rem;}
.cp-muted {color: #66756B; font-size: 0.85rem;}
.cp-status {font-size: 0.78rem; color: #66756B; line-height: 1.7;}
.cp-dot {display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: 1px;}
.ok {background: #22A06B;} .warn {background: #E2A100;} .bad {background: #D64545;}
.cp-sms {background: #EEF6F0; border-radius: 14px 14px 14px 4px; padding: 12px 14px; font-size: 0.93rem;}
.cp-step {display: flex; gap: 10px; padding: 6px 0; border-bottom: 1px solid #EEF1EC; font-size: 0.85rem;}
.cp-step code {background: none; padding: 0; color: #1B2A21;}
.cp-step .who {color: #66756B; min-width: 110px;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #E4E9E2; border-radius: 12px; padding: 12px 16px;}
</style>
"""

VERDICT_COLOR = {"PLANT": "green", "SPRAY": "orange", "HOLD": "blue"}
STATUS_TEXT = {"PENDING_REVIEW": "Awaiting signature", "SECURITY_LOCK": "Security lock",
               "NEEDS_DATA": "Needs field data", "APPROVED": "Sent", "REJECTED": "Rejected"}
STATUS_COLOR = {"PENDING_REVIEW": "orange", "SECURITY_LOCK": "red", "NEEDS_DATA": "gray", "APPROVED": "green",
                "REJECTED": "gray"}


def setup() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str) -> None:
    st.title(title)
    st.markdown(f'<p class="cp-sub">{subtitle}</p>', unsafe_allow_html=True)


def badges(verdict: str | None, status: str) -> str:
    """Verdict and status as inline markdown badges on one line."""
    return (f":{VERDICT_COLOR.get(verdict, 'gray')}-badge[{verdict or 'No advice'}] "
            f":{STATUS_COLOR.get(status, 'gray')}-badge[{STATUS_TEXT.get(status, status)}]")

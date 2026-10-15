"""Shared look & feel: one small stylesheet plus helpers built on native Streamlit components."""
from __future__ import annotations

import html

import streamlit as st

CSS = """
<style>
.block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}
[data-testid="stSidebar"] {background: #FFFFFF; border-right: 1px solid #E4E9E2;}
h1, h2, h3 {letter-spacing: -0.01em;}
.cp-band {background: linear-gradient(110deg, #134E33 0%, #1F7A4D 60%, #2E8F5C 100%); color: #fff;
  border-radius: 14px; padding: 18px 24px 16px 24px; margin: 0 0 1.2rem 0;}
.cp-band h1 {color: #fff; font-size: 1.65rem; margin: 2px 0 2px 0; padding: 0;}
.cp-band p {color: #DCEFE3; margin: 0; font-size: 0.93rem;}
.cp-band-kicker {color: #A8D8B9; font-size: 0.72rem; letter-spacing: .08em; text-transform: uppercase; font-weight: 600;}
.cp-wards table {width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #E4E9E2; border-radius: 12px;
  overflow: hidden; font-size: 0.92rem;}
.cp-wards th {text-align: left; background: #F1F4EF; color: #4B5B51; font-weight: 600; padding: 10px 14px;
  font-size: 0.78rem; text-transform: uppercase; letter-spacing: .04em;}
.cp-wards td {padding: 12px 14px; border-top: 1px solid #EEF1EC; vertical-align: top;}
.cp-wards td small {display: block; color: #66756B; margin-top: 2px;}
.cp-tag {display: inline-block; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8rem;}
.t-green {background: #DCF5E5; color: #14632F;} .t-orange {background: #FFF1D6; color: #8A5300;}
.t-red {background: #FDE2E2; color: #A12A2A;} .t-gray {background: #EEF1EC; color: #4B5B51;}
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
    """Green header band used on every page."""
    st.markdown(f'<div class="cp-band"><div class="cp-band-kicker">Dagoretti South extension desk · '
                f'Short rains 2026</div><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>',
                unsafe_allow_html=True)


def badges(verdict: str | None, status: str) -> str:
    """Verdict and status as inline markdown badges on one line."""
    return (f":{VERDICT_COLOR.get(verdict, 'gray')}-badge[{verdict or 'No advice'}] "
            f":{STATUS_COLOR.get(status, 'gray')}-badge[{STATUS_TEXT.get(status, status)}]")

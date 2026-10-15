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


# --- Plain-language labels ----------------------------------------------------------------------------------
GUIDE_TITLES = {"pest_action_thresholds.md": "Pest action guide", "pesticides_safety.md": "Pesticide safety guide",
                "crop_calendar_nairobi.md": "Crop calendar guide", "spray_safety_guidelines.md": "Spray safety guide",
                "pests_diseases.md": "Pests & diseases guide", "chirps_dekadal_dagoretti.csv": "Rainfall history (CHIRPS-style)",
                "season_outlook.csv": "Season rainfall outlook"}
STAGES = {"PRE_PLANTING": "Not planted yet", "EMERGENCE": "Just emerged", "EARLY_VEGETATIVE": "Young plants",
          "LATE_VEGETATIVE_TASSELING": "Tall plants / tasseling", "GRAIN_FILL": "Grain filling", "MATURITY": "Maturing",
          "HARVEST_READY": "Ready to harvest", "VEGETATIVE": "Growing leaves", "FLOWERING": "Flowering",
          "POD_FILL": "Pods filling", "ESTABLISHMENT": "Establishing", "CONTINUOUS_HARVEST": "Harvesting leaves",
          "TUBER_INITIATION": "Tubers starting", "TUBER_BULKING": "Tubers growing", "UNKNOWN": "Unknown stage"}
FLAG_TEXT = {
    "auto_filled": "The AI skipped a step, so the system fetched it automatically",
    "corrected_args": "The AI used a wrong value in a step; the system corrected it",
    "model_disagreement": "The AI suggested different advice; the safety rules decided",
    "data_repaired": "Messy farm record was cleaned up",
    "prompt_injection_detected": "Suspicious instructions found in the record and removed",
    "false_start_risk": "Rain follows a dry spell (false-start risk)",
    "rotation_risk": "Same crop family planted again (pest carry-over risk)",
    "self_check_retry": "The self-check found a problem and re-gathered the evidence",
    "self_check_failed": "The self-check failed twice; draft withheld",
    "llm_unavailable_deterministic_gathering": "Local AI was offline; fixed rules were used",
    "weather_forecast_stale": "The rain forecast is out of date",
    "blocked_tool_request": "The AI asked for a tool it is not allowed to use (blocked)",
    "llm_skipped_status_needs_data": "Not enough farm data, so no AI text was written",
    "llm_skipped_status_security_lock": "Record locked, so no AI text was written",
}


def stage_label(stage: str | None) -> str:
    return STAGES.get(stage or "", (stage or "—").replace("_", " ").title())


def source_label(src: str, names: dict | None = None) -> str:
    kind, _, ref = src.partition(":")
    if kind == "plots":
        return f"Farm record ({(names or {}).get(ref, ref)})"
    if kind == "weather_cache":
        zone, _, issued = ref.partition("@")
        return f"Rain forecast for {zone.title()}" + (f" (issued {issued[:10]})" if issued else "")
    if kind == "pest_alerts":
        return f"Confirmed pest report {ref}"
    if kind == "reference":
        return GUIDE_TITLES.get(ref, ref)
    return src


def flag_label(flag: str) -> str:
    return FLAG_TEXT.get(flag.split(":")[0], flag.replace("_", " "))


def names() -> dict:
    return st.session_state.get("farm_names", {})


def farm_label(hid: str | None) -> str:
    if not hid:
        return "—"
    info = st.session_state.get("farm_info", {}).get(hid, {})
    zone = (info.get("zone_id") or "").title()
    return f"{names().get(hid, hid)}" + (f" · {zone}" if zone else "")


# --- Urgency and citations ------------------------------------------------------------------------------------
HARVEST_STAGES = {"MATURITY", "HARVEST_READY", "HARVEST", "POD_FILL_MATURITY", "TUBER_BULKING"}
URGENCY = {"PLANT": ("When to plant: plant now", "green"), "SPRAY": ("When to spray: spray now", "orange"),
           "HOLD": ("When to hold: hold", "blue"), "HARVEST": ("Ready for harvest", "violet")}


def urgency(verdict: str | None, stage: str | None) -> tuple[str, str]:
    """Display state from the verdict plus the crop calendar. Harvest readiness is shown, never decided by the AI."""
    if verdict in (None, "HOLD") and stage in HARVEST_STAGES:
        return URGENCY["HARVEST"]
    return URGENCY.get(verdict or "", ("No advice yet", "gray"))


def suggested_citation(adv: dict, field_log: list[dict] | None = None) -> str:
    """A citation built from the draft's own records, for the officer to check before sending."""
    ev = adv.get("evidence") or {}
    rain, plot, pattern = ev.get("rain") or {}, ev.get("plot") or {}, ev.get("weather_pattern") or {}
    srcs = adv.get("sources") or []
    wx = next((x for x in srcs if x.startswith("weather_cache:")), None)
    pl = next((x for x in srcs if x.startswith("plots:")), None)
    pest = next((x for x in srcs if x.startswith("pest_alerts:")), None)
    parts = []
    if wx:
        parts.append(f"{rain.get('rain_7d_mm', '?')} mm 7-day rain forecast ({wx})")
    if pattern.get("season_anomaly_pct") is not None:
        parts.append(f"season outlook {pattern['season_anomaly_pct']:+d}% vs normal")
    if pl:
        day = plot.get("days_since_planting")
        parts.append(f"plot record {pl} ({plot.get('active_crop') or 'no crop'}"
                     + (f", day {day})" if day is not None else ")"))
    if pest:
        parts.append(f"confirmed pest report {pest}")
    if field_log:
        parts.append(f"plot history entry ID: {field_log[0]['id']}")
    return "Citing " + ", ".join(parts) if parts else ""

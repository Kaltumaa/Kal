"""Shared look & feel: one small stylesheet plus helpers built on native Streamlit components."""
from __future__ import annotations

import html
import re

import streamlit as st

CSS = """
<style>
/* zinc scale, as Tailwind names it. --meta is the one place to change if tiny labels need more contrast. */
:root {--forest: #14532D; --gold: #F2B134; --cream: #F7F1E3; --z900: #18181B; --z600: #52525B; --meta: #71717A; --line: #F4F4F5; --wire: #E4E4E7;}

/* Base: white page, nothing boxed */
.stApp, [data-testid="stHeader"] {background: #FFFFFF !important;}
[data-testid="stSidebar"] {background: var(--forest) !important;}
[data-testid="stMainBlockContainer"] {padding: 4rem 3rem 6rem !important; max-width: 1120px;}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {gap: 3rem;}
/* A heading stays with the text under it */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(h3, h4, h5) {margin-bottom: -2.25rem;}
hr {border: 0 !important; border-top: 1px solid var(--line) !important; margin: 1rem 0 !important;}

/* Type */
.stApp, .stApp p, .stApp li, [data-testid="stMarkdownContainer"] {color: var(--z600); line-height: 1.625;}
.stApp b, .stApp strong {color: var(--z900); font-weight: 600;}
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 {color: var(--z900) !important; font-weight: 600 !important; letter-spacing: -0.025em;}
.stApp h2 {font-size: 1.875rem !important;} .stApp h3 {font-size: 1.5rem !important;}
.stApp h4 {font-size: 1.25rem !important;} .stApp h5 {font-size: 1.125rem !important;}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color: var(--z600) !important; font-size: 0.875rem;}
[data-testid="stWidgetLabel"] p {color: var(--z600) !important; font-size: 0.875rem;}
.cp-muted {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta);}

/* Page header */
.cp-head {padding: 0 0 1.5rem; border-bottom: 1px solid var(--line);}
.cp-head.hero {padding-bottom: 3rem;}
.cp-head .cp-kicker {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--forest);}
.stApp .cp-head h1 {font-size: 1.875rem !important; line-height: 1.15; margin: 0.25rem 0 0.25rem; padding: 0; letter-spacing: -0.025em;}
.cp-head.hero h1::after {content: ""; display: block; width: 72px; height: 4px; background: var(--gold); margin-top: 1.25rem;}
.cp-head p {max-width: 44rem; margin: 0; font-size: 0.9375rem;}
.cp-head.hero p {font-size: 1.0625rem;}
.stApp .cp-head.hero h1 {margin: 0.75rem 0 1rem;}
@media (min-width: 768px) {.stApp .cp-head.hero h1 {font-size: 3rem !important;}}

/* A farmer's latest advice */
.cp-now {background: var(--cream); border-top: 3px solid var(--gold); padding: 1.5rem 1.75rem;}
.cp-now .cp-kicker {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--z600);}
.cp-now .act {font-weight: 600; font-size: 2rem; line-height: 1.2; letter-spacing: -0.025em; margin: 0.35rem 0 0.5rem;}
.cp-now .act.t-gray {color: var(--z900);}
.cp-now p {margin: 0; font-size: 1.125rem; color: var(--z900); max-width: 46rem;}

/* Learn: a plain list of guides */
[class*="st-key-cp-topic"] {border-top: 1px solid var(--line); padding: 0.5rem 0;}
.stApp button[data-testid="stBaseButton-tertiary"] {padding: 0; min-height: 0; justify-content: flex-start;}
.stApp button[data-testid="stBaseButton-tertiary"] p {color: var(--forest); font-weight: 600; font-size: 1rem;}

/* Sections instead of cards: a faint rule and air */
[class*="st-key-cp-section"] {border-top: 1px solid var(--line); padding-top: 2rem;}
[data-testid="stForm"] {border: 0 !important; padding: 0 !important; border-radius: 0;}
[data-testid="stExpander"] details {border: 0 !important; border-top: 1px solid var(--line) !important; border-radius: 0 !important;}
[data-testid="stExpander"] summary {padding-left: 0; padding-right: 0;}
[data-testid="stExpanderDetails"] {padding-left: 0; padding-right: 0;}
[data-testid="stAlertContainer"] {background: transparent !important; border-radius: 0 !important; padding: 0.75rem 0 !important; border-top: 1px solid var(--line);}
[data-testid="stAlertContainer"] p {color: var(--z600) !important;}
[data-testid="stAlertContentWarning"] p, [data-testid="stAlertContentError"] p {color: var(--z900) !important; font-weight: 500;}
[data-testid="stChatMessage"] {background: transparent !important; border-radius: 0; border-top: 1px solid var(--line); padding: 1.25rem 0;}
[data-testid="stMetric"] {background: transparent; border: 0; padding: 0;}
[data-testid="stMetricLabel"] p {font-size: 0.75rem !important; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta) !important;}
[data-testid="stMetricValue"] {font-size: 1.875rem; font-weight: 600; color: var(--z900); letter-spacing: -0.025em;}
[data-testid="stDataFrameResizable"] {border: 0 !important;}
[data-testid="stMetricValue"] * {color: var(--forest) !important;}
[data-testid="stMetricValue"] *, [data-testid="stMetricLabel"] * {white-space: normal !important; overflow: visible !important; text-overflow: clip !important; overflow-wrap: anywhere;}
[data-testid="stMetricValue"] {font-size: 1.5rem; line-height: 1.2;}
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] > [data-testid="stMetric"]) {background: var(--cream); border-top: 3px solid var(--gold); padding: 1.5rem;}
[data-testid="stElementContainer"]:has(.cp-head) + [data-testid="stLayoutWrapper"] > [class*="st-key-cp-section"] {border-top: 0; padding-top: 0;}

/* Forms: wireframe underline only */
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"], [data-testid="stNumberInputContainer"],
[data-testid="stDateInputField"], [data-baseweb="select"] > div, [data-baseweb="base-input"], [data-baseweb="textarea"] {
  background: transparent !important; border: 0 !important; border-radius: 0 !important;}
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"], [data-testid="stNumberInputContainer"],
[data-testid="stDateInputField"], [data-baseweb="select"] > div {border-bottom: 1px solid var(--wire) !important; box-shadow: none !important;}
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stTextAreaRootElement"]:focus-within,
[data-baseweb="select"] > div:focus-within {border-bottom-color: var(--z900) !important;}
.stApp input, .stApp textarea {color: var(--z600) !important; padding-left: 0 !important; background: transparent !important;}
.stApp input::placeholder, .stApp textarea::placeholder {color: var(--meta) !important;}
[data-testid="stSelectbox"] [data-baseweb="select"] div {background: transparent !important;}
[data-testid="stFileUploaderDropzone"], [data-testid="stAudioInput"] {background: transparent !important; border: 0 !important; border-bottom: 1px solid var(--wire) !important; border-radius: 0 !important; padding-left: 0;}

/* Buttons and links */
.stApp button[data-testid^="stBaseButton"] {border-radius: 6px !important; box-shadow: none !important; font-weight: 500;}
.stApp button[data-testid="stBaseButton-secondary"], .stApp button[data-testid="stBaseButton-secondaryFormSubmit"] {background: #FFFFFF; border: 1px solid var(--wire); color: var(--z900);}
.stApp button[data-testid="stBaseButton-primary"], .stApp button[data-testid="stBaseButton-primaryFormSubmit"] {background: var(--forest); border: 1px solid var(--forest); color: #FFFFFF;}
.stApp button[data-testid="stBaseButton-primary"] p, .stApp button[data-testid="stBaseButton-primaryFormSubmit"] p {color: #FFFFFF;}
[data-testid="stPageLink"] a {padding-left: 0; background: transparent !important;}
[data-testid="stPageLink"] p {color: var(--forest); font-weight: 600;}
[data-testid="stPageLink"] [data-testid="stIconMaterial"] {color: var(--forest);}
.stApp [data-testid="stMarkdownContainer"] a {color: var(--forest);}
[data-testid="stAlertContentInfo"] [data-testid="stAlertDynamicIcon"] {color: var(--forest) !important;}

/* Sidebar navigation: bare text, diagonal arrow on the current or hovered page */
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label, [data-testid="stSidebar"] b {color: var(--cream) !important;}
[data-testid="stSidebar"] svg {color: var(--cream); fill: var(--cream);}
[data-testid="stSidebarNavLink"] {background: transparent !important; padding-left: 0.5rem; border-radius: 0; border-left: 3px solid transparent;}
[data-testid="stSidebarNavLink"] [data-testid="stIconMaterial"] {display: none;}
[data-testid="stSidebarNavLink"] span {opacity: 0.85;}
[data-testid="stSidebarNavLink"][aria-current="page"] {border-left-color: var(--gold);}
[data-testid="stSidebarNavLink"][aria-current="page"] span, [data-testid="stSidebarNavLink"]:hover span {opacity: 1; font-weight: 600;}
[data-testid="stSidebarNavLink"][aria-current="page"]::after, [data-testid="stSidebarNavLink"]:hover::after {content: "↗"; margin-left: 0.4rem; color: var(--gold);}
[data-testid="stNavSectionHeader"] span {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--gold) !important;}
[data-testid="stSidebar"] [data-baseweb="select"] div, [data-testid="stSidebar"] input {color: var(--cream) !important; -webkit-text-fill-color: var(--cream);}
[data-testid="stSidebar"] [data-baseweb="select"] > div {border-bottom-color: rgba(247, 241, 227, 0.4) !important;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color: var(--cream) !important; opacity: 0.8;}
[data-testid="stSidebar"] hr {border-top-color: rgba(247, 241, 227, 0.2) !important;}
[data-testid="stSidebar"] .cp-status, [data-testid="stSidebar"] .cp-status b {color: var(--cream); opacity: 0.85;}
[data-testid="stSidebar"] .cp-dot.ok {background: var(--cream);} [data-testid="stSidebar"] .cp-dot.warn {background: var(--gold);}

/* Tags: tiny text with a dot. Status colours stay, because they carry safety meaning. */
.stMarkdownBadge {background: transparent !important; padding: 0 !important; white-space: normal !important; overflow: visible !important; max-width: none !important; font-size: 0.75rem !important; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;}
.stMarkdownBadge::before {content: "•"; margin-right: 0.35rem;}
.cp-tag {display: inline-block; font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;}
.cp-tag::before {content: "•"; margin-right: 0.35rem;}
.t-green {color: #15803D;} .t-orange {color: #B45309;} .t-red {color: #B91C1C;} .t-gray {color: #71717A;}
.cp-chip {display: inline-block; margin: 0 0.9rem 0 0; font-size: 0.875rem; color: var(--z600);}
.cp-chip.red {color: #B91C1C;} .cp-chip.ok {color: #15803D;} .cp-chip.gray {color: var(--meta);}

/* Ward-by-ward, crops, seasons, log: bare columns */
.cp-wards table {width: 100%; border-collapse: collapse; font-size: 0.9375rem;}
.cp-wards th {text-align: left; font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta); padding: 0.75rem 1rem 0.75rem 0;}
.cp-wards td {padding: 1rem 1rem 1rem 0; border-top: 1px solid var(--line); vertical-align: top;}
.cp-wards td small {display: block; color: var(--meta); margin-top: 2px;}
.cp-wgrid {display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 3rem;}
.cp-ward {display: flex; flex-direction: column; gap: 1rem; border-top: 1px solid var(--line); padding-top: 1.5rem;}
.cp-ward .wn {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta);}
.cp-ward .act {font-weight: 600; font-size: 1.625rem; line-height: 1.2; letter-spacing: -0.025em; margin-top: -0.5rem;}
.cp-ward .act.t-gray {color: var(--z900);}
.cp-ward .cp-row .cp-tag {font-size: 0.9375rem; font-weight: 600; text-transform: none; letter-spacing: 0;}
.cp-ward .why {color: var(--z600); font-size: 0.9375rem; line-height: 1.625;}
.cp-stats {display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem;}
.cp-stat {min-width: 0;}
.cp-stat b {display: block; font-size: 1.125rem; font-weight: 600; color: var(--z900); white-space: nowrap;}
.cp-stat span {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta);}
.cp-row {font-size: 0.875rem; color: var(--z600); line-height: 1.625;}
.cp-row .lbl {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta); margin-right: 0.75rem; display: inline-block; min-width: 72px;}
.cp-legend {display: flex; gap: 2rem; flex-wrap: wrap; font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta); padding: 1rem 0 0;}
.cp-legend i {display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 0.5rem;}
.cp-callout {padding: 1rem 0; border-top: 1px solid var(--line); font-size: 0.9375rem; color: var(--z600); line-height: 1.625;}
.cp-callout.warn {color: var(--z900);}
.cp-crops {display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 3rem;}
.cp-cropcard {display: flex; flex-direction: column; gap: 0.5rem; border-top: 1px solid var(--line); padding-top: 1.5rem;}
.cp-cropcard .cn {font-weight: 600; font-size: 1.25rem; letter-spacing: -0.025em; color: var(--z900);}
.cp-cropcard .meta {font-size: 0.875rem; color: var(--z600);}
.cp-prog {height: 4px; background: var(--line); overflow: hidden;}
.cp-prog span {display: block; height: 100%; background: var(--gold);}
.cp-seasons {display: flex; align-items: baseline; gap: 1.25rem; flex-wrap: wrap;}
.cp-season small {display: block; font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta);}
.cp-season b {font-size: 0.9375rem; font-weight: 500; color: var(--z600);}
.cp-season.now b {color: var(--z900); font-weight: 600;}
.cp-arrow {color: var(--meta);}
.cp-entry {padding: 1rem 0; border-top: 1px solid var(--line);}
.cp-entry .t {font-weight: 600; color: var(--z900); font-size: 0.9375rem;}
.cp-entry .d {font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta);}
.cp-entry .x {color: var(--z600); font-size: 0.9375rem; margin-top: 0.25rem;}
.cp-status {font-size: 0.75rem; color: var(--meta); line-height: 1.9;}
.cp-status b {font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta);}
.cp-dot {display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 0.5rem; vertical-align: 1px;}
.cp-dot.ok {background: #15803D;} .cp-dot.warn {background: #B45309;} .cp-dot.bad {background: #B91C1C;}
.cp-sms {padding: 1rem 0; border-top: 1px solid var(--line); font-size: 0.9375rem;}
.cp-step {display: flex; gap: 1rem; padding: 0.75rem 0; border-top: 1px solid var(--line); font-size: 0.875rem;}
.cp-step code {background: none; padding: 0; color: var(--z900);}
.cp-step .who {color: var(--meta); min-width: 110px;}

/* Tech row */
.cp-partners {display: flex; flex-wrap: wrap; gap: 1rem 3rem; padding: 1.5rem 0; border-top: 1px solid var(--line); margin-top: 3rem;
  font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; color: var(--meta);}
</style>
"""

VERDICT_COLOR = {"PLANT": "green", "SPRAY": "orange", "HOLD": "orange"}
STATUS_TEXT = {"PENDING_REVIEW": "Awaiting signature", "SECURITY_LOCK": "Security lock",
               "NEEDS_DATA": "Needs field data", "APPROVED": "Sent", "REJECTED": "Rejected"}
STATUS_COLOR = {"PENDING_REVIEW": "orange", "SECURITY_LOCK": "red", "NEEDS_DATA": "gray", "APPROVED": "green",
                "REJECTED": "gray"}


def setup() -> None:
    st.session_state["_cp_sections"] = 0
    st.markdown(CSS, unsafe_allow_html=True)


def section(parent=None):
    """A block of related content: no box, just a faint rule above it (replaces a bordered container)."""
    st.session_state["_cp_sections"] = st.session_state.get("_cp_sections", 0) + 1
    return (parent or st).container(key=f"cp-section-{st.session_state['_cp_sections']}")


def partners() -> None:
    """What the system runs on, as one flat row."""
    items = ["Qwen 2.5", "Moondream 2", "Whisper", "Ollama", "LangGraph", "MCP", "FastAPI", "SQLite", "Streamlit"]
    st.markdown('<div class="cp-partners">' + "".join(f"<span>{i}</span>" for i in items) + "</div>",
                unsafe_allow_html=True)


def header(title: str, subtitle: str, hero: bool = False) -> None:
    """Page header. Only landing pages get the large version, so working pages start with the work."""
    kicker = ("Mkulima Hub" if st.session_state.get("role") == "farmer"
              else "Dagoretti South extension desk · Short rains 2026")
    st.markdown(f'<div class="cp-head{" hero" if hero else ""}"><div class="cp-kicker">{kicker}</div>'
                f'<h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>', unsafe_allow_html=True)


def show_rationale(text: str | None) -> None:
    """A draft's reasoning in parts: the decision, why, plot history, the season, and the AI's own words folded away."""
    parts = re.split(r"\s(?=Plot history |Weather pattern: |Model: |Self-check problems: )", (text or "").strip())
    head, _, why = parts[0].partition(". ")
    if why and head.split(":")[0] in ("PLANT", "SPRAY", "HOLD"):
        st.markdown(f"#### {head}")
    else:
        why = parts[0]
    if why:
        st.markdown(why)
    for part in parts[1:]:
        if part.startswith("Plot history "):
            st.markdown(f"**Plot history.** {part[len('Plot history '):]}")
        elif part.startswith("Weather pattern: "):
            st.markdown(f"**This season.** {part[len('Weather pattern: '):]}")
        elif part.startswith("Model: "):
            with st.expander("The AI's explanation (not checked by the rules)"):
                st.markdown(part[len("Model: "):])
        else:
            st.warning(part)


def latest_advice(advisories: list[dict]) -> None:
    """The first thing a farmer sees: their officer's latest signed advice. Never a draft."""
    sent = [a for a in advisories if a["status"] == "APPROVED"]
    if not sent:
        st.markdown('<div class="cp-now"><div class="cp-kicker">This week</div><div class="act">No advice yet</div>'
                    '<p>When your extension officer signs advice for your farm, it appears here and comes by SMS.</p>'
                    '</div>', unsafe_allow_html=True)
        return
    a = max(sent, key=lambda x: x.get("reviewed_at") or "")
    word, color = {"PLANT": ("Plant now", "green"), "SPRAY": ("Scout, then spray", "orange"),
                   "HOLD": ("Wait for now", "orange")}.get(a["verdict"], ("Advice", "gray"))
    langs = (a.get("sent_languages") or "en").split(",")
    message = a["farmer_message"] if "en" in langs or not a.get("farmer_message_sw") else a["farmer_message_sw"]
    st.markdown(f'<div class="cp-now"><div class="cp-kicker">From {html.escape(a["officer_signature"] or "your officer")}'
                f' · {html.escape((a.get("reviewed_at") or "")[:10])}</div>'
                f'<div class="act t-{color}">{word}</div><p>{html.escape(message or "")}</p></div>',
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
    "sw_template": "Kiswahili message uses fixed template wording",
    "sw_model_translation": "Kiswahili message translated by the local model",
    "sw_translation_failed": "The local model could not translate to Kiswahili; template used",
    "sw_translation_rejected": "The model's Kiswahili changed a number or name; template used",
}


SPRAY_COLOUR = {"NO_RAIN": "red", "RAIN_SOON": "orange", "NO_WIND": "orange", "CAREFUL": "orange", "OK": "green"}
OLD_SPRAY_LABEL = {"UNSAFE": ("Don't spray (rain)", "red"), "CAUTION": ("Careful: only if no rain for 6 h", "orange"),
                   "SAFE": ("OK", "green")}


def voice_note(key: str) -> dict | None:
    """A record button: the farmer picks the language they will speak, records, and gets text to check.
    Returns the transcription (text, suggested_action) once, or None."""
    import base64

    import api_client as api
    with st.expander("Record a voice note instead of typing", expanded=False):
        try:
            status = api.speech_status()
        except api.ApiError:
            status = {"available": False}
        if not status.get("available"):
            st.caption("Voice notes need the speech model on this computer. Type your note below instead.")
            return None
        c = st.columns([1, 2], vertical_alignment="bottom")
        lang = c[0].selectbox("I will speak in", ["sw", "en", "auto"], key=f"{key}-lang",
                              format_func={"sw": "Kiswahili", "en": "English", "auto": "Let the app detect"}.get)
        audio = c[1].audio_input("Record", key=f"{key}-audio")
        st.caption("The recording is turned into text on this computer and nothing is saved until you press Save. "
                   "Sheng and other local languages are not supported yet. The first recording takes longer while "
                   "the speech model loads.")
        if audio is not None and st.button("Turn my voice into text", key=f"{key}-go", icon=":material/subtitles:"):
            with st.spinner("Listening…"):
                try:
                    r = api.transcribe(base64.b64encode(audio.getvalue()).decode(), None if lang == "auto" else lang)
                except api.ApiError as exc:
                    st.error(str(exc.detail))
                    return None
            if r.get("flagged") or not r.get("text"):
                st.warning("No usable text came out of that recording. Try again closer to the phone, or type it.")
                return None
            st.success(f"Heard: “{r['text']}”. Check it in the box below and edit it before saving.")
            return r
    return None


def language_defaults(plot: dict) -> tuple[bool, bool, str]:
    """(send English, send Kiswahili, caption) from the farmer's preferred language and when they last used the app."""
    pref = plot.get("language") or "en"
    seen = plot.get("farmer_last_seen")
    words = {"en": "English", "sw": "Kiswahili", "both": "English and Kiswahili"}[pref]
    app = f"last opened the app {seen[:10]}" if seen else "has not opened the app"
    return (pref in ("en", "both"), pref in ("sw", "both"),
            f"Farmer prefers **{words}** and {app}. The message goes by SMS either way (no internet needed).")


def spray_status(z: dict) -> tuple[str, str]:
    """(label, colour) for 'can you spray?'. The backend decides it (rainfall_outlook); this only picks a colour.
    Drafts saved before the backend sent a status fall back to the rain band alone."""
    if z.get("spray_label"):
        return z["spray_label"], SPRAY_COLOUR.get(z.get("spray_status"), "orange")
    return OLD_SPRAY_LABEL.get(z.get("spray_band"), ("—", "orange"))


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
           "HOLD": ("When to hold: hold", "orange"), "HARVEST": ("Ready for harvest", "green")}


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


def search_markdown(md: str, query: str) -> str | None:
    """The parts of a guide that mention the search words: matching sections, and only the matching rows of a
    table (with its header). None if nothing matches."""
    words = [w for w in query.lower().split() if w]
    hit = lambda text: all(w in text.lower() for w in words)              # noqa: E731
    sections, cur = [], []
    for line in md.splitlines():
        if line.startswith("#") and cur:
            sections.append(cur)
            cur = []
        cur.append(line)
    sections.append(cur)
    out = []
    for sec in sections:
        if not hit("\n".join(sec)):
            continue
        head = [l for l in sec if l.startswith("#")]
        table = [l for l in sec if l.lstrip().startswith("|")]
        rows = [l for l in table[2:] if hit(l)]
        if table and rows and not hit("\n".join(l for l in sec if l not in table)):
            out.append("\n".join(head + [""] + table[:2] + rows))       # just the matching table rows
        else:
            out.append("\n".join(sec))
    return "\n\n".join(out) if out else None

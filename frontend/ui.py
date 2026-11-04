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
.cp-wgrid {display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 14px; margin: 4px 0 8px;}
.cp-ward {background: #fff; border: 1px solid #E4E9E2; border-top: 4px solid var(--accent, #1F7A4D);
          border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px;}
.cp-ward .wh {display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;}
.cp-ward .wn {font-weight: 800; font-size: 1.08rem; color: #1B2A21;}
.cp-ward .why {color: #4B5B51; font-size: 0.85rem; line-height: 1.45;}
.cp-stats {display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;}
.cp-stat {background: #F6F8F5; border-radius: 10px; padding: 7px 10px; min-width: 0;}
.cp-stat b {display: block; font-size: 1.02rem; color: #1B2A21; white-space: nowrap;}
.cp-stat span {font-size: 0.68rem; color: #66756B; text-transform: uppercase; letter-spacing: .04em; font-weight: 600;}
.cp-row {font-size: 0.83rem; color: #33443A; line-height: 1.6;}
.cp-row .lbl {color: #66756B; font-weight: 600; margin-right: 6px; display: inline-block; min-width: 64px;}
.cp-chip {display: inline-block; background: #EEF4EF; color: #1F5B3B; border-radius: 999px; padding: 1px 9px;
          margin: 2px 4px 2px 0; font-size: 0.77rem; font-weight: 600;}
.cp-chip.red {background: #FDE2E2; color: #A12A2A;} .cp-chip.ok {background: #DCF5E5; color: #14632F;}
.cp-chip.gray {background: #EEF1EC; color: #66756B;}
.cp-legend {display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.8rem; color: #4B5B51; margin: 6px 0 2px;}
.cp-legend i {display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 6px; vertical-align: -1px;}
.cp-callout {background: #F3F8F4; border-left: 4px solid #1F7A4D; border-radius: 8px; padding: 10px 14px;
             font-size: 0.86rem; color: #2B3B31; margin: 6px 0;}
.cp-callout.warn {background: #FFF6E6; border-left-color: #D98E04;}
.cp-crops {display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin: 4px 0 8px;}
.cp-cropcard {background: #fff; border: 1px solid #E4E9E2; border-radius: 14px; padding: 12px 14px;
              display: flex; flex-direction: column; gap: 6px;}
.cp-cropcard .cn {font-weight: 800; font-size: 1rem; color: #1B2A21;}
.cp-cropcard .meta {font-size: 0.8rem; color: #66756B;}
.cp-prog {height: 7px; background: #EEF1EC; border-radius: 99px; overflow: hidden;}
.cp-prog span {display: block; height: 100%; background: #1F7A4D; border-radius: 99px;}
.cp-seasons {display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 4px 0 6px;}
.cp-season {background: #fff; border: 1px solid #E4E9E2; border-radius: 12px; padding: 6px 12px; text-align: center;}
.cp-season.now {border-color: #1F7A4D; background: #EEF6F0;}
.cp-season small {display: block; font-size: 0.68rem; color: #66756B; text-transform: uppercase; letter-spacing: .04em;}
.cp-season b {font-size: 0.88rem; color: #1B2A21;}
.cp-arrow {color: #A3B1A7; font-size: 1.1rem;}
.cp-log {border-left: 2px solid #DDE6DF; margin-left: 8px; padding-left: 0;}
.cp-entry {position: relative; padding: 2px 0 12px 22px;}
.cp-entry::before {content: ""; position: absolute; left: -7px; top: 6px; width: 12px; height: 12px; border-radius: 50%;
                   background: var(--dot, #1F7A4D); border: 2px solid #fff; box-shadow: 0 0 0 1px #DDE6DF;}
.cp-entry .t {font-weight: 700; color: #1B2A21; font-size: 0.9rem;}
.cp-entry .d {color: #66756B; font-size: 0.78rem;}
.cp-entry .x {color: #33443A; font-size: 0.85rem; margin-top: 2px;}
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
    st.markdown(f'<div class="cp-band"><div class="cp-band-kicker">Mkulima Hub · Dagoretti South extension desk · '
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
    with st.expander("🎙️ Record a voice note instead of typing", expanded=False):
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

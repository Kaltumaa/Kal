"""Plot history: what is growing now (every crop, each from its own planting date), past seasons, rotation risk and
the field log. Farmers add entries (and finished reminders); the officer view is read-only."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

import api_client as api
import ui

ACTION_LABEL = {"PLANTING": "Planting", "WEEDING": "Weeding", "SPRAYING": "Spraying", "FERTILISER": "Fertiliser",
                "IRRIGATION": "Watering", "HARVEST": "Harvest", "OBSERVATION": "Observation", "VARIETY": "Seed / variety"}
DOT = {"PLANTING": "#1F7A4D", "WEEDING": "#5E9E3A", "SPRAYING": "#C0392B", "FERTILISER": "#7A5AF8",
       "IRRIGATION": "#2E86C1", "HARVEST": "#D98E04", "OBSERVATION": "#66756B", "VARIETY": "#8A5A2B"}
SEED_LABEL = {"VERIFIED": "Verified with KEPHIS", "FAILED": "Did not verify", "NOT_CHECKED": "Not checked"}
CROPS = ["Maize", "Beans", "Kale", "Potato", "Tomato", "Sorghum", "Cowpeas", "Sweet Potato", "Groundnut"]
RISK = {"HIGH": ("High rotation risk", "red"), "ELEVATED": ("Rotation risk", "orange"), "LOW": ("Good rotation", "green")}

role, mine = st.session_state.get("role", "officer"), st.session_state.get("my_farm")
ui.header("Plot history", "What is growing on this plot, what grew before, and everything done on it. Past seasons "
                          "shape the advice (crop rotation, planting dates, crop stage).")
if role == "farmer" and mine:
    hid = mine
else:
    hid = st.selectbox("Farm", list(ui.names()), format_func=ui.farm_label)

profile = api.household_profile(hid)
plot, rot = profile["plot"], profile["rotation"]
growing = profile.get("growing") or []
calendars = profile.get("calendars") or {}
log = api.farm_actions(hid)
esc = html.escape


def chip(text: str, cls: str = "") -> str:
    return f'<span class="cp-chip {cls}">{esc(text)}</span>'


def crop_card(g: dict) -> str:
    """One growing crop: role on the plot, planting date, stage today, and how far through its cycle it is."""
    stages = (calendars.get(g["crop"]) or {}).get("stages") or []
    cycle = stages[-1]["start_day"] if stages else None            # day it reaches its last stage (harvest)
    days = g["days"]
    if g.get("harvested"):
        status, pct, nxt = f"Harvested {g['harvested']}", 100, ""
    elif days is None:
        status, pct, nxt = "Not planted yet", 0, "Waiting for the planting window"
    else:
        status = f"Day {days} · {ui.stage_label(g['stage'])}"
        pct = min(100, round(100 * days / cycle)) if cycle else 0
        up = next((s for s in stages if s["start_day"] > days), None)
        nxt = (f"Next: {ui.stage_label(up['stage']).lower()} in {up['start_day'] - days} days" if up
               else "Ready to harvest")
    role_chip = chip("Main crop", "ok") if g["main"] else chip("Grown with it")
    planted = f"Planted {g['planted']}" if g.get("planted") else "No planting date yet"
    return (f'<div class="cp-cropcard"><div style="display:flex;justify-content:space-between;align-items:center">'
            f'<span class="cn">{esc(g["crop"])}</span>{role_chip}</div>'
            f'<div class="meta">{esc(planted)}</div><div style="font-weight:600;color:#1B2A21;font-size:.88rem">'
            f'{esc(status)}</div><div class="cp-prog"><span style="width:{pct}%"></span></div>'
            f'<div class="meta">{esc(nxt)}</div></div>')


def entry(a: dict) -> str:
    extra = [x for x in (
        f"Product group: {a['chem_group']}" if a.get("chem_group") else "",
        {1: "Needs weeding before planting", 0: "No weeding needed"}.get(a.get("needs_weeding"), ""),
        {1: "Soil moist to a hand's depth", 0: "Soil not moist yet"}.get(a.get("soil_moist"), ""),
        f"Seed label: {SEED_LABEL[a['seed_check']]}" if a.get("seed_check") in SEED_LABEL else "") if x]
    what = ACTION_LABEL.get(a["action"], a["action"].title()) + (f" · {a['crop']}" if a.get("crop") else "")
    who = f"{a['entered_by']} ({'farmer' if a['entered_by_role'] == 'farmer' else 'officer'})"
    body = esc(a.get("details") or "")
    if extra:
        body += ("<br>" if body else "") + " · ".join(esc(x) for x in extra)
    return (f'<div class="cp-entry" style="--dot:{DOT.get(a["action"], "#66756B")}">'
            f'<div class="t">{esc(what)}</div>'
            f'<div class="d">{esc(a["action_date"])} · {esc(who)}</div>'
            + (f'<div class="x">{body}</div>' if body else "") + "</div>")


# --- Farm summary strip ---------------------------------------------------------------------------------------
terrain = " · ".join(x for x in ((plot.get("slope") or "").capitalize() + (" slope" if plot.get("slope") else ""),
                                 (plot.get("soil") or "").capitalize()) if x.strip()) or "Terrain not recorded"
risk_text, risk_cls = RISK.get(rot.get("risk"), ("Rotation unknown", "gray"))
st.markdown(f'<div class="cp-seasons" style="margin-bottom:10px">{chip(ui.farm_label(hid), "ok")}'
            f'{chip(terrain)}{chip(risk_text, {"red": "red", "orange": "red", "green": "ok"}.get(risk_cls, "gray"))}'
            f'{chip(str(len(log)) + " field-log entries")}</div>', unsafe_allow_html=True)

left, right = st.columns([1.45, 1], gap="large")
with left:
    # --- Growing now ------------------------------------------------------------------------------------------
    st.subheader("Growing now")
    if growing:
        st.markdown('<div class="cp-crops">' + "".join(crop_card(g) for g in growing) + "</div>", unsafe_allow_html=True)
    else:
        st.info("No crop recorded yet. Log a planting to start this plot's history.", icon=":material/potted_plant:")

    # --- Seasons ----------------------------------------------------------------------------------------------
    st.subheader("Seasons on this plot")
    past = plot.get("seasons") or [[c] for c in plot.get("crop_history") or []]
    now = [g["crop"] for g in growing if not g.get("harvested")]
    cells = [(f"{len(past) - i} season{'s' if len(past) - i > 1 else ''} ago", " + ".join(s), False)
             for i, s in enumerate(past)] + [("This season", " + ".join(now) or "Nothing yet", True)]
    st.markdown('<div class="cp-seasons">' + '<span class="cp-arrow">→</span>'.join(
        f'<div class="cp-season{" now" if cur else ""}"><small>{esc(lbl)}</small><b>{esc(crops)}</b></div>'
        for lbl, crops, cur in cells) + "</div>", unsafe_allow_html=True)
    if rot.get("note"):
        st.markdown(f'<div class="cp-callout{" warn" if risk_cls in ("red", "orange") else ""}">'
                    f'<b>{esc(risk_text)}.</b> {esc(rot["note"])}'
                    + (f'<br>Tip: {esc(rot["sms_tip"])}' if rot.get("sms_tip") else "") + "</div>",
                    unsafe_allow_html=True)
    st.caption("A season with \"+\" grew several crops together. Rotation is judged on the main crop of each season.")

    # --- Field log --------------------------------------------------------------------------------------------
    st.subheader("Field log")
    if not log:
        st.caption("Nothing logged yet for this plot.")
    else:
        crops_logged = sorted({a["crop"] for a in log if a.get("crop")})
        show = st.segmented_control("Show", ["All crops"] + crops_logged, default="All crops",
                                    label_visibility="collapsed", key=f"logfilter-{hid}") or "All crops"
        rows = [a for a in log if show == "All crops" or a.get("crop") == show]
        st.markdown('<div class="cp-log">' + "".join(entry(a) for a in rows[:12]) + "</div>", unsafe_allow_html=True)
        if len(rows) > 12:
            with st.expander(f"All {len(rows)} entries as a table"):
                st.dataframe(pd.DataFrame([{
                    "Date": a["action_date"], "What": ACTION_LABEL.get(a["action"], a["action"]),
                    "Crop": a["crop"] or "", "Details": a["details"] or "",
                    "Entered by": a["entered_by"]} for a in rows]), hide_index=True, width="stretch")

with right:
    if role == "farmer":
        with ui.section():
            st.markdown("#### Add to my plot history")
            voice = ui.voice_note("log-voice")
            if voice:
                st.session_state["log-details"] = voice["text"]
                if voice.get("suggested_action") in ACTION_LABEL:
                    st.session_state["log-act"] = voice["suggested_action"]
            st.session_state.setdefault("log-act", "WEEDING")
            action = st.pills("What did you do?", list(ACTION_LABEL), key="log-act",
                              format_func=lambda k: ACTION_LABEL[k]) or "WEEDING"
            with st.form("log-action", clear_on_submit=True, border=False):
                when = st.date_input("When", value=pd.Timestamp(st.session_state.get("demo_today",
                                                                                    "2026-10-15")).date())
                mine_now = [g["crop"] for g in growing if g["crop"] in CROPS and not g.get("harvested")]
                crops = st.multiselect("For which crop(s)?", CROPS, default=mine_now[:1],
                                         help="Pick every crop it was for, e.g. weeding both the maize and the beans. "
                                              "Each crop gets its own entry.")
                with_main, group, weeding, moist, seed = False, "—", "—", "—", "—"
                if action == "PLANTING":
                    with_main = st.checkbox("Planted alongside my main crop (grown together)",
                                            help="E.g. beans between maize rows: your main crop stays as it is. "
                                                 "Without this, the first crop picked becomes the main crop.")
                if action in ("PLANTING", "VARIETY"):
                    seed = st.selectbox("Seed label check", ["—"] + list(SEED_LABEL),
                                        format_func=lambda k: SEED_LABEL.get(k, k),
                                        help="Scratch the KEPHIS label on the seed packet and SMS the code to the "
                                             "number on it (1393 on most labels). The reply should name the variety, "
                                             "producer and lot. No reply or wrong details: choose 'Did not verify'.")
                if action == "SPRAYING":
                    group = st.selectbox("Product group (on the label)", ["—"] + api.spray_groups(),
                                         help="Spraying the same group again and again lets pests become resistant. "
                                              "Your next spray advice will suggest a different group.")
                if action == "OBSERVATION":
                    o = st.columns(2)
                    weeding = o[0].selectbox("Needs weeding before planting?", ["—", "Yes", "No"],
                                             help="If yes, planting advice waits until you log a weeding.")
                    moist = o[1].selectbox("Soil moist to a hand's depth (15 cm)?", ["—", "Yes", "No"],
                                           help="Dig with your hand or a stick. If it is dry below the top, planting "
                                                "advice waits until it is moist that deep.")
                details = st.text_input("Details", max_chars=300, key="log-details",
                                        placeholder="e.g. east side, 50 kg CAN top-dress, 2 h drip irrigation")
                if st.form_submit_button(f"Save {ACTION_LABEL[action].lower()}", type="primary",
                                         width="stretch"):
                    try:
                        updated = False
                        for n, crop in enumerate(crops or [None]):
                            r = api.log_farm_action(hid, action, when.isoformat(), crop, details, "farmer", None,
                                                    None if group == "—" else group,
                                                    None if weeding == "—" else weeding == "Yes",
                                                    None if moist == "—" else moist == "Yes",
                                                    None if seed == "—" else seed,
                                                    action == "PLANTING" and (with_main or n > 0))
                            updated = updated or r["updated_record"]
                        st.toast(f"Saved{' for ' + ', '.join(crops) if crops else ''}."
                                 + (" Your crops and planting dates are updated, so the next advice uses them."
                                    if updated else ""), icon=":material/check:")
                        st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
        st.caption("Saved as reported by you (farmer). Planting updates your farm record, so your officer's next "
                   "advice uses it. Ticking a reminder done in **Reminders** adds an entry too. No internet? Text "
                   "`LOG WEEDING ...` (see Notifications).")
    else:
        with ui.section():
            st.caption("Farmers add to this log from the app, by voice note or by SMS. It is read-only for the officer.")

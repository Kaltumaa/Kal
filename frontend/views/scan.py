"""Field scan: a photo of a crop is checked by a LOCAL vision model and matched against the pest knowledge base.

The result is only an UNVERIFIED report. A named officer must confirm it before it becomes a pest signal
that the advisory agent will use.
"""
from __future__ import annotations

import base64

import pandas as pd
import streamlit as st

import api_client as api
import ui

def ai_label(candidates: list[dict]) -> str:
    """The model's output, always shown as an unverified suggestion."""
    if not candidates:
        return "AI Analysis: no clear match to a known pest — ⏳ AWAITING EXTENSION OFFICER CONFIRMATION"
    top = candidates[0]
    low = " Low match: look closely at the photo before confirming." if top["score"] < 0.5 else ""
    return (f"AI Analysis: Consistent with **{top['pest']}** ({top['score'] * 100:.0f}% symptom-match score) "
            f"— ⏳ AWAITING EXTENSION OFFICER CONFIRMATION.{low}")


CROPS = ["From household record", "Maize", "Beans", "Kale", "Potato", "Tomato"]

ui.header("Field scan" if st.session_state.get("role", "officer") == "officer" else "Report a sick plant",
          "Photograph a sick plant. A local model describes it, the pest guide suggests causes, and an "
                        "officer confirms before it counts as a pest alert.")
role, mine = st.session_state.get("role", "officer"), st.session_state.get("my_farm")
officer = role == "officer"
if officer:
    t_new, t_check = st.tabs(["New photo", "Officer check"])
else:
    t_new, t_check = st.container(), None

with t_new:
    left, right = st.columns([1, 1], gap="large")
    with left:
        source = st.segmented_control("Source", ["Camera", "Upload"], default="Camera", label_visibility="collapsed")
        photo = (st.camera_input("Photo", label_visibility="collapsed") if source == "Camera"
                 else st.file_uploader("Photo (JPEG or PNG, max 6 MB)", type=["jpg", "jpeg", "png"]))
        c = st.columns(2)
        if officer:
            hid = c[0].selectbox("Farm", ["None"] + list(ui.names()),
                                 format_func=lambda h: "No farm" if h == "None" else ui.farm_label(h))
        else:
            hid = mine
            c[0].text_input("Farm", ui.farm_label(mine), disabled=True)
        crop = c[1].selectbox("Crop", CROPS)
        if st.button("Check photo", type="primary", disabled=photo is None, width="stretch"):
            with st.spinner("The local model is looking at the photo… (20–90 s)"):
                try:
                    st.session_state["last_scan"] = api.create_scan(
                        base64.b64encode(photo.getvalue()).decode(), None if hid == "None" else hid,
                        None if crop == CROPS[0] else crop)
                except api.ApiError as exc:
                    st.error(str(exc.detail))
    with right:
        res = st.session_state.get("last_scan")
        if not res:
            st.caption("Results appear here. Photos stay on this computer.")
        else:
            st.markdown(f"**Photo #{res['scan_id']}** · {ui.farm_label(res['household_id']) if res['household_id'] else 'no farm'} · "
                        f"{res['crop'] or 'crop unknown'}")
            if not res["vision_available"]:
                st.warning("The vision model is offline, so the photo was saved for the officer to check by eye.")
            st.write(res["description"] or "—")
            st.warning(ai_label(res["candidates"]), icon=":material/hourglass_top:")
            if res["candidates"]:
                st.markdown("**Possible causes**")
                st.dataframe(pd.DataFrame([{"Cause": x["pest"], "Match": x["score"], "Signs seen": ", ".join(x["matched"])}
                                           for x in res["candidates"]]), hide_index=True, width="stretch",
                             column_config={"Match": st.column_config.ProgressColumn("Match", min_value=0, max_value=1)})
            else:
                st.caption("No clear match. See Learn → Pests & diseases.")
            st.caption("Not a diagnosis. It waits in Officer check until a named officer confirms it.")

if t_check is None:
    st.stop()
with t_check:
    pending = [s for s in api.scans() if s["status"] == "UNVERIFIED"]
    if not pending:
        st.caption("No photos waiting.")
    for s in pending:
        with st.container(border=True):
            img_col, body = st.columns([1, 2.3], gap="medium")
            img = api.scan_image(s["id"])
            if img:
                img_col.image(img, width="stretch")
            with body:
                st.markdown(f"**Photo #{s['id']}** · {ui.farm_label(s['household_id']) if s['household_id'] else 'no farm'}"
                            f" · {s['crop'] or 'crop unknown'}")
                st.write(s["description"] or "No description.")
                st.warning(ai_label(s["candidates"]), icon=":material/hourglass_top:")
                top = s["candidates"][0]["pest"] if s["candidates"] else None
                overriding = st.session_state.get(f"override-{s['id']}", False) or top is None
                with st.form(f"scan-{s['id']}", border=False):
                    f = st.columns([1.4, 1, 1.4])
                    if overriding:
                        pest = f[0].selectbox("Your diagnosis", ["Fall Armyworm", "Late Blight", "Aphids", "Bean fly",
                                                                 "Maize Lethal Necrosis", "Other pest or disease",
                                                                 "Not a pest (dismiss)"])
                    else:
                        pest = top
                        f[0].text_input("AI suggestion", top, disabled=True)
                    sev = f[1].selectbox("Severity", ["MEDIUM", "HIGH", "LOW"])
                    name = f[2].text_input("Your full name")
                    b = st.columns([1.3, 1.3, 1.5])
                    confirm = b[0].form_submit_button("Confirm & Log Pest Alert", type="primary", width="stretch")
                    override = (b[1].form_submit_button("Override Diagnosis", width="stretch") if not overriding
                                else False)
                    try:
                        if override:
                            st.session_state[f"override-{s['id']}"] = True
                            st.rerun()
                        if confirm:
                            if pest == "Not a pest (dismiss)":
                                api.review_scan(s["id"], name, "DISMISSED")
                                st.toast("Dismissed: not a pest.", icon=":material/check:")
                            else:
                                r = api.review_scan(s["id"], name, "VERIFIED", pest, sev)
                                st.toast(f"Pest alert #{r['pest_alert_id']} logged. The agent will now use it.",
                                         icon=":material/check:")
                            st.session_state.pop(f"override-{s['id']}", None)
                            st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))

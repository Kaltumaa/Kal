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

CROPS = ["From household record", "Maize", "Beans", "Kale", "Potato", "Tomato"]

ui.header("Field scan", "Photograph a sick plant. A local model describes it, the pest guide suggests causes, and an "
                        "officer confirms before it counts as a pest alert.")
t_new, t_check = st.tabs(["New photo", "Officer check"])

with t_new:
    left, right = st.columns([1, 1], gap="large")
    with left:
        source = st.segmented_control("Source", ["Camera", "Upload"], default="Camera", label_visibility="collapsed")
        photo = (st.camera_input("Photo", label_visibility="collapsed") if source == "Camera"
                 else st.file_uploader("Photo (JPEG or PNG, max 6 MB)", type=["jpg", "jpeg", "png"]))
        c = st.columns(2)
        hid = c[0].selectbox("Household", ["None"] + api.households())
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
            st.markdown(f"**Scan #{res['scan_id']}** · {res['household_id'] or 'no household'} · "
                        f"{res['crop'] or 'crop unknown'}")
            if not res["vision_available"]:
                st.warning("The vision model is offline, so the photo was saved for the officer to check by eye.")
            st.write(res["description"] or "—")
            if res["candidates"]:
                st.markdown("**Possible causes**")
                st.dataframe(pd.DataFrame([{"Cause": x["pest"], "Match": x["score"], "Signs seen": ", ".join(x["matched"])}
                                           for x in res["candidates"]]), hide_index=True, width="stretch",
                             column_config={"Match": st.column_config.ProgressColumn("Match", min_value=0, max_value=1)})
            else:
                st.caption("No clear match. See Learn → Pests & diseases.")
            st.caption("Not a diagnosis. It waits in Officer check until a named officer confirms it.")

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
                st.markdown(f"**Scan #{s['id']}** · {s['household_id'] or 'no household'} · {s['crop'] or 'crop unknown'}")
                st.write(s["description"] or "No description.")
                with st.form(f"scan-{s['id']}", border=False):
                    guesses = [x["pest"] for x in s["candidates"]]
                    f = st.columns([1.4, 1, 1.4])
                    pest = f[0].selectbox("Confirmed cause", list(dict.fromkeys(
                        guesses + ["Fall Armyworm", "Late Blight", "Aphids", "Bean fly", "Other"])))
                    sev = f[1].selectbox("Severity", ["MEDIUM", "HIGH", "LOW"])
                    name = f[2].text_input("Your full name")
                    b = st.columns([1, 1, 2])
                    ok = b[0].form_submit_button("Verify", type="primary", width="stretch")
                    no = b[1].form_submit_button("Dismiss", width="stretch")
                    try:
                        if ok:
                            r = api.review_scan(s["id"], name, "VERIFIED", pest, sev)
                            st.toast(f"Pest alert #{r['pest_alert_id']} created. The agent will use it.",
                                     icon=":material/check:")
                            st.rerun()
                        if no:
                            api.review_scan(s["id"], name, "DISMISSED")
                            st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))

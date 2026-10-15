"""AI Scan.

Farmer: take or upload a photo of a plant, weed or pest. It goes to the extension officer; the farmer never sees the
AI's guess, only the officer's verified result (here and in Notifications).
Officer: verify photos. The officer sees the photo and the AI's unverified suggestion, then confirms, overrides or
dismisses it, with a note for the farmer. A confirmed pest becomes an alert the advisory agent uses.
"""
from __future__ import annotations

import base64

import pandas as pd
import streamlit as st

import api_client as api
import ui

role, mine = st.session_state.get("role", "officer"), st.session_state.get("my_farm")


def ai_label(candidates: list[dict]) -> str:
    """The model's output, always shown to the officer as an unverified suggestion."""
    if not candidates:
        return "AI Analysis: no clear match to a known plant problem, weed or pest — ⏳ Awaiting Verification"
    top = candidates[0]
    low = " Low match: look closely at the photo before verifying." if top["score"] < 0.5 else ""
    return (f"AI Analysis: Consistent with **{top['pest']}** ({top.get('type', 'Pest').lower()}, "
            f"{top['score'] * 100:.0f}% symptom-match score) — ⏳ Awaiting Verification.{low}")


def farmer_page() -> None:
    ui.header("Identify plants, weeds & pests", "Send a photo to your extension officer. They check it and tell you "
                                                "what it is and what to do.")
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        source = st.segmented_control("Source", ["Camera", "Upload"], default="Camera", label_visibility="collapsed")
        photo = (st.camera_input("Photo", label_visibility="collapsed") if source == "Camera"
                 else st.file_uploader("Photo (JPEG or PNG, max 6 MB)", type=["jpg", "jpeg", "png"]))
        if st.button("Send to my extension officer", type="primary", disabled=photo is None, width="stretch"):
            with st.spinner("Sending… (the photo is checked on this computer first, about a minute)"):
                try:
                    r = api.submit_photo(mine, base64.b64encode(photo.getvalue()).decode())
                    st.success(f"Photo #{r['scan_id']} sent. {r['message']}", icon=":material/schedule_send:")
                except api.ApiError as exc:
                    st.error(str(exc.detail))
        st.caption("Your officer sees the photo before you get an answer. Photos stay on this computer.")
    with right:
        st.markdown("**My photos**")
        photos = api.my_photos(mine)
        if not photos:
            st.caption("No photos sent yet.")
        for p in photos:
            with st.container(border=True):
                c = st.columns([1, 2.2], gap="small")
                img = api.scan_image(p["id"])
                if img:
                    c[0].image(img, width="stretch")
                with c[1]:
                    st.markdown(f"**Photo #{p['id']}** <span class='cp-muted'>· {p['created_at'][:16].replace('T', ' ')}"
                                "</span>", unsafe_allow_html=True)
                    if p["waiting"]:
                        st.markdown(":orange-badge[⏳ Waiting for your extension officer]")
                    else:
                        st.markdown(f":green-badge[Reviewed by {p['reviewed_by']}]  \n**{p['officer_finding']}**")
                        if p["officer_note"]:
                            st.caption(p["officer_note"])


def officer_page() -> None:
    ui.header("Verify photos", "Photos farmers sent. Check the AI's suggestion, then confirm, override or dismiss it. "
                               "The farmer sees only your answer.")
    scans = api.scans()
    pending = [s for s in scans if s["status"] == "UNVERIFIED"]
    done = [s for s in scans if s["status"] != "UNVERIFIED"]
    st.caption(f"{len(pending)} waiting · {len(done)} reviewed")
    if not pending:
        st.info("No photos waiting for verification.", icon=":material/task_alt:")
    for s in pending:
        with st.container(border=True):
            img_col, body = st.columns([1, 2.3], gap="medium")
            img = api.scan_image(s["id"])
            if img:
                img_col.image(img, width="stretch")
            with body:
                st.markdown(f"**Photo #{s['id']}** · {ui.farm_label(s['household_id']) if s['household_id'] else 'no farm'}"
                            f" · {s['crop'] or 'crop unknown'}")
                st.caption(f"AI description: {s['description'] or '—'}")
                st.warning(ai_label(s["candidates"]), icon=":material/hourglass_top:")
                top = s["candidates"][0]["pest"] if s["candidates"] else None
                overriding = st.session_state.get(f"override-{s['id']}", False) or top is None
                with st.form(f"scan-{s['id']}", border=False):
                    f = st.columns([1.4, 1, 1.4])
                    if overriding:
                        pest = f[0].selectbox("Your diagnosis", ["Fall Armyworm", "Late Blight", "Aphids", "Bean fly",
                                                                 "Maize Lethal Necrosis", "Striga (witchweed)",
                                                                 "Wild / prickly lettuce", "Other pest, disease or weed",
                                                                 "Not a problem (dismiss)"])
                    else:
                        pest = top
                        f[0].text_input("AI suggestion", top, disabled=True)
                    sev = f[1].selectbox("Severity", ["MEDIUM", "HIGH", "LOW"])
                    name = f[2].text_input("Your full name")
                    note = st.text_input("Note to the farmer", max_chars=300,
                                         placeholder="e.g. Pull it out before it flowers; no spraying needed.")
                    b = st.columns([1.3, 1.3, 1.5])
                    confirm = b[0].form_submit_button("✅ Verify Assessment", type="primary", width="stretch")
                    override = (b[1].form_submit_button("Override Diagnosis", width="stretch") if not overriding
                                else False)
                    try:
                        if override:
                            st.session_state[f"override-{s['id']}"] = True
                            st.rerun()
                        if confirm:
                            if pest == "Not a problem (dismiss)":
                                api.review_scan(s["id"], name, "DISMISSED", note=note)
                                st.toast("Dismissed. The farmer is notified.", icon=":material/check:")
                            else:
                                r = api.review_scan(s["id"], name, "VERIFIED", pest, sev, note)
                                st.toast(f"Verified. Alert #{r['pest_alert_id']} logged; the farmer is notified.",
                                         icon=":material/check:")
                            st.session_state.pop(f"override-{s['id']}", None)
                            st.rerun()
                    except api.ApiError as exc:
                        st.error(str(exc.detail))
    if done:
        with st.expander(f"Reviewed photos ({len(done)})"):
            st.dataframe(pd.DataFrame([{"Photo": d["id"], "Farm": ui.farm_label(d["household_id"]),
                                        "Result": d.get("officer_finding") or d["status"].title(),
                                        "By": d["reviewed_by"], "Note": d.get("officer_note") or ""} for d in done]),
                         hide_index=True, width="stretch")


if role == "farmer" and mine:
    farmer_page()
else:
    officer_page()

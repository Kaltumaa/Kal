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


NOT_PLANT, UNCLEAR = "Not a plant or pest (not applicable)", "Photo unclear: field visit needed"
# Officer choice -> (finding stored, suggested message to the farmer)
DISMISS = {
    "Not a problem (dismiss)": ("No problem found",
                                "Your photo shows no pest, disease or weed problem. No action is needed."),
    NOT_PLANT: ("Not a plant or pest: advice not applicable",
                "This photo does not show a plant or a pest, so there is no advice for it. Send a photo of the "
                "affected leaves, stem or insect."),
    UNCLEAR: ("Photo unclear: field visit needed",
              "Your photo is too blurry or dark to be sure what it is. Your extension officer will call or visit. "
              "You can also send a clearer photo in daylight."),
}


# Same wording as the backend's templates (fieldscan FINDINGS_SW, voice_draft SW_NAMES). Native-speaker review pending.
FINDINGS_SW = {"No problem found": "Hakuna tatizo lililoonekana.",
               "Not a plant or pest: advice not applicable": "Picha haionyeshi mmea wala mdudu, kwa hiyo hakuna ushauri.",
               "Photo unclear: field visit needed": "Picha haikuwa wazi. Afisa atakupigia simu au kukutembelea."}
SW_NAMES = {"fall armyworm": "viwavijeshi", "aphids": "vidukari", "late blight": "ukungu", "bean fly": "inzi wa maharagwe"}


def call_defaults(lang: str, pest: str, cloud: dict | None, ai_draft: dict | None = None, top: str | None = None) -> str:
    """Starting text for the phone call, only ever a start: the officer edits it before signing.
    Kiswahili: the drafted script (Qwen's two-key JSON) while the officer keeps the AI's diagnosis, else a template."""
    finding = DISMISS[pest][0] if pest in DISMISS else pest
    if lang == "sw":
        if ai_draft and ai_draft.get("farmer_kiswahili_voice_script") and pest == top:
            return ai_draft["farmer_kiswahili_voice_script"]
        if cloud and cloud.get("voice_draft_sw") and pest == top:
            return cloud["voice_draft_sw"]
        said = FINDINGS_SW.get(finding) or f"Huenda shamba lako lina tatizo la {SW_NAMES.get(finding.lower(), finding)}."
        return f"Habari. Afisa wako wa kilimo ameangalia picha ya shamba lako. {said} Maelezo kamili yametumwa kwa SMS."
    return f"Your officer has checked the photo of your farm. Result: {finding}. The full advice was sent to you by SMS."


def draft_box(ai_draft: dict | None) -> None:
    if not ai_draft or not ai_draft.get("extension_officer_draft"):
        return
    with st.expander(f":material/description: Officer draft from the local AI ({ai_draft.get('model') or 'Qwen'}), "
                     "not verified"):
        st.markdown(ai_draft["extension_officer_draft"])


def deepleaf_box(cloud: dict | None) -> None:
    if not cloud:
        return
    if cloud.get("status") != "ok":
        st.caption(f"DeepLeaf second opinion: not available ({cloud.get('error') or cloud.get('status')}).")
        return
    with st.container(border=True):
        st.markdown(":violet-badge[DeepLeaf Agronomist · second opinion · not verified]")
        st.markdown(cloud.get("officer_draft") or "—")
        st.caption("From DeepLeaf's cloud model. Compare it with the photo and the local AI; the farmer never sees "
                   "it unless you put it in your message.")


def group_review(g: dict, by_id: dict) -> None:
    """Clear photos from one ward with the same AI suggestion: the officer looks at all of them, unticks any that
    differ, and signs once. Each photo still gets its own review record and audit line."""
    scans = [by_id[i] for i in g["scan_ids"] if i in by_id]
    with st.expander(f":material/grid_view: {len(scans)} clear photos from {g['zone_id'].title()}, all suggested as "
                     f"**{g['pest']}**: review together", expanded=True):
        st.caption("The AI's match score is a symptom match, not a certainty. Look at every photo and untick any that "
                   "does not show the same problem; those stay below for a one-by-one review.")
        cols, keep = st.columns(4), []
        for n, s in enumerate(scans):
            with cols[n % 4]:
                img = api.scan_image(s["id"])
                if img:
                    st.image(img, width="stretch")
                if st.checkbox(f"#{s['id']} · {ui.farm_label(s['household_id'])}", value=True,
                               key=f"grp-{g['zone_id']}-{s['id']}"):
                    keep.append(s["id"])
        with st.form(f"grp-form-{g['zone_id']}-{g['pest']}", border=False):
            c = st.columns([1.4, 1])
            pest = c[0].text_input("Diagnosis for the ticked photos", g["pest"])
            sev = c[1].selectbox("Severity", ["MEDIUM", "HIGH", "LOW"])
            note = st.text_area("Message to each farmer", api.problem(g["pest"])["farmer_message"], height=110,
                                max_chars=1200)
            f = st.columns([1.6, 1.4])
            name = f[0].text_input("Your full name")
            if f[1].form_submit_button(f"✅ Verify {len(keep)} ticked & notify farmers", type="primary",
                                       width="stretch"):
                try:
                    r = api.review_scan_batch(keep, name, pest, sev, note)
                    st.toast(f"Verified {len(r['verified'])} photos as {pest}, signed by {r['officer']}.",
                             icon=":material/check:")
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc.detail))


def farmer_page() -> None:
    ui.header("Identify plants, weeds, pests & sick plants", "Send a photo to your extension officer. They check it "
                                                            "and tell you what it is and how to fix it.")
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
        st.caption("Your officer sees the photo before you get an answer, and the answer also comes to you by SMS, "
                   "so you get it without internet. No data to send a photo? Text PROBLEM and what you see "
                   "(see Notifications), or ask your officer to take a photo on a visit.")
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
    ui.header("Identify plants, weeds, pests & sick plants", "Verify the photos farmers sent: check the AI's "
                                                            "suggestion, confirm or correct it, and send the farmer what "
                                                            "it is and how to fix it.")
    scans = api.scans()
    pending = [s for s in scans if s["status"] == "UNVERIFIED"]
    done = [s for s in scans if s["status"] != "UNVERIFIED"]
    dl = api.integrations()["deepleaf"]
    st.caption(f"{len(pending)} waiting · {len(done)} reviewed · DeepLeaf second opinion: "
               + ("on" if dl["enabled"] else f"off ({dl['reason']})"))
    if not pending:
        st.info("No photos waiting for verification.", icon=":material/task_alt:")
    for g in api.scan_groups():
        group_review(g, {s["id"]: s for s in pending})
    for s in pending:
        with st.container(border=True):
            img_col, body = st.columns([1, 2.3], gap="medium")
            img = api.scan_image(s["id"])
            if img:
                img_col.image(img, width="stretch")
            with body:
                st.markdown(f"**Photo #{s['id']}** · {ui.farm_label(s['household_id']) if s['household_id'] else 'no farm'}"
                            f" · {s['crop'] or 'crop unknown'}")
                if s.get("submitted_by"):
                    st.markdown(f":blue-badge[Nyumba Kumi] Sent by lead farmer **{ui.farm_label(s['submitted_by'])}** "
                                "for this neighbour, who has no smartphone.")
                st.caption(f"AI description: {s['description'] or '—'}")
                deepleaf_box(s.get("cloud"))
                draft_box(s.get("ai_draft"))
                issues = (s.get("image_quality") or {}).get("issues", [])
                if s.get("inconclusive"):
                    st.error(f"**Inconclusive image capture ({' and '.join(issues)}): requires a manual field call.** "
                             "The AI suggestion is hidden because a photo like this can make a weed look like a "
                             "disease. Call or visit the farmer, or ask for a clear daylight photo.",
                             icon=":material/blur_on:")
                else:
                    st.warning(ai_label(s["candidates"]), icon=":material/hourglass_top:")
                if s.get("not_a_plant"):
                    st.info("The AI found no plant, leaf or insect in this photo. If you agree, mark it **not "
                            "applicable**: there is no advice to give.", icon=":material/hide_image:")
                top = s["candidates"][0]["pest"] if s["candidates"] and not s.get("inconclusive") else None
                first = [UNCLEAR] if s.get("inconclusive") else [NOT_PLANT] if s.get("not_a_plant") else []
                options = list(dict.fromkeys(first + ([top] if top else []) + [
                    "Fall Armyworm", "Late Blight", "Aphids", "Bean fly", "Maize Lethal Necrosis",
                    "Tomato leaf miner (Tuta)", "Striga (witchweed)", "Couch grass", "Black-jack (Bidens)",
                    "Wild / prickly lettuce", "Weed (species unclear)", "Nutrient deficiency (not a pest)",
                    "Not a problem (dismiss)", NOT_PLANT, UNCLEAR]))
                c = st.columns([1.6, 1])
                pest = c[0].selectbox("Your diagnosis (the AI's suggestion is first; change it to override)", options,
                                      key=f"diag-{s['id']}")
                sev = c[1].selectbox("Severity", ["MEDIUM", "HIGH", "LOW"], key=f"sev-{s['id']}")
                if pest in DISMISS:
                    suggested = DISMISS[pest][1]
                else:
                    suggested = api.problem(pest)["farmer_message"]
                farm = st.session_state.get("farm_info", {}).get(s["household_id"] or "", {})
                feature = farm.get("phone_type") == "feature"
                cc = st.columns([1.6, 1])
                call = cc[0].toggle("📞 Also phone the farmer with the result" + (" (feature phone)" if feature else ""),
                                    value=feature and farm.get("has_phone", False), key=f"call-{s['id']}",
                                    disabled=not farm.get("has_phone"),
                                    help="An automatic call reads out your message. The farmer presses 1 if they "
                                         "heard it, 2 to ask for a visit." if farm.get("has_phone")
                                    else "No phone number on this farm. Add it on the Farms page.")
                lang = cc[1].segmented_control("Call language", ["sw", "en"], default="sw", key=f"clang-{s['id']}",
                                               format_func=lambda x: "Kiswahili" if x == "sw" else "English",
                                               disabled=not call) or "sw"
                with st.form(f"scan-{s['id']}", border=False):
                    note = st.text_area("Message to the farmer (what it is and how to fix it; edit before sending)",
                                        suggested, height=140, max_chars=1200, key=f"note-{s['id']}-{pest}")
                    script = None
                    if call:
                        script = st.text_area("What the farmer will hear on the call (short, simple sentences)",
                                              call_defaults(lang, pest, s.get("cloud"), s.get("ai_draft"), top),
                                              height=110, max_chars=600,
                                              key=f"script-{s['id']}-{pest}-{lang}")
                    f = st.columns([1.6, 1.4])
                    name = f[0].text_input("Your full name")
                    confirm = f[1].form_submit_button("✅ Verify Assessment & notify farmer", type="primary",
                                                      width="stretch")
                    try:
                        if confirm:
                            if pest in DISMISS:
                                api.review_scan(s["id"], name, "DISMISSED", note=note, finding=DISMISS[pest][0],
                                                call=call, call_script=script, call_language=lang)
                                st.toast("Saved. The farmer is notified.", icon=":material/check:")
                            else:
                                api.review_scan(s["id"], name, "VERIFIED", pest, sev, note, call=call,
                                                call_script=script, call_language=lang)
                                st.toast(f"Verified as {pest}. The farmer is notified.", icon=":material/check:")
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

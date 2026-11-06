"""Nyumba Kumi: the lead farmer sends photos for neighbours without a smartphone and follows their results.

The lead sees only what any farmer sees for a photo: waiting, or the officer's finding. Never the AI's guess.
The neighbour gets the officer's answer by SMS, and by a phone call if the officer chooses.
"""
from __future__ import annotations

import base64

import streamlit as st

import api_client as api
import ui

mine = st.session_state.get("my_farm")
view = api.my_cell(mine)
CALL_TEXT = {"SENT": "phone ringing", "ANSWERED": "answered the call", "ACKNOWLEDGED": "heard the call",
             "VISIT_REQUESTED": "pressed 2: needs your help", "NO_ANSWER": "did not answer the call",
             "FAILED": "call failed", "QUEUED": "call queued"}

if view["role"] == "none":
    ui.header("Nyumba Kumi", "Neighbours helping neighbours reach the extension officer.")
    st.info("Your farm is not in a Nyumba Kumi cell yet. Ask your extension officer to add it. In a cell, a lead "
            "farmer with a smartphone can send photos for neighbours who have none.", icon=":material/groups:")
    st.stop()

cell = view["cell"]
if view["role"] == "member":
    ui.header("Nyumba Kumi", f"{cell['name']} · {cell['zone_id'].title()}")
    lead = view["lead"]
    st.info(f"Your lead farmer is **{lead.get('farmer_name') or lead['household_id']}**. If you see a problem on your "
            "farm and have no smartphone, ask them to take a photo for you. Your officer's answer comes to **your** "
            "phone by SMS, and sometimes as a call: press 1 if you understood, or 2 if you need help from your "
            "lead farmer.", icon=":material/groups:")
    st.stop()

ui.header("Nyumba Kumi", f"You lead {cell['name']} ({cell['zone_id'].title()}). Send photos for neighbours who have "
                         "no smartphone; the officer's answer goes to their own phone.")
neighbours = view["neighbours"]
visits = view["visit_requests"]
if visits:
    names = ", ".join(ui.farm_label(v["household_id"]) for v in visits)
    st.warning(f"**Needs your help:** {names} pressed 2 on the officer's call. Please visit them and see what "
               "they need; the officer has been told too.", icon=":material/directions_walk:")

left, right = st.columns([1.15, 1], gap="large")
with left:
    st.markdown("##### My neighbours")
    for n in neighbours:
        with ui.section():
            phone = "Feature phone" if n.get("phone_type") == "feature" else "Smartphone"
            top = st.columns([2.4, 1], vertical_alignment="center")
            top[0].markdown(f"**{n['farmer_name'] or n['household_id']}** <span class='cp-muted'>· "
                            f"{n.get('active_crop') or 'no crop recorded'} · {phone}</span>", unsafe_allow_html=True)
            if n["visit_requested"]:
                top[1].markdown(":orange-badge[Needs help]")
            elif n["waiting"]:
                top[1].markdown(f":gray-badge[{n['waiting']} waiting]")
            lines = []
            for p in n["photos"][:3]:
                when = (p["reviewed_at"] or p["created_at"])[:10]
                lines.append(f"Photo #{p['id']} · {when} · " + ("⏳ waiting for the officer" if p["waiting"]
                                                                else f"**{p['officer_finding']}**"))
            if n.get("last_call"):
                lines.append(f"Call: {CALL_TEXT.get(n['last_call']['status'], n['last_call']['status'])} "
                             f"({n['last_call']['updated_at'][:10]})")
            st.markdown("  \n".join(lines) if lines else "<span class='cp-muted'>No photos sent for them yet.</span>",
                        unsafe_allow_html=True)

with right:
    st.markdown("##### Send a photo for a neighbour")
    pick = st.selectbox("Neighbour", [n["household_id"] for n in neighbours],
                        format_func=lambda h: next(n["farmer_name"] or h for n in neighbours if n["household_id"] == h))
    source = st.segmented_control("Source", ["Camera", "Upload"], default="Upload", label_visibility="collapsed",
                                  key="nk-src")
    photo = (st.camera_input("Photo", label_visibility="collapsed", key="nk-cam") if source == "Camera"
             else st.file_uploader("Photo (JPEG or PNG, max 6 MB)", type=["jpg", "jpeg", "png"], key="nk-up"))
    st.caption("Ask your neighbour first. Take it close to the sick leaves, stem or insect, in daylight.")
    if st.button("Send to the extension officer", type="primary", disabled=photo is None or not pick,
                 width="stretch"):
        with st.spinner("Sending… (the photo is checked on this computer first)"):
            try:
                r = api.cell_photo(mine, pick, base64.b64encode(photo.getvalue()).decode())
                st.success(f"Photo #{r['scan_id']}: {r['message']}", icon=":material/schedule_send:")
            except api.ApiError as exc:
                st.error(str(exc.detail))

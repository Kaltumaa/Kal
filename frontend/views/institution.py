"""Institution home: a read-only view of the extension officers who work with it (performance and workload by
sub-county; officers sign up and work independently, no approval),
the farmers it pays for and the payment gateway (KES 50 per farmer, M-Pesa or card), Lead Farmers and bulk alerts."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import api_client as api
import auth
import payments_panel
import ui

u = auth.require("institution")
ui.header("My extension officers", "The officers who work with you, their workload in each sub-county, and the "
                                   "farmers you pay for.")

try:
    data = api.institution_officers(auth.token())
    farmer_lists = api.institution_farmers(auth.token())
except api.ApiError as exc:
    auth.show_error(exc)
    st.stop()
officers, workload, sub = data["officers"], data["sub_county_workload"], data["subscription"]
covered, waiting = farmer_lists["covered"], farmer_lists["waiting"]

if not sub["active"]:
    st.warning("Not paid yet: your farmers cannot use TALO, and you cannot send alerts. "
               "Open **Farmers & payment** to pay KES 50 per farmer by M-Pesa or card.",
               icon=":material/credit_card_off:")
else:
    st.success(f"Paid until {(sub['valid_until'] or '')[:10]} · {sub['farmers_covered']} of {sub['farmer_seats']} "
               f"farmer places used · {', '.join(sub['sub_counties'])}", icon=":material/verified:")

pending_total = sum(o["pending_approvals"]["total"] for o in officers)
times = [o["avg_response_minutes"] for o in officers if o["avg_response_minutes"] is not None]
c = st.columns(5)
c[0].metric("Officers", len(officers))
c[1].metric("Sub-counties", len(workload))
c[2].metric("Farmers with access", len(covered), delta=f"{len(waiting)} waiting" if waiting else None,
            delta_color="off")
c[3].metric("Waiting for officers", pending_total, help="Advice drafts and agent escalations not yet decided")
c[4].metric("Avg response", f"{sum(times) / len(times):.0f} min" if times else "—")

tab_officers, tab_pay, tab_tools = st.tabs(["Extension officers", "Farmers & payment", "Lead Farmers & alerts"])

# --- officers -----------------------------------------------------------------------------------------------------
with tab_officers:
    if not officers:
        st.info("No officers yet. Extension officers sign up on their own on the sign-in page; those who name your "
                "institution appear here.", icon=":material/group_add:")
    else:
        with ui.section():
            st.subheader("Workload by sub-county")
            wl = pd.DataFrame(workload)
            long = wl.melt(id_vars=["sub_county"], value_vars=["households_per_officer", "pending_approvals",
                                                               "open_escalations"], var_name="measure")
            long["measure"] = long["measure"].map({"households_per_officer": "Farms per officer",
                                                   "pending_approvals": "Waiting for approval",
                                                   "open_escalations": "Open escalations"})
            st.altair_chart(alt.Chart(long).mark_bar().encode(
                x=alt.X("value:Q", title=None), y=alt.Y("sub_county:N", title=None),
                color=alt.Color("measure:N", title=None, legend=alt.Legend(orient="bottom")),
                yOffset="measure:N", tooltip=["sub_county", "measure", "value"]).properties(
                    height=60 + 70 * len(wl)), width="stretch")
            st.dataframe(wl.rename(columns={"sub_county": "Sub-county", "county": "County", "officers": "Officers",
                                            "households": "Farms", "households_per_officer": "Farms per officer",
                                            "pending_approvals": "Waiting", "open_escalations": "Open escalations"}),
                         hide_index=True, width="stretch")

        st.subheader("Officers by sub-county")
        subs = sorted({o["sub_county"] for o in officers})
        pick = st.segmented_control("Sub-county", ["All"] + subs, default="All")
        for sc in subs:
            if pick not in (None, "All", sc):
                continue
            group = [o for o in officers if o["sub_county"] == sc]
            with st.expander(f"{sc} · {len(group)} officer{'s' if len(group) != 1 else ''}", expanded=True):
                st.dataframe(pd.DataFrame([{
                    "Officer": o["full_name"],
                    "Wards": ", ".join(w.title() for w in o["wards"]) if isinstance(o["wards"], list) else "All",
                    "Farms": o["active_caseload"]["households"],
                    "Waiting: advice": o["pending_approvals"]["advisories"],
                    "Waiting: escalations": o["pending_approvals"]["escalations"],
                    "Resolved": o["cases"]["resolved"],
                    "Escalated to officer": o["cases"]["escalated_to_officer"],
                    "Avg response (min)": o["avg_response_minutes"],
                } for o in group]), hide_index=True, width="stretch",
                    column_config={"Avg response (min)": st.column_config.NumberColumn(format="%.0f")})
    if data.get("unassigned_open_escalations"):
        st.warning(f"{data['unassigned_open_escalations']} escalation(s) have no officer for their sub-county.")

# --- farmers & payment --------------------------------------------------------------------------------------------
with tab_pay:
    areas = sorted({o["sub_county"] for o in officers} | {f["sub_county"] for f in waiting if f.get("sub_county")})
    payments_panel.render(areas, len(waiting))
    with ui.section():
        st.subheader("Farmers")
        rows = [{"Farmer": f["full_name"], "Sub-county": f.get("sub_county"), "Farm": f.get("household_id") or "",
                 "Access": "Paid" if f in covered else "Waiting", "Joined": (f["created_at"] or "")[:10]}
                for f in covered + waiting]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.caption("No farmer has signed up in your county yet.")

# --- Lead Farmers and alerts ------------------------------------------------------------------------------------------
with tab_tools:
    with ui.section():
        st.subheader("Lead Farmers")
        farms = st.session_state.get("farm_info", {})
        with st.form("lead-farmer"):
            c = st.columns([3, 1], vertical_alignment="bottom")
            hid = c[0].selectbox("Make this farmer a Lead Farmer (the farmer must have an account)", sorted(farms),
                                 format_func=ui.farm_label)
            if c[1].form_submit_button("Designate", width="stretch"):
                try:
                    r = api.designate_lead_farmer(auth.token(), hid)
                    st.success(f"{r['lead_farmer']['full_name']} is now a Lead Farmer"
                               + (f" for cell {', '.join(r['cells'])}" if r["cells"] else "") + ".")
                except api.ApiError as exc:
                    auth.show_error(exc)
    with ui.section():
        st.subheader("Bulk alert by SMS")
        st.caption("One message to every farm with a phone in a sub-county you pay for, signed with your name.")
        with st.form("bulk-alert", clear_on_submit=True):
            c = st.columns([1, 2])
            sc = c[0].selectbox("Sub-county", sub["sub_counties"] or ["Dagoretti South"])
            msg = c[1].text_area("Message (max 320 characters)", max_chars=320, height=80)
            if st.form_submit_button("Send alert", type="primary"):
                try:
                    r = api.bulk_alert(auth.token(), sc, msg)
                    st.success(f"Queued {r['queued']} SMS, signed by {r['sent_by']}.")
                except api.ApiError as exc:
                    auth.show_error(exc)

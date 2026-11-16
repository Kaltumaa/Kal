"""Farmer access payment for institutions: KES 50 per farmer per 30 days, by M-Pesa (STK Push) or card.
Rendered inside the institution's page (views/institution.py)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
import auth
import ui


def _status(tx: dict) -> None:
    label = {"SUCCESS": ("Paid", "success"), "PENDING": ("Waiting for confirmation", "info"),
             "FAILED": ("Failed", "error"), "CANCELLED": ("Cancelled", "warning")}[tx["status"]]
    getattr(st, label[1])(f"{label[0]} · {tx['provider'].title()} · KES {tx['amount']:,}"
                          + (f" · receipt {tx['receipt']}" if tx.get("receipt") else "")
                          + (f" · {tx['result_desc']}" if tx["status"] != "SUCCESS" and tx.get("result_desc") else ""))


def render(sub_counties: list[str], waiting_farmers: int) -> None:
    token = auth.token()
    try:
        data = api.subscription_overview(token)
        modes = api.payments_status()
    except api.ApiError as exc:
        auth.show_error(exc)
        return
    ent, price = data["entitlement"], data["tiers"]["per_farmer"]["price_kes"]

    c = st.columns(4)
    c[0].metric("Payment", "Active" if ent["active"] else "Not paid")
    c[1].metric("Farmers paid for", f"{ent['farmers_covered']} / {ent['farmer_seats']}")
    c[2].metric("Farmers waiting", waiting_farmers)
    c[3].metric("Valid until", (ent["valid_until"] or "—")[:10])
    if modes["mpesa"]["mode"] == "simulator" or modes["card"]["mode"] == "simulator":
        st.info("Demo mode: payments run on the built-in simulator, so no real money moves. Add the M-Pesa Daraja / "
                "Stripe or Flutterwave test keys to `.env` to use the real sandbox.", icon=":material/science:")

    with ui.section():
        st.subheader(f"Pay for farmer access · KES {price} per farmer per month")
        c = st.columns([2, 1])
        areas = c[0].multiselect("Sub-counties", sorted(set(sub_counties) | set(ent["sub_counties"]))
                                 or ["Dagoretti South"], default=ent["sub_counties"] or sub_counties[:1]
                                 or ["Dagoretti South"], accept_new_options=True,
                                 help="Farmers who signed up in these sub-counties get access")
        farmers = c[1].number_input("Farmers", min_value=1, max_value=100_000,
                                    value=max(1, waiting_farmers + ent["farmers_covered"]))
        st.markdown(f"**Total: KES {price * farmers:,} for 30 days** ({farmers:,} farmers × KES {price})")
        if st.button("Continue to payment", type="primary", disabled=not areas):
            try:
                st.session_state["billing_sub"] = api.create_subscription(token, "per_farmer", int(farmers), areas)
            except api.ApiError as exc:
                auth.show_error(exc)

    pending = st.session_state.get("billing_sub")
    if pending is None:
        waiting = [s for s in data["subscriptions"] if s["status"] == "PENDING_PAYMENT"]
        pending = waiting[0] if waiting else None
    if pending:
        with ui.section():
            st.subheader(f"Pay KES {pending['amount_kes']:,}")
            st.caption(f"{pending['seats']:,} farmers in {(pending['sub_counties'] or '').replace(',', ', ')} "
                       f"· 30 days")
            mpesa_tab, card_tab = st.tabs(["M-Pesa", "Visa / Mastercard"])
            with mpesa_tab:
                st.caption("You get a prompt on your phone to enter your M-Pesa PIN.")
                with st.form("mpesa"):
                    phone = st.text_input("Safaricom number", placeholder="0712 345 678")
                    outcome = st.selectbox("Simulated result", ["success", "cancelled", "insufficient_funds",
                                                                "timeout"],
                                           disabled=modes["mpesa"]["mode"] != "simulator",
                                           help="Only used by the simulator")
                    if st.form_submit_button("Send M-Pesa prompt", type="primary", width="stretch"):
                        try:
                            r = api.mpesa_stkpush(token, pending["id"], phone, outcome)
                            st.session_state["billing_tx"] = r["transaction"]["id"]
                            st.session_state.pop("billing_sub", None)
                            st.rerun()
                        except api.ApiError as exc:
                            auth.show_error(exc)
            with card_tab:
                st.caption("You pay on the card processor's secure page; card numbers never reach this app.")
                outcome = st.selectbox("Simulated result", ["success", "declined"], key="card-sim",
                                       disabled=modes["card"]["mode"] != "simulator")
                if st.button("Pay by card", type="primary", width="stretch"):
                    try:
                        r = api.card_checkout(token, pending["id"], outcome)
                        st.session_state["billing_tx"] = r["transaction"]["id"]
                        st.session_state["billing_checkout_url"] = (r["checkout_url"] if r["mode"] != "simulator"
                                                                    else None)
                        st.session_state.pop("billing_sub", None)
                        st.rerun()
                    except api.ApiError as exc:
                        auth.show_error(exc)

    tx_id = st.session_state.get("billing_tx")
    if tx_id:
        with ui.section():
            st.subheader("Payment status")
            try:
                tx = api.transaction(token, tx_id)
            except api.ApiError as exc:
                auth.show_error(exc)
                tx = None
            if tx:
                _status(tx)
                url = st.session_state.get("billing_checkout_url")
                if tx["status"] == "PENDING" and url:
                    st.link_button("Open card payment page", url, type="primary")
                if tx["status"] == "PENDING" and st.button("Check again", icon=":material/refresh:"):
                    st.rerun()
                if tx["status"] != "PENDING" and st.button("Done"):
                    for k in ("billing_tx", "billing_checkout_url"):
                        st.session_state.pop(k, None)
                    st.rerun()

    if data["transactions"]:
        with ui.section():
            st.subheader("Payment history")
            st.dataframe(pd.DataFrame([{
                "Date": t["created_at"][:16].replace("T", " "), "Method": t["provider"].title(),
                "Amount (KES)": t["amount"], "Status": t["status"], "Receipt": t.get("receipt") or "",
                "Phone": t.get("phone_masked") or "", "Simulated": "yes" if t["simulated"] else "no"}
                for t in data["transactions"]]), hide_index=True, width="stretch")

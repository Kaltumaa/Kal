"""Visa / card checkout through Stripe Checkout or Flutterwave Standard, plus their webhooks.

Only TEST keys are used unless PAYMENTS_ALLOW_LIVE=1 (sk_test_... for Stripe, FLWSECK_TEST-... for Flutterwave).
With no key (or CARD_SIMULATE=1) a simulator returns a local checkout URL and settles through the same webhook
handler with a correctly signed, provider-shaped event, so card payment can be demoed offline.

Webhooks are verified before anything is read from them:
* Stripe: the `Stripe-Signature` header, HMAC-SHA256 over "<t>.<raw body>" with STRIPE_WEBHOOK_SECRET, 5-minute
  tolerance (Stripe's documented scheme).
* Flutterwave: the `verif-hash` header must equal FLW_WEBHOOK_HASH; the transaction is then re-checked with
  Flutterwave's verify endpoint (live mode) before the subscription is activated.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

import httpx

from crop_pilot import config
from crop_pilot.core import telemetry
from crop_pilot.payments import ledger
from crop_pilot.payments.ledger import PaymentError

STRIPE_API = "https://api.stripe.com/v1"
FLW_API = "https://api.flutterwave.com/v3"
STRIPE_TOLERANCE_S = 300
# The simulator signs its own events with this when no webhook secret is configured.
_SIM_SECRET = "whsec_simulator_" + secrets.token_hex(8)


def provider() -> str:
    if config.CARD_PROVIDER not in ("stripe", "flutterwave"):
        raise PaymentError("CARD_PROVIDER must be stripe or flutterwave.")
    return config.CARD_PROVIDER


def _key() -> str:
    return config.STRIPE_SECRET_KEY if provider() == "stripe" else config.FLW_SECRET_KEY


def _is_test_key(key: str) -> bool:
    return key.startswith(("sk_test_", "rk_test_")) or "_TEST" in key.upper()


def live() -> bool:
    key = _key()
    if config.CARD_SIMULATE or not key:
        return False
    if not _is_test_key(key) and not config.PAYMENTS_ALLOW_LIVE:
        return False            # a live key without the explicit opt-in is ignored: the simulator answers instead
    return True


def status() -> dict:
    key = _key()
    note = None
    if key and not _is_test_key(key) and not config.PAYMENTS_ALLOW_LIVE:
        note = "live key ignored: set PAYMENTS_ALLOW_LIVE=1 to take real card payments"
    return {"provider": provider(), "mode": ("test" if _is_test_key(key) else "live") if live() else "simulator",
            "webhook_secret_set": bool(config.STRIPE_WEBHOOK_SECRET if provider() == "stripe"
                                       else config.FLW_WEBHOOK_HASH), "note": note}


def _webhook_secret() -> str:
    if provider() == "stripe":
        return config.STRIPE_WEBHOOK_SECRET or ("" if live() else _SIM_SECRET)
    return config.FLW_WEBHOOK_HASH or ("" if live() else _SIM_SECRET)


def _urls(reference: str) -> tuple[str, str]:
    base = config.PUBLIC_BASE_URL or "http://127.0.0.1:8000"
    ok = config.CARD_SUCCESS_URL or f"{base}/api/payments/card/return"
    cancel = config.CARD_CANCEL_URL or f"{base}/api/payments/card/return"
    sep = lambda u: "&" if "?" in u else "?"   # noqa: E731
    return f"{ok}{sep(ok)}ref={reference}&status=success", f"{cancel}{sep(cancel)}ref={reference}&status=cancelled"


def checkout(subscription: dict, customer_email: str, institution_name: str, simulate_result: str = "success") -> dict:
    if subscription["status"] not in ("PENDING_PAYMENT", "ACTIVE"):
        raise PaymentError(f"Subscription is {subscription['status']}; start a new one.")
    prov, is_live = provider(), live()
    reference = ledger.new_reference("MKC")
    tx_id = ledger.open_transaction(subscription, prov, reference, simulated=not is_live)
    success_url, cancel_url = _urls(reference)
    amount = int(subscription["amount_kes"])
    if not is_live:
        return _simulate(tx_id, reference, amount, simulate_result)
    try:
        with httpx.Client(timeout=config.CARD_TIMEOUT_S) as client:
            if prov == "stripe":
                r = client.post(f"{STRIPE_API}/checkout/sessions", auth=(config.STRIPE_SECRET_KEY, ""), data={
                    "mode": "payment", "success_url": success_url, "cancel_url": cancel_url,
                    "client_reference_id": reference, "customer_email": customer_email,
                    "payment_method_types[0]": "card",
                    "line_items[0][quantity]": 1, "line_items[0][price_data][currency]": "kes",
                    # Stripe amounts are in the currency's minor unit (cents for KES).
                    "line_items[0][price_data][unit_amount]": amount * 100,
                    "line_items[0][price_data][product_data][name]":
                        f"TALO {subscription['tier'].replace('_', '-')} subscription x{subscription['seats']}",
                    "metadata[reference]": reference, "metadata[subscription_id]": subscription["id"]})
                data = r.json()
                if r.status_code != 200:
                    raise PaymentError((data.get("error") or {}).get("message", "Stripe refused the checkout."))
                provider_ref, url = data["id"], data["url"]
            else:
                r = client.post(f"{FLW_API}/payments", headers={"Authorization": f"Bearer {config.FLW_SECRET_KEY}"},
                                json={"tx_ref": reference, "amount": amount, "currency": "KES",
                                      "redirect_url": success_url, "payment_options": "card",
                                      "customer": {"email": customer_email, "name": institution_name},
                                      "customizations": {"title": "TALO subscription"},
                                      "meta": {"subscription_id": subscription["id"]}})
                data = r.json()
                if r.status_code != 200 or data.get("status") != "success":
                    raise PaymentError(data.get("message", "Flutterwave refused the checkout."))
                provider_ref, url = None, data["data"]["link"]     # Flutterwave's id arrives with the webhook
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        ledger.fail(tx_id, "NETWORK", type(exc).__name__)
        raise PaymentError("Could not reach the card processor. Try again, or pay by M-Pesa.") from exc
    except PaymentError as exc:
        ledger.fail(tx_id, "REFUSED", str(exc))
        raise
    ledger.attach_provider_ref(tx_id, provider_ref, checkout_url=url)
    telemetry.record(f"payment-{reference}", prov, "card_checkout", {"amount": amount},
                     {"provider_ref": provider_ref}, latency_ms=0, actor="institution")
    return {"transaction": ledger.get(tx_id), "checkout_url": url, "mode": status()["mode"]}


# --- simulator ----------------------------------------------------------------------------------------------------
def _simulate(tx_id: int, reference: str, amount: int, result: str) -> dict:
    if result not in ("success", "declined", "pending"):
        raise PaymentError("simulate_result must be success, declined or pending.")
    prov = provider()
    provider_ref = f"cs_test_sim_{secrets.token_hex(8)}" if prov == "stripe" else None
    url = f"{config.PUBLIC_BASE_URL or 'http://127.0.0.1:8000'}/api/payments/card/return?ref={reference}&simulated=1"
    ledger.attach_provider_ref(tx_id, provider_ref, checkout_url=url)
    settled = None
    if result != "pending":
        body, headers = simulated_event(reference, amount, provider_ref, paid=result == "success")
        settled = handle_webhook(body, headers)
    return {"transaction": ledger.get(tx_id), "checkout_url": url, "mode": "simulator", "settlement": settled,
            "note": "SIMULATED card payment: no real money moved."}


def simulated_event(reference: str, amount: int, provider_ref: str | None, paid: bool = True) -> tuple[bytes, dict]:
    """A webhook body and headers in the configured provider's exact shape, signed like the provider signs them."""
    if provider() == "stripe":
        event = {"id": f"evt_sim_{secrets.token_hex(6)}", "type": "checkout.session.completed" if paid
                 else "checkout.session.expired",
                 "data": {"object": {"id": provider_ref, "object": "checkout.session", "client_reference_id": reference,
                                     "amount_total": amount * 100, "currency": "kes",
                                     "payment_status": "paid" if paid else "unpaid",
                                     "payment_intent": f"pi_sim_{secrets.token_hex(6)}" if paid else None}}}
        body = json.dumps(event).encode()
        return body, {"stripe-signature": stripe_signature(body, _webhook_secret())}
    event = {"event": "charge.completed", "data": {"id": int(time.time()), "tx_ref": reference, "amount": amount,
                                                   "currency": "KES", "status": "successful" if paid else "failed",
                                                   "flw_ref": f"FLW-SIM-{secrets.token_hex(5)}",
                                                   "payment_type": "card"}}
    return json.dumps(event).encode(), {"verif-hash": _webhook_secret()}


def stripe_signature(body: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# --- webhooks -----------------------------------------------------------------------------------------------------
def _verify_stripe(body: bytes, header: str | None) -> None:
    secret = _webhook_secret()
    if not secret:
        raise PaymentError("STRIPE_WEBHOOK_SECRET is not set; webhook refused.")
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    try:
        ts = int(parts.get("t", ""))
    except ValueError as exc:
        raise PaymentError("Bad Stripe-Signature header.") from exc
    if abs(time.time() - ts) > STRIPE_TOLERANCE_S:
        raise PaymentError("Stripe webhook timestamp outside tolerance.")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    sigs = [v for k, v in (p.split("=", 1) for p in (header or "").split(",") if "=" in p) if k == "v1"]
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise PaymentError("Stripe signature does not match.")


def _verify_flutterwave(header: str | None) -> None:
    secret = _webhook_secret()
    if not secret or not hmac.compare_digest(header or "", secret):
        raise PaymentError("Flutterwave verif-hash does not match.")


def _flw_confirm(tx_id: int | str, reference: str, amount: int) -> bool:
    """Live mode: ask Flutterwave whether the charge really succeeded (never trust the webhook body alone)."""
    with httpx.Client(timeout=config.CARD_TIMEOUT_S) as client:
        r = client.get(f"{FLW_API}/transactions/{int(tx_id)}/verify",
                       headers={"Authorization": f"Bearer {config.FLW_SECRET_KEY}"})
    d = (r.json() or {}).get("data") or {}
    return (r.status_code == 200 and d.get("status") == "successful" and d.get("tx_ref") == reference
            and d.get("currency") == "KES" and float(d.get("amount") or 0) >= amount)


def handle_webhook(body: bytes, headers: dict) -> dict:
    h = {k.lower(): v for k, v in headers.items()}
    prov = provider()
    if prov == "stripe":
        _verify_stripe(body, h.get("stripe-signature"))
    else:
        _verify_flutterwave(h.get("verif-hash"))
    try:
        event = json.loads(body)
    except ValueError as exc:
        raise PaymentError("Webhook body is not JSON.") from exc

    if prov == "stripe":
        obj = (event.get("data") or {}).get("object") or {}
        tx = ledger.find("stripe", reference=str(obj.get("client_reference_id") or ""))
        if tx is None:
            return {"ignored": True, "reason": "no matching checkout"}
        if tx["provider_ref"] and obj.get("id") != tx["provider_ref"]:
            raise PaymentError("Checkout session does not match the transaction.")
        kind = event.get("type")
        if kind not in ("checkout.session.completed", "checkout.session.async_payment_succeeded",
                        "checkout.session.expired", "checkout.session.async_payment_failed"):
            return {"ignored": True, "reason": f"event {kind} not used"}
        paid = kind != "checkout.session.expired" and kind != "checkout.session.async_payment_failed" \
            and obj.get("payment_status") == "paid" and str(obj.get("currency", "")).lower() == "kes"
        return ledger.settle(tx["id"], success=paid, result_code=kind, result_desc=obj.get("payment_status", ""),
                             paid_amount=int(obj.get("amount_total") or 0) // 100,
                             receipt=obj.get("payment_intent") or obj.get("id"),
                             raw={"type": kind, "session": obj.get("id")}, cancelled=kind == "checkout.session.expired")

    data = event.get("data") or {}
    tx = ledger.find("flutterwave", reference=str(data.get("tx_ref") or ""))
    if tx is None:
        return {"ignored": True, "reason": "no matching checkout"}
    paid = data.get("status") == "successful" and str(data.get("currency", "")).upper() == "KES"
    if paid and live():
        paid = _flw_confirm(data.get("id"), tx["reference"], tx["amount"])
    if data.get("id") is not None and not tx["provider_ref"]:
        ledger.attach_provider_ref(tx["id"], str(data["id"]), checkout_url=tx["checkout_url"])
    return ledger.settle(tx["id"], success=paid, result_code=str(data.get("status")), result_desc=event.get("event", ""),
                         paid_amount=int(float(data.get("amount") or 0)), receipt=data.get("flw_ref"),
                         raw={"event": event.get("event"), "id": data.get("id"), "status": data.get("status")})

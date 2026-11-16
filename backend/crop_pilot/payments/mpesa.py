"""Safaricom M-Pesa Daraja: Lipa na M-Pesa Online (STK Push) and its result callback.

Live mode (all of MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_SHORTCODE, MPESA_PASSKEY set and MPESA_SIMULATE
not 1) calls Daraja's sandbox (or production, MPESA_ENV=production). Otherwise a built-in simulator answers with
the same request and callback shapes, so the billing flow can be demoed offline: it settles the payment at once by
feeding a Daraja-shaped callback into the same handler that real callbacks use.
"""
from __future__ import annotations

import base64
import hmac
import re
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from crop_pilot import config
from crop_pilot.core import telemetry
from crop_pilot.payments import ledger
from crop_pilot.payments.ledger import PaymentError

HOSTS = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}
CALLBACK_PATH = "/api/payments/mpesa/callback"
PHONE_RE = re.compile(r"^2547\d{8}$|^2541\d{8}$")
# Simulated outcomes, with Daraja's own result codes.
SIM_RESULTS = {"success": (0, "The service request is processed successfully."),
               "cancelled": (1032, "Request cancelled by user."),
               "insufficient_funds": (1, "The balance is insufficient for the transaction."),
               "timeout": (1037, "DS timeout user cannot be reached."),
               "pending": (None, None)}


def live() -> bool:
    return (not config.MPESA_SIMULATE and all((config.MPESA_CONSUMER_KEY, config.MPESA_CONSUMER_SECRET,
                                               config.MPESA_SHORTCODE, config.MPESA_PASSKEY)))


def status() -> dict:
    return {"mode": "daraja_" + config.MPESA_ENV if live() else "simulator",
            "callback_url_set": bool(callback_url()), "callback_token_set": bool(config.MPESA_CALLBACK_TOKEN)}


def normalise_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if not PHONE_RE.match(digits):
        raise PaymentError("Enter a Safaricom number, e.g. 0712 345 678 or 254712345678.")
    return digits


def callback_url() -> str:
    base = config.MPESA_CALLBACK_URL or (config.PUBLIC_BASE_URL + CALLBACK_PATH if config.PUBLIC_BASE_URL else "")
    if base and config.MPESA_CALLBACK_TOKEN:
        base += ("&" if "?" in base else "?") + f"t={config.MPESA_CALLBACK_TOKEN}"
    return base


def token_ok(token: str | None) -> bool:
    """Callback shared secret. Required whenever one is configured, and always in live mode."""
    if not config.MPESA_CALLBACK_TOKEN:
        return not live()
    return hmac.compare_digest(token or "", config.MPESA_CALLBACK_TOKEN)


def timestamp() -> str:
    return datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")


def password(ts: str) -> str:
    return base64.b64encode(f"{config.MPESA_SHORTCODE}{config.MPESA_PASSKEY}{ts}".encode()).decode()


def _access_token(client: httpx.Client) -> str:
    r = client.get(f"{HOSTS[config.MPESA_ENV]}/oauth/v1/generate", params={"grant_type": "client_credentials"},
                   auth=(config.MPESA_CONSUMER_KEY, config.MPESA_CONSUMER_SECRET))
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise PaymentError("Daraja did not return an access token.")
    return token


def stk_push(subscription: dict, phone: str, simulate_result: str = "success") -> dict:
    """Ask the payer's phone for their M-Pesa PIN. Returns the pending (or, simulated, settled) transaction."""
    if subscription["status"] not in ("PENDING_PAYMENT", "ACTIVE"):
        raise PaymentError(f"Subscription is {subscription['status']}; start a new one.")
    msisdn = normalise_phone(phone)
    reference = ledger.new_reference("MKH")
    is_live = live()
    if is_live and not callback_url():
        raise PaymentError("Set MPESA_CALLBACK_URL (or PUBLIC_BASE_URL) so Daraja can report the payment.")
    tx_id = ledger.open_transaction(subscription, "mpesa", reference, phone=msisdn, simulated=not is_live)
    ts = timestamp()
    body = {"BusinessShortCode": config.MPESA_SHORTCODE or "174379", "Password": password(ts) if is_live else "SIM",
            "Timestamp": ts, "TransactionType": "CustomerPayBillOnline", "Amount": int(subscription["amount_kes"]),
            "PartyA": msisdn, "PartyB": config.MPESA_SHORTCODE or "174379", "PhoneNumber": msisdn,
            "CallBackURL": callback_url() or "http://127.0.0.1:8000" + CALLBACK_PATH,
            "AccountReference": reference[:12], "TransactionDesc": "TALO subscription"}
    if not is_live:
        return _simulate(tx_id, body, simulate_result)
    try:
        with httpx.Client(timeout=config.MPESA_TIMEOUT_S) as client:
            token = _access_token(client)
            r = client.post(f"{HOSTS[config.MPESA_ENV]}/mpesa/stkpush/v1/processrequest", json=body,
                            headers={"Authorization": f"Bearer {token}"})
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except (httpx.HTTPError, ValueError) as exc:
        ledger.fail(tx_id, "NETWORK", f"{type(exc).__name__}")
        raise PaymentError("Could not reach M-Pesa. Try again, or pay by card.") from exc
    if r.status_code != 200 or str(data.get("ResponseCode")) != "0":
        ledger.fail(tx_id, str(data.get("errorCode") or data.get("ResponseCode") or r.status_code),
                    str(data.get("errorMessage") or data.get("ResponseDescription") or "rejected"))
        raise PaymentError(f"M-Pesa refused the request: {data.get('errorMessage') or data.get('ResponseDescription')}")
    ledger.attach_provider_ref(tx_id, data["CheckoutRequestID"], data.get("MerchantRequestID"))
    telemetry.record(f"payment-{reference}", "mpesa", "stk_push", {"amount": body["Amount"]},
                     {"checkout_request_id": data["CheckoutRequestID"]}, latency_ms=0, actor="institution")
    return {"transaction": ledger.get(tx_id), "customer_message": data.get("CustomerMessage"), "mode": status()["mode"]}


def _simulate(tx_id: int, body: dict, result: str) -> dict:
    if result not in SIM_RESULTS:
        raise PaymentError(f"simulate_result must be one of {sorted(SIM_RESULTS)}.")
    checkout_id = f"ws_CO_{body['Timestamp']}{secrets.token_hex(4)}"
    merchant_id = f"SIM-{secrets.token_hex(5)}"
    ledger.attach_provider_ref(tx_id, checkout_id, merchant_id)
    settled = None
    if result != "pending":
        settled = handle_callback(simulated_callback(checkout_id, merchant_id, body["Amount"], body["PhoneNumber"],
                                                     result))
    return {"transaction": ledger.get(tx_id), "mode": "simulator", "settlement": settled,
            "customer_message": "SIMULATED: no real money moved. Success. Request accepted for processing"}


def simulated_callback(checkout_id: str, merchant_id: str, amount: int, phone: str, result: str = "success") -> dict:
    """A callback body in Daraja's exact shape (Body.stkCallback...)."""
    code, desc = SIM_RESULTS[result]
    cb = {"MerchantRequestID": merchant_id, "CheckoutRequestID": checkout_id, "ResultCode": code, "ResultDesc": desc}
    if code == 0:
        cb["CallbackMetadata"] = {"Item": [
            {"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": "SIM" + secrets.token_hex(4).upper()},
            {"Name": "TransactionDate", "Value": int(timestamp())}, {"Name": "PhoneNumber", "Value": int(phone)}]}
    return {"Body": {"stkCallback": cb}}


def handle_callback(payload: dict) -> dict:
    """Daraja's result for an STK Push. Unknown CheckoutRequestIDs are refused; replays change nothing."""
    try:
        cb = payload["Body"]["stkCallback"]
        checkout_id, code = str(cb["CheckoutRequestID"]), int(cb["ResultCode"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PaymentError("Not an STK Push callback.") from exc
    tx = ledger.find("mpesa", provider_ref=checkout_id)
    if tx is None:
        raise PaymentError("Unknown CheckoutRequestID.")
    if tx["merchant_request_id"] and str(cb.get("MerchantRequestID")) != tx["merchant_request_id"]:
        raise PaymentError("MerchantRequestID does not match the request.")
    items = {i.get("Name"): i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])
             if isinstance(i, dict)}
    paid = items.get("Amount")
    return ledger.settle(tx["id"], success=code == 0, result_code=str(code), result_desc=str(cb.get("ResultDesc", "")),
                         paid_amount=int(float(paid)) if paid is not None else None,
                         receipt=str(items["MpesaReceiptNumber"]) if items.get("MpesaReceiptNumber") else None,
                         raw={"stkCallback": {k: v for k, v in cb.items() if k != "CallbackMetadata"},
                              "metadata": {k: v for k, v in items.items() if k != "PhoneNumber"}},
                         cancelled=code == 1032)

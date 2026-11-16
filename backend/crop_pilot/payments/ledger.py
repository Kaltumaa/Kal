"""The `transactions` table: one row per payment attempt; settling a successful one activates its subscription.

Settlement is idempotent (providers retry callbacks) and checks the paid amount against what was asked for.
"""
from __future__ import annotations

import json
import re
import secrets

from crop_pilot.core import telemetry
from crop_pilot.database.db import connect
from crop_pilot.payments import subscriptions


class PaymentError(ValueError):
    """A payment request or callback that cannot be accepted."""


def mask_phone(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return f"{digits[:4]}{'*' * max(0, len(digits) - 6)}{digits[-2:]}" if len(digits) >= 8 else None


def new_reference(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


def open_transaction(subscription: dict, provider: str, reference: str, *, phone: str | None = None,
                     simulated: bool = False) -> int:
    now = telemetry.now_iso()
    with connect() as conn:
        cur = conn.execute("INSERT INTO transactions (institution_id, subscription_id, provider, reference, amount, "
                           "currency, phone_masked, status, simulated, created_at, updated_at) "
                           "VALUES (?,?,?,?,?,'KES',?,'PENDING',?,?,?)",
                           (subscription["institution_id"], subscription["id"], provider, reference,
                            subscription["amount_kes"], mask_phone(phone), int(simulated), now, now))
        return cur.lastrowid


def attach_provider_ref(tx_id: int, provider_ref: str | None, merchant_request_id: str | None = None,
                        checkout_url: str | None = None) -> None:
    with connect() as conn:
        conn.execute("UPDATE transactions SET provider_ref=?, merchant_request_id=?, checkout_url=?, updated_at=? "
                     "WHERE id=?", (provider_ref, merchant_request_id, checkout_url, telemetry.now_iso(), tx_id))


def fail(tx_id: int, code: str, desc: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE transactions SET status='FAILED', result_code=?, result_desc=?, updated_at=? "
                     "WHERE id=? AND status='PENDING'", (code, desc[:300], telemetry.now_iso(), tx_id))


def get(tx_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id=?", (int(tx_id),)).fetchone()
    return _public(row)


def find(provider: str, *, provider_ref: str | None = None, reference: str | None = None) -> dict | None:
    with connect() as conn:
        if provider_ref:
            row = conn.execute("SELECT * FROM transactions WHERE provider=? AND provider_ref=?",
                               (provider, provider_ref)).fetchone()
        else:
            row = conn.execute("SELECT * FROM transactions WHERE provider=? AND reference=?",
                               (provider, reference)).fetchone()
    return dict(row) if row else None


def _public(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d.pop("raw_callback_json", None)
    d["simulated"] = bool(d["simulated"])
    return d


def list_for(institution_id: int) -> list[dict]:
    with connect() as conn:
        return [_public(r) for r in conn.execute("SELECT * FROM transactions WHERE institution_id=? ORDER BY id DESC",
                                                 (int(institution_id),))]


def settle(tx_id: int, *, success: bool, result_code: str, result_desc: str, paid_amount: int | None = None,
           receipt: str | None = None, raw: object = None, cancelled: bool = False) -> dict:
    """Record the provider's verdict. Success with the right amount activates the subscription in the same commit."""
    with connect() as conn:
        tx = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if tx is None:
            raise PaymentError("Unknown transaction.")
        if tx["status"] != "PENDING":                  # provider retry: answer the same, change nothing
            return {"transaction_id": tx_id, "status": tx["status"], "idempotent_replay": True}
        status = "CANCELLED" if cancelled else "FAILED"
        if success:
            if paid_amount is None or int(paid_amount) < tx["amount"]:
                result_code, result_desc = "AMOUNT_MISMATCH", f"paid {paid_amount}, expected {tx['amount']}"
            elif not receipt:
                result_code, result_desc = "NO_RECEIPT", "provider reported success without a receipt"
            else:
                status = "SUCCESS"
        conn.execute("UPDATE transactions SET status=?, result_code=?, result_desc=?, receipt=?, raw_callback_json=?, "
                     "updated_at=? WHERE id=?",
                     (status, str(result_code), (result_desc or "")[:300], receipt if status == "SUCCESS" else None,
                      json.dumps(raw, default=str)[:20_000] if raw is not None else None, telemetry.now_iso(), tx_id))
        sub = subscriptions.activate(conn, tx["subscription_id"], int(paid_amount)) if status == "SUCCESS" else None
    telemetry.record(f"payment-{tx['reference']}", tx["provider"], "payment_settled",
                     {"transaction_id": tx_id, "result_code": result_code},
                     {"status": status, "subscription_status": sub and sub["status"]}, latency_ms=0, actor="provider")
    return {"transaction_id": tx_id, "status": status, "subscription": sub}

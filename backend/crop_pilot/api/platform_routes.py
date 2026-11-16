"""/api routes for accounts (JWT), institutions, billing (M-Pesa Daraja + card) and the escalation queue.

Roles: farmer, extension_officer, institution. Payment callbacks are public but verified (M-Pesa: shared token in the
callback URL + a known CheckoutRequestID; card: provider signature).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from crop_pilot import config
from crop_pilot.accounts import service as accounts
from crop_pilot.accounts.deps import current_user, require_roles
from crop_pilot.accounts.security import AuthError
from crop_pilot.core import weather_sources
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError
from crop_pilot.institutions import service as institutions
from crop_pilot.payments import card, ledger, mpesa, subscriptions
from crop_pilot.payments.ledger import PaymentError
from crop_pilot.payments.subscriptions import SubscriptionError

router = APIRouter(prefix="/api")
institution_only = require_roles("institution")
staff = require_roles("institution", "extension_officer")
officer_only = require_roles("extension_officer")


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthError):
        return HTTPException(401, detail=str(exc))
    if isinstance(exc, SubscriptionError):
        return HTTPException(402, detail=str(exc))
    return HTTPException(400, detail=str(exc))


# --- auth ---------------------------------------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    role: str = Field(..., pattern="^(farmer|institution|extension_officer)$")
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=10, max_length=256)
    full_name: str = Field(..., max_length=80)
    phone: str | None = Field(None, max_length=20)
    household_id: str | None = Field(None, max_length=32)          # farmer
    institution_name: str | None = Field(None, max_length=120)     # institution
    institution_kind: str | None = Field(None, max_length=40)
    county: str | None = Field(None, max_length=60)
    institution_id: int | None = None                              # extension officer: who employs them
    sub_county: str | None = Field(None, max_length=60)
    wards: list[str] | None = Field(None, max_length=30)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


@router.post("/auth/register", status_code=201)
def register(req: RegisterRequest):
    try:
        if req.role == "farmer":
            return accounts.register_farmer(req.email, req.password, req.full_name, req.household_id, req.phone,
                                            req.county, req.sub_county)
        if req.role == "institution":
            if not (req.institution_name and req.institution_kind and req.county):
                raise accounts.AccountError("institution_name, institution_kind and county are required.")
            return accounts.register_institution(req.institution_name, req.institution_kind, req.county, req.email,
                                                 req.password, req.full_name, req.phone)
        if not (req.institution_id and req.county and req.sub_county):
            raise accounts.AccountError("institution_id, county and sub_county are required.")
        return accounts.register_officer(req.email, req.password, req.full_name, req.institution_id, req.county,
                                         req.sub_county, req.wards, req.phone)
    except (accounts.AccountError, AuthError) as exc:
        raise HTTPException(400, detail=str(exc))


@router.get("/institutions")
def institutions_list():
    """Institutions an extension officer can choose when signing up."""
    return accounts.list_institutions()


@router.post("/auth/login")
def login(req: LoginRequest):
    try:
        return accounts.login(req.email, req.password)
    except AuthError as exc:
        raise HTTPException(401, detail=str(exc))


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return accounts.public(user)


# --- institution --------------------------------------------------------------------------------------------------
class OfficerRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=10, max_length=256)
    full_name: str = Field(..., max_length=80)
    county: str = Field(..., max_length=60)
    sub_county: str = Field(..., max_length=60)
    wards: list[str] | None = Field(None, max_length=30)
    phone: str | None = Field(None, max_length=20)


@router.get("/institution/officers")
def institution_officers(user: dict = Depends(staff)):
    """Each officer's caseload, pending human approvals, average response time, resolved vs escalated cases, and
    the workload per sub-county."""
    return institutions.officer_analytics(user["institution_id"])


@router.post("/institution/officers", status_code=201)
def onboard_officer(req: OfficerRequest, user: dict = Depends(institution_only)):
    try:
        return institutions.onboard_officer(user, req.email, req.password, req.full_name, req.county, req.sub_county,
                                            req.wards, req.phone)
    except (SubscriptionError, ApprovalError, accounts.AccountError, AuthError) as exc:
        raise _http(exc)


@router.get("/institution/farmers")
def institution_farmers(user: dict = Depends(institution_only)):
    """Farmers this institution pays for (KES 50 each) and farmers in its county still waiting for a seat."""
    return institutions.farmers(user["institution_id"])


@router.get("/institution/officers/pending")
def pending_officers(user: dict = Depends(institution_only)):
    return institutions.pending_officers(user["institution_id"])


@router.post("/institution/officers/{officer_id}/approve")
def approve_officer(officer_id: int, user: dict = Depends(institution_only)):
    try:
        return institutions.decide_officer(user, officer_id, approve=True)
    except (SubscriptionError, ApprovalError) as exc:
        raise _http(exc)


@router.post("/institution/officers/{officer_id}/reject")
def reject_officer(officer_id: int, user: dict = Depends(institution_only)):
    try:
        return institutions.decide_officer(user, officer_id, approve=False)
    except ApprovalError as exc:
        raise _http(exc)


class LeadFarmerRequest(BaseModel):
    household_id: str = Field(..., max_length=32)


@router.post("/institution/lead-farmers")
def designate_lead_farmer(req: LeadFarmerRequest, user: dict = Depends(institution_only)):
    try:
        return institutions.designate_lead_farmer(user, req.household_id)
    except accounts.AccountError as exc:
        raise _http(exc)


class BulkAlertRequest(BaseModel):
    sub_county: str = Field(..., max_length=60)
    message: str = Field(..., max_length=320)
    wards: list[str] | None = Field(None, max_length=30)


@router.post("/institution/alerts/bulk")
def bulk_alert(req: BulkAlertRequest, user: dict = Depends(staff)):
    try:
        return institutions.bulk_alert(user, req.sub_county, req.message, req.wards)
    except (SubscriptionError, ApprovalError) as exc:
        raise _http(exc)


@router.get("/institution/subscription")
def institution_subscription(user: dict = Depends(staff)):
    return {"entitlement": subscriptions.entitlement(user["institution_id"]),
            "subscriptions": subscriptions.list_for(user["institution_id"]),
            "transactions": ledger.list_for(user["institution_id"]), "tiers": config.SUBSCRIPTION_TIERS}


class SubscriptionRequest(BaseModel):
    tier: str = Field("per_farmer", pattern="^per_farmer$")
    seats: int = Field(1, ge=1, le=100_000, description="number of farmers to pay for")
    sub_counties: list[str] | None = Field(None, max_length=50)


@router.post("/institution/subscriptions", status_code=201)
def create_subscription(req: SubscriptionRequest, user: dict = Depends(institution_only)):
    try:
        return subscriptions.create(user["institution_id"], req.tier, req.seats, req.sub_counties)
    except SubscriptionError as exc:
        raise HTTPException(400, detail=str(exc))


# --- escalations (human-in-the-loop) --------------------------------------------------------------------------------
@router.get("/escalations")
def escalations(status: str | None = Query("OPEN", pattern="^(OPEN|RESOLVED)$"), user: dict = Depends(staff)):
    return institutions.list_escalations(user, status)


class ResolveRequest(BaseModel):
    diagnosis: str = Field(..., max_length=1200)


@router.post("/escalations/{escalation_id}/resolve")
def resolve_escalation(escalation_id: int, req: ResolveRequest, user: dict = Depends(officer_only)):
    try:
        return institutions.resolve_escalation(user, escalation_id, req.diagnosis)
    except ApprovalError as exc:
        raise HTTPException(400, detail=str(exc))


# --- payments -----------------------------------------------------------------------------------------------------
@router.get("/payments/status")
def payments_status():
    return {"mpesa": mpesa.status(), "card": card.status()}


class StkPushRequest(BaseModel):
    subscription_id: int
    phone: str = Field(..., max_length=20)
    simulate_result: str = Field("success", pattern="^(success|cancelled|insufficient_funds|timeout|pending)$")


@router.post("/payments/mpesa/stkpush")
def mpesa_stkpush(req: StkPushRequest, user: dict = Depends(institution_only)):
    try:
        sub = subscriptions.for_institution(user["institution_id"], req.subscription_id)
        return mpesa.stk_push(sub, req.phone, req.simulate_result)
    except (PaymentError, SubscriptionError) as exc:
        raise _http(exc)


@router.post("/payments/mpesa/callback")
async def mpesa_callback(request: Request, t: str | None = None):
    """Daraja posts the STK Push result here. Always answers in Daraja's ack shape."""
    if not mpesa.token_ok(t):
        raise HTTPException(403, detail="bad token")
    try:
        payload = await request.json()
        result = mpesa.handle_callback(payload)
    except PaymentError as exc:
        return {"ResultCode": 1, "ResultDesc": f"Rejected: {exc}"}
    except ValueError:
        return {"ResultCode": 1, "ResultDesc": "Rejected: body is not JSON"}
    return {"ResultCode": 0, "ResultDesc": "Accepted", "status": result["status"]}


@router.get("/payments/transactions/{transaction_id}")
def transaction(transaction_id: int, user: dict = Depends(staff)):
    tx = ledger.get(transaction_id)
    if tx is None or tx["institution_id"] != user["institution_id"]:
        raise HTTPException(404, detail="Transaction not found.")
    return tx


class CardCheckoutRequest(BaseModel):
    subscription_id: int
    simulate_result: str = Field("success", pattern="^(success|declined|pending)$")


@router.post("/payments/card/checkout")
def card_checkout(req: CardCheckoutRequest, user: dict = Depends(institution_only)):
    try:
        sub = subscriptions.for_institution(user["institution_id"], req.subscription_id)
        with connect() as conn:
            inst = conn.execute("SELECT name FROM institutions WHERE id = ?", (user["institution_id"],)).fetchone()
        return card.checkout(sub, user["email"], inst["name"] if inst else "Institution", req.simulate_result)
    except (PaymentError, SubscriptionError) as exc:
        raise _http(exc)


@router.post("/payments/card/webhook")
async def card_webhook(request: Request):
    body = await request.body()
    try:
        return card.handle_webhook(body, dict(request.headers))
    except PaymentError as exc:
        raise HTTPException(400, detail=str(exc))


@router.get("/payments/card/return")
def card_return(ref: str = Query(..., max_length=40), status: str | None = Query(None, max_length=20)):
    """Where the card page sends the payer back. Informational only: the webhook is what settles the payment."""
    for prov in ("stripe", "flutterwave"):
        tx = ledger.find(prov, reference=ref)
        if tx:
            return {"reference": ref, "status": tx["status"], "returned_with": status,
                    "note": "The payment is confirmed by the processor's webhook, not by this page."}
    raise HTTPException(404, detail="Unknown reference.")


# --- weather ------------------------------------------------------------------------------------------------------
@router.get("/weather/{zone_id}")
def weather(zone_id: str, user: dict = Depends(current_user)):
    """Cross-verified forecast for a ward: Open-Meteo and Visual Crossing, with failover and the cached baseline."""
    return weather_sources.dual_forecast(zone_id, run_id=f"api-weather-{user['id']}")

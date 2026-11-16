"""Who may call each route of the main API (127.0.0.1:8000). Applied to every route as an app-wide dependency.

* Public, no sign-in: /health, the API docs, the sign-up/login routes under /api (they check their own tokens),
  and the carrier / WhatsApp / payment webhooks (verified by their own tokens and signatures).
* /farms without a token returns only farm IDs and wards (the farmer sign-up picker); names need a sign-in.
* Extension officers: every route.
* Institutions: read-only (GET); their own actions live under /api/institution.
* Farmers: their own farm's routes only (household id in the path or query must be theirs), plus the shared
  learning hub, community board, greenhouse check and speech-to-text.

Officer signatures: wherever an officer types their name to sign, it must be the signed-in account's own name, so a
signature always belongs to a real, logged-in officer (sign()).
"""
from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from crop_pilot.accounts import service as accounts
from crop_pilot.accounts.security import AuthError, decode_token
from crop_pilot.core import sanitizer
from crop_pilot.database.db import DatabaseUnavailable, connect

_bearer = HTTPBearer(auto_error=False)

PUBLIC_EXACT = {"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
PUBLIC_PREFIX = ("/api/", "/voice/callback", "/voice/dtmf", "/whatsapp/webhook")
OPTIONAL = {("GET", "/farms")}                       # anonymous callers get a reduced list

OWN_FARM = [re.compile(p) for p in (
    r"^/farms/(?P<hid>[^/]+)/(actions|reminders|photos|notifications|language|cell|cell/photos)$",
    r"^/households/(?P<hid>[^/]+)/profile$",
)]
FARMER_GET = [re.compile(p) for p in (
    r"^/farms$", r"^/overview$", r"^/knowledge(/.*)?$", r"^/forum(/topics)?$", r"^/greenhouse/readings$",
    r"^/speech/status$", r"^/integrations$", r"^/cells$", r"^/sms$",
)]
FARMER_POST = [re.compile(p) for p in (
    r"^/forum$", r"^/greenhouse/(assess|check|readings)$", r"^/speech/transcribe$", r"^/knowledge/suitability$",
    r"^/sms/inbound$", r"^/reminders/(?P<rid>\d+)/done$",
)]


def _deny(msg: str = "Your account cannot do this.") -> HTTPException:
    return HTTPException(403, detail=msg)


def _user_from(creds: HTTPAuthorizationCredentials | None, path: str) -> dict | None:
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    try:
        claims = decode_token(creds.credentials)
    except AuthError:
        raise HTTPException(401, detail="Your sign-in has expired. Sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        user = accounts.get_user(int(claims["sub"]))
    except DatabaseUnavailable:
        if path.startswith("/fallback/manual"):      # the paper-form backup must work while the database is down
            return {"id": int(claims["sub"]), "role": claims.get("role"), "full_name": claims.get("name"),
                    "household_id": None, "active": 1}
        raise HTTPException(503, detail="database_unavailable")
    if user is None or not user["active"] or user["role"] != claims.get("role"):
        raise HTTPException(401, detail="Account not active.", headers={"WWW-Authenticate": "Bearer"})
    return user


def _farmer_allowed(request: Request, user: dict) -> bool:
    path, method = request.url.path, request.method
    own = (user.get("household_id") or "").upper()
    for rx in OWN_FARM:
        m = rx.match(path)
        if m:
            return bool(own) and sanitizer.normalise_text(m["hid"]).upper() == own
    rules = FARMER_GET if method == "GET" else FARMER_POST if method == "POST" else []
    for rx in rules:
        m = rx.match(path)
        if not m:
            continue
        if path == "/sms":
            return bool(own) and (request.query_params.get("household_id") or "").upper() == own
        if "rid" in m.groupdict():
            with connect() as conn:
                row = conn.execute("SELECT household_id FROM farmer_reminders WHERE id = ?",
                                   (int(m["rid"]),)).fetchone()
            return bool(row) and bool(own) and row["household_id"].upper() == own
        return True
    return False


def guard(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    path, method = request.url.path, request.method
    request.state.user = None
    if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIX):
        return
    user = _user_from(creds, path)
    request.state.user = user
    if user is None:
        if (method, path) in OPTIONAL:
            return
        raise HTTPException(401, detail="Sign in first.", headers={"WWW-Authenticate": "Bearer"})
    role = user["role"]
    if role == "extension_officer":
        return
    if role == "institution":
        if method == "GET":
            return
        raise _deny("Institutions can view this but not change it.")
    if role == "farmer" and _farmer_allowed(request, user):
        return
    raise _deny()


def current(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def own_household(request: Request, household_id: str | None) -> None:
    """For routes a farmer may use with a household id in the body: it must be their own farm."""
    user = current(request)
    if user and user["role"] == "farmer":
        if not household_id or household_id.strip().upper() != (user.get("household_id") or "").upper():
            raise _deny("You can only do this for your own farm.")


def _norm(name: str | None) -> str:
    return " ".join(sanitizer.normalise_text(name).lower().split())


def sign(request: Request, typed_name: str | None) -> str:
    """The typed signature must be the signed-in officer's own full name. Returns the account's name."""
    user = current(request)
    if user is None:
        raise HTTPException(401, detail="Sign in first.")
    account = user.get("full_name") or ""
    if not _norm(typed_name):
        raise HTTPException(400, detail="Type your full name to sign.")
    if _norm(typed_name) != _norm(account):
        raise HTTPException(403, detail=f"Sign with your own name as on your account ({account}).")
    return account

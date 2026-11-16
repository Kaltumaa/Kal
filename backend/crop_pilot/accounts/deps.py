"""FastAPI dependencies: who is calling (from the Bearer JWT) and whether their role may use a route."""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from crop_pilot.accounts import service
from crop_pilot.accounts.security import AuthError, decode_token

_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(401, detail="Sign in first.", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(creds.credentials)
        user = service.get_user(int(claims["sub"]))
    except (AuthError, ValueError):
        raise HTTPException(401, detail="Invalid or expired token.", headers={"WWW-Authenticate": "Bearer"})
    # The role in the token must still be the account's role (a demoted or deactivated account loses access at once).
    if user is None or not user["active"] or user["role"] != claims.get("role"):
        raise HTTPException(401, detail="Account not active.", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_roles(*roles: str) -> Callable[..., dict]:
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, detail=f"This needs a {' or '.join(r.replace('_', ' ') for r in roles)} account.")
        return user
    return dependency

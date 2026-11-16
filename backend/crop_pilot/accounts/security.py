"""Password hashing (stdlib scrypt, salted, constant-time compare) and JWT access tokens (PyJWT, HS256)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from crop_pilot import config

# scrypt cost: n=2**14, r=8, p=1 (~16 MB, tens of ms). Stored as scrypt$n$r$p$salt$hash so the cost can be raised.
_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32
MIN_PASSWORD_LEN = 10

# Used only when JWT_SECRET is not set: tokens then stop working on restart, which is safe for a demo.
_EPHEMERAL_SECRET = secrets.token_hex(32)


class AuthError(ValueError):
    """Bad credentials, bad token or a role that may not do this."""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(password) > 256:
        raise AuthError("Password is too long.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        got = hashlib.scrypt((password or "").encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


def _secret() -> str:
    return config.JWT_SECRET or _EPHEMERAL_SECRET


def create_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user["id"]), "role": user["role"], "institution_id": user.get("institution_id"),
              "name": user.get("full_name"),
              "iat": now, "exp": now + timedelta(minutes=config.JWT_TTL_MINUTES), "iss": "mkulima-hub"}
    return jwt.encode(claims, _secret(), algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _secret(), algorithms=[config.JWT_ALGORITHM], issuer="mkulima-hub",
                          options={"require": ["exp", "sub", "role"]})
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token.") from exc

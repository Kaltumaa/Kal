"""Accounts for the three roles: farmer, extension officer, institution (County Agric Department, cooperative, NGO).

* Farmers and institutions register themselves.
* Extension officers are onboarded by their institution (crop_pilot.institutions.service), which needs an active,
  paid subscription with a free seat. An officer always belongs to an institution, a county and a sub-county.
* A Lead Farmer is a farmer account an institution designates; it is linked to that institution, county and
  sub-county, and to the Lead Farmer cell the household leads.
"""
from __future__ import annotations

import re
import sqlite3

from crop_pilot import config
from crop_pilot.accounts.security import AuthError, create_token, hash_password, verify_password
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\-.]+(?: [A-Za-z][A-Za-z'\-.]+)+$")
PUBLIC_FIELDS = ("id", "email", "full_name", "role", "institution_id", "county", "sub_county", "wards",
                 "household_id", "is_lead_farmer", "active", "approval_status", "phone", "created_at",
                 "last_login_at")
# Dummy hash so a login for an unknown e-mail costs the same as a wrong password (no account enumeration by timing).
_DUMMY_HASH = hash_password("timing-equaliser-not-a-password")


class AccountError(ValueError):
    """Invalid registration or account change (shown to the user)."""


def public(user: dict | sqlite3.Row | None) -> dict | None:
    if user is None:
        return None
    u = dict(user)
    out = {k: u.get(k) for k in PUBLIC_FIELDS}
    out["is_lead_farmer"] = bool(out["is_lead_farmer"])
    out["active"] = bool(out["active"])
    if u.get("role") == "farmer":            # farmers get in only while an institution pays for their seat
        from crop_pilot.payments import subscriptions
        out["access"] = subscriptions.farmer_access(u)
    return out


def _email(value: str) -> str:
    email = sanitizer.normalise_text(value).lower()
    if not EMAIL_RE.match(email):
        raise AccountError("Enter a valid e-mail address.")
    return email


def _name(value: str) -> str:
    name = sanitizer.normalise_text(value)
    if not (5 <= len(name) <= 80) or not NAME_RE.match(name) or sanitizer.detect_injection(name):
        raise AccountError("Enter a full name (first and last name, letters only).")
    return name


def _place(value: str | None, label: str) -> str:
    text = sanitizer.normalise_text(value)
    if not (2 <= len(text) <= 60) or not re.match(r"^[A-Za-z][A-Za-z '\-]+$", text):
        raise AccountError(f"Enter a valid {label}.")
    return text.title()


def _insert_user(conn, **fields) -> int:
    fields.setdefault("created_at", telemetry.now_iso())
    cols = ", ".join(fields)
    try:
        cur = conn.execute(f"INSERT INTO users ({cols}) VALUES ({', '.join('?' * len(fields))})",   # fixed names
                           tuple(fields.values()))
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc):
            raise AccountError("An account with this e-mail already exists.") from exc
        raise AccountError("Account details are incomplete for this role.") from exc
    return cur.lastrowid


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
    return dict(row) if row else None


def _session(user: dict) -> dict:
    return {"access_token": create_token(user), "token_type": "bearer", "expires_in_minutes": config.JWT_TTL_MINUTES,
            "user": public(user)}


def register_institution(name: str, kind: str, county: str, admin_email: str, admin_password: str,
                         admin_name: str, contact_phone: str | None = None) -> dict:
    """An institution signs up; its first account (role `institution`) manages officers and billing."""
    inst_name = sanitizer.normalise_text(name)
    if not (3 <= len(inst_name) <= 120) or sanitizer.detect_injection(inst_name):
        raise AccountError("Enter the institution's name.")
    if kind not in config.INSTITUTION_KINDS:
        raise AccountError(f"Institution type must be one of {list(config.INSTITUTION_KINDS)}.")
    county_name = _place(county, "county")
    email, full_name = _email(admin_email), _name(admin_name)
    pw_hash = hash_password(admin_password)
    with connect() as conn:
        try:
            inst_id = conn.execute("INSERT INTO institutions (name, kind, county, contact_email, contact_phone, "
                                   "created_at) VALUES (?,?,?,?,?,?)",
                                   (inst_name, kind, county_name, email, contact_phone, telemetry.now_iso())).lastrowid
        except sqlite3.IntegrityError as exc:
            raise AccountError("An institution with this name is already registered.") from exc
        uid = _insert_user(conn, email=email, password_hash=pw_hash, full_name=full_name, role="institution",
                           institution_id=inst_id, county=county_name, phone=contact_phone)
        user = dict(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    telemetry.record(f"inst-{inst_id}", "accounts", "register_institution", {"name": inst_name, "kind": kind},
                     {"institution_id": inst_id, "user_id": uid}, latency_ms=0, actor=full_name)
    return {"institution": {"id": inst_id, "name": inst_name, "kind": kind, "county": county_name}, **_session(user)}


def register_farmer(email: str, password: str, full_name: str, household_id: str | None = None,
                    phone: str | None = None, county: str | None = None, sub_county: str | None = None) -> dict:
    """A farmer creates an account, linked to their farm record or at least their county and sub-county. Access is
    paid by an institution (KES 50 per farmer): a free seat in their sub-county is taken at once if there is one."""
    from crop_pilot.payments import subscriptions
    hid = sanitizer.normalise_text(household_id).upper()[:32] or None
    county = _place(county, "county") if county else None
    sub_county = _place(sub_county, "sub-county") if sub_county else None
    with connect() as conn:
        if hid:
            plot = conn.execute("SELECT zone_id FROM plots WHERE household_id = ?", (hid,)).fetchone()
            if plot is None:
                raise AccountError("That farm ID was not found. Ask your extension officer for it.")
            if conn.execute("SELECT 1 FROM users WHERE household_id = ? AND role = 'farmer'", (hid,)).fetchone():
                raise AccountError("This farm already has an account.")
            county, sub_county = config.ward_location(sanitizer.normalise_zone(plot["zone_id"]))
        if not sub_county:
            raise AccountError("Choose your farm, or enter your county and sub-county.")
        uid = _insert_user(conn, email=_email(email), password_hash=hash_password(password),
                           full_name=_name(full_name), role="farmer", household_id=hid, phone=phone,
                           county=county, sub_county=sub_county)
        subscriptions.sponsor_new_farmer(conn, uid, sub_county)
        user = dict(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    return _session(user)


def create_officer(institution_id: int, email: str, password: str, full_name: str, county: str, sub_county: str,
                   wards: list[str] | None = None, phone: str | None = None) -> dict:
    """Called only through institutions.service.onboard_officer (subscription and seat checks happen there)."""
    clean_wards = sorted({sanitizer.normalise_zone(w) for w in wards or [] if sanitizer.normalise_zone(w)})
    with connect() as conn:
        uid = _insert_user(conn, email=_email(email), password_hash=hash_password(password),
                           full_name=_name(full_name), role="extension_officer", institution_id=int(institution_id),
                           county=_place(county, "county"), sub_county=_place(sub_county, "sub-county"),
                           wards=",".join(clean_wards) or None, phone=phone)
        return public(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())


def list_institutions() -> list[dict]:
    """Public list for the officer sign-up form (no contact details)."""
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name, kind, county FROM institutions ORDER BY name")]


def register_officer(email: str, password: str, full_name: str, institution_id: int, county: str, sub_county: str,
                     wards: list[str] | None = None, phone: str | None = None) -> dict:
    """An extension officer signs up. The account stays inactive until their institution approves it, which uses
    one of the institution's paid seats (institutions.service.decide_officer)."""
    with connect() as conn:
        inst = conn.execute("SELECT id, name, county FROM institutions WHERE id = ?", (int(institution_id),)).fetchone()
    if inst is None:
        raise AccountError("Choose your institution.")
    if inst["county"].lower() != _place(county, "county").lower():
        raise AccountError(f"{inst['name']} works in {inst['county']} County only.")
    clean_wards = sorted({sanitizer.normalise_zone(w) for w in wards or [] if sanitizer.normalise_zone(w)})
    with connect() as conn:
        uid = _insert_user(conn, email=_email(email), password_hash=hash_password(password),
                           full_name=_name(full_name), role="extension_officer", institution_id=inst["id"],
                           county=_place(county, "county"), sub_county=_place(sub_county, "sub-county"),
                           wards=",".join(clean_wards) or None, phone=phone, active=0, approval_status="pending")
        user = public(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    telemetry.record(f"inst-{inst['id']}", "accounts", "officer_signup", {"sub_county": user["sub_county"]},
                     {"user_id": uid, "status": "pending"}, latency_ms=0, actor=user["full_name"])
    return {"user": user, "status": "pending",
            "message": f"Account created. {inst['name']} must approve it before you can sign in."}


def designate_lead_farmer(institution_id: int, household_id: str) -> dict:
    """Mark a farmer account as a Lead Farmer for an institution, in the farm's county and sub-county."""
    hid = sanitizer.normalise_text(household_id).upper()[:32]
    with connect() as conn:
        plot = conn.execute("SELECT zone_id FROM plots WHERE household_id = ?", (hid,)).fetchone()
        if plot is None:
            raise AccountError("Farm not found.")
        user = conn.execute("SELECT * FROM users WHERE household_id = ? AND role = 'farmer'", (hid,)).fetchone()
        if user is None:
            raise AccountError("This farm has no farmer account yet; the farmer must register first.")
        county, sub_county = config.ward_location(sanitizer.normalise_zone(plot["zone_id"]))
        if sub_county is None:
            raise AccountError("This farm's ward is not in a known sub-county.")
        conn.execute("UPDATE users SET is_lead_farmer = 1, institution_id = ?, county = ?, sub_county = ? "
                     "WHERE id = ?", (int(institution_id), county, sub_county, user["id"]))
        conn.execute("UPDATE lead_farmer_cells SET institution_id = ?, county = ?, sub_county = ? "
                     "WHERE lead_household_id = ?", (int(institution_id), county, sub_county, hid))
        cells = [r["cell_id"] for r in conn.execute("SELECT cell_id FROM lead_farmer_cells WHERE lead_household_id = ?",
                                                    (hid,))]
        updated = public(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
    return {"lead_farmer": updated, "cells": cells}


def login(email: str, password: str) -> dict:
    try:
        addr = _email(email)
    except AccountError:
        addr = ""
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (addr,)).fetchone() if addr else None
        ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
        if row is None or not ok:
            raise AuthError("Wrong e-mail or password.")
        status = row["approval_status"] if "approval_status" in row.keys() else "approved"
        if status == "pending":
            raise AuthError("Your account is waiting for your institution to approve it.")
        if status == "rejected" or not row["active"]:
            raise AuthError("This account is not active. Contact your institution.")
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (telemetry.now_iso(), row["id"]))
        user = dict(row)
    return _session(user)

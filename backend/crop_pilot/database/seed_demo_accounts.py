"""Create one demo login per role on the local database, and write the logins to data/demo_accounts.md.

    PYTHONPATH=backend python -m crop_pilot.database.seed_demo_accounts            # create missing accounts
    PYTHONPATH=backend python -m crop_pilot.database.seed_demo_accounts --reset    # also give them new passwords

Accounts (all synthetic):
* Institution:          Nairobi County Agriculture Department, paid by the M-Pesa SIMULATOR for 15 farmers in
                        Dagoretti South (KES 750; no real money).
* Extension officer:    signs up for that institution and is approved by it.
* Farmer:               Grace Wanjiku, farm HH-DS-003 (access paid by the institution).
* Lead Farmer:          Peter Njoroge, farm HH-DS-001, designated by the institution (cell RIR-1).

Passwords are random and written only to data/demo_accounts.md, which git ignores. Never use these on a server
anyone else can reach.
"""
from __future__ import annotations

import argparse
import secrets

from crop_pilot import config
from crop_pilot.accounts import service as accounts
from crop_pilot.accounts.security import hash_password
from crop_pilot.database.db import connect
from crop_pilot.database.init_db import ensure_schema, init_db
from crop_pilot.payments import mpesa, subscriptions

OUT = config.DATA_DIR / "demo_accounts.md"
INSTITUTION = "Nairobi County Agriculture Department"
ACCOUNTS = [
    # key, role, e-mail, name, extra
    ("institution", "institution", "institution@talo.demo", "Amina Odhiambo", {}),
    ("officer", "extension_officer", "officer@talo.demo", "Wanjiru Kamau", {}),
    ("farmer", "farmer", "farmer@talo.demo", "Grace Wanjiku", {"household_id": "HH-DS-003"}),
    ("lead_farmer", "farmer", "leadfarmer@talo.demo", "Peter Njoroge", {"household_id": "HH-DS-001"}),
]


def _password() -> str:
    return "talo-" + secrets.token_urlsafe(9)


def _user(email: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def seed(reset: bool = False) -> dict[str, str | None]:
    if not config.DB_PATH.exists():
        init_db()
    with connect() as conn:
        ensure_schema(conn)
    passwords: dict[str, str | None] = {}

    inst_user = _user("institution@talo.demo")
    if inst_user is None:
        passwords["institution"] = _password()
        inst = accounts.register_institution(INSTITUTION, "county_agric_department", "Nairobi",
                                             "institution@talo.demo", passwords["institution"], "Amina Odhiambo",
                                             "+254700000900")
        inst_id = inst["institution"]["id"]
    else:
        inst_id = inst_user["institution_id"]

    if not subscriptions.entitlement(inst_id)["active"]:          # pay through the M-Pesa simulator
        sub = subscriptions.create(inst_id, "per_farmer", 15, ["Dagoretti South"])
        prev = config.MPESA_SIMULATE
        config.MPESA_SIMULATE = True
        try:
            mpesa.stk_push(sub, "0700000900", "success")
        finally:
            config.MPESA_SIMULATE = prev

    if _user("officer@talo.demo") is None:
        passwords["officer"] = _password()
        reg = accounts.register_officer("officer@talo.demo", passwords["officer"], "Wanjiru Kamau", inst_id,
                                        "Nairobi", "Dagoretti South", None, "+254700000901")
        with connect() as conn:                                     # the institution approves its officer
            conn.execute("UPDATE users SET approval_status='approved', active=1, approved_by=? WHERE id=?",
                         ("Amina Odhiambo", reg["user"]["id"]))

    for key, _, email, name, extra in ACCOUNTS[2:]:
        if _user(email) is None:
            with connect() as conn:                                 # a farm can have only one account
                taken = conn.execute("SELECT email FROM users WHERE household_id = ? AND role = 'farmer'",
                                     (extra["household_id"],)).fetchone()
            if taken:
                print(f"skipped {email}: farm {extra['household_id']} already has an account ({taken['email']})")
                continue
            passwords[key] = _password()
            accounts.register_farmer(email, passwords[key], name, extra["household_id"])
    if _user("leadfarmer@talo.demo"):
        accounts.designate_lead_farmer(inst_id, "HH-DS-001")
    with connect() as conn:                                         # farmers who joined before the payment
        subscriptions.assign_seats(conn, inst_id)

    if reset:
        for key, _, email, _, _ in ACCOUNTS:
            if _user(email) and key not in passwords:
                passwords[key] = _password()
                with connect() as conn:
                    conn.execute("UPDATE users SET password_hash = ? WHERE email = ?",
                                 (hash_password(passwords[key]), email))
    return passwords


def write(passwords: dict[str, str | None]) -> None:
    known: dict[str, str] = {}
    if OUT.exists():                                               # keep passwords from earlier runs
        for line in OUT.read_text().splitlines():
            parts = [p.strip(" `") for p in line.split("|")]
            if len(parts) > 4 and "@talo.demo" in parts[3]:
                known[parts[3]] = parts[4]
    rows = []
    for key, role, email, name, extra in ACCOUNTS:
        if _user(email) is None:
            continue
        pw = passwords.get(key) or known.get(email, "(unchanged: run with --reset to set a new one)")
        label = {"institution": f"Institution admin ({INSTITUTION})", "officer": "Extension officer",
                 "farmer": f"Farmer ({extra.get('household_id', '')})",
                 "lead_farmer": f"Lead Farmer ({extra.get('household_id', '')})"}[key]
        rows.append(f"| {label} | {name} | `{email}` | `{pw}` |")
    OUT.write_text("# TALO demo logins (local database only)\n\n"
                   "Synthetic accounts made by `python -m crop_pilot.database.seed_demo_accounts`. This file is "
                   "git-ignored. Do not reuse these passwords anywhere.\n\n"
                   "| Role | Name | E-mail | Password |\n|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
                   "The institution's access for 15 farmers in Dagoretti South was paid through the M-Pesa "
                   "simulator (no real money).\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Create TALO demo logins")
    ap.add_argument("--reset", action="store_true", help="give the demo accounts new passwords")
    args = ap.parse_args()
    write(seed(args.reset))
    print(f"Demo logins written to {OUT}")


if __name__ == "__main__":
    main()

"""Institution subscriptions. Only institutions pay: KES 50 per farmer per 30 days (config.SUBSCRIPTION_TIERS).

A subscription buys N farmer seats in named sub-counties. It is ACTIVE only after a provider (M-Pesa callback or card
webhook) reports a successful payment of the full amount. Then the seats are handed to farmer accounts in those
sub-counties (oldest sign-ups first), and those farmers get access to the platform. A farmer who signs up later gets a
free seat at once if one of the institutions covering their sub-county has one.

Approving officers and sending bulk alerts also need an active subscription (require_active).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect

TIER = "per_farmer"


class SubscriptionError(ValueError):
    """The institution has no usable subscription for this action (shown to the user; HTTP 402)."""


def _names(sub_counties: list[str] | str | None) -> list[str]:
    items = sub_counties.split(",") if isinstance(sub_counties, str) else (sub_counties or [])
    return sorted({sanitizer.normalise_text(s).title() for s in items if sanitizer.normalise_text(s)})


def quote(tier: str, seats: int, sub_counties: list[str] | None = None) -> dict:
    if tier not in config.SUBSCRIPTION_TIERS:
        raise SubscriptionError(f"Plan must be one of {sorted(config.SUBSCRIPTION_TIERS)}.")
    seats, names = int(seats), _names(sub_counties)
    if not names:
        raise SubscriptionError("Choose the sub-counties whose farmers you are paying for.")
    if not 1 <= seats <= 100_000:
        raise SubscriptionError("Number of farmers must be between 1 and 100,000.")
    price = config.SUBSCRIPTION_TIERS[tier]["price_kes"]
    return {"tier": tier, "seats": seats, "sub_counties": names, "unit_price_kes": price,
            "amount_kes": price * seats, "period_days": config.SUBSCRIPTION_PERIOD_DAYS,
            "label": config.SUBSCRIPTION_TIERS[tier]["label"]}


def create(institution_id: int, tier: str, seats: int, sub_counties: list[str] | None = None) -> dict:
    q = quote(tier, seats, sub_counties)
    now = telemetry.now_iso()
    with connect() as conn:
        cur = conn.execute("INSERT INTO subscriptions (institution_id, tier, seats, sub_counties, amount_kes, status, "
                           "created_at, updated_at) VALUES (?,?,?,?,?,'PENDING_PAYMENT',?,?)",
                           (int(institution_id), q["tier"], q["seats"], ",".join(q["sub_counties"]), q["amount_kes"],
                            now, now))
    return get(cur.lastrowid) | {"quote": q}


def _row(conn, subscription_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (int(subscription_id),)).fetchone()
    return dict(row) if row else None


def get(subscription_id: int) -> dict | None:
    with connect() as conn:
        return _row(conn, subscription_id)


def for_institution(institution_id: int, subscription_id: int) -> dict:
    sub = get(subscription_id)
    if sub is None or sub["institution_id"] != int(institution_id):
        raise SubscriptionError("Subscription not found.")
    return sub


def _expire_old(conn) -> None:
    conn.execute("UPDATE subscriptions SET status='EXPIRED', updated_at=? WHERE status='ACTIVE' AND period_end < ?",
                 (telemetry.now_iso(), telemetry.now_iso()))


def list_for(institution_id: int) -> list[dict]:
    with connect() as conn:
        _expire_old(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM subscriptions WHERE institution_id = ? ORDER BY id DESC",
                                              (int(institution_id),))]


def _active(conn, institution_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM subscriptions WHERE institution_id = ? AND status = 'ACTIVE'",
                                          (int(institution_id),))]


def _coverage(subs: list[dict]) -> tuple[int, list[str]]:
    seats = sum(s["seats"] for s in subs if s["tier"] == TIER)
    return seats, sorted({sc for s in subs for sc in _names(s["sub_counties"])})


def assign_seats(conn, institution_id: int) -> list[int]:
    """Give the institution's free farmer seats to waiting farmers in the sub-counties it pays for."""
    _expire_old(conn)
    seats, covered = _coverage(_active(conn, institution_id))
    used = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'farmer' AND sponsor_institution_id = ?",
                        (int(institution_id),)).fetchone()[0]
    free = seats - used
    if free <= 0 or not covered:
        return []
    marks = ",".join("?" * len(covered))
    ids = [r[0] for r in conn.execute(
        f"SELECT id FROM users WHERE role = 'farmer' AND active = 1 AND sponsor_institution_id IS NULL "
        f"AND sub_county IS NOT NULL AND lower(sub_county) IN ({marks}) ORDER BY created_at, id LIMIT ?",
        (*[c.lower() for c in covered], free))]
    for uid in ids:
        conn.execute("UPDATE users SET sponsor_institution_id = ? WHERE id = ?", (int(institution_id), uid))
    return ids


def sponsor_new_farmer(conn, user_id: int, sub_county: str | None) -> int | None:
    """A farmer just signed up: take a free seat from any institution paying for their sub-county."""
    if not sub_county:
        return None
    _expire_old(conn)
    for (inst_id,) in conn.execute("SELECT DISTINCT institution_id FROM subscriptions WHERE status = 'ACTIVE' "
                                   "ORDER BY institution_id").fetchall():
        seats, covered = _coverage(_active(conn, inst_id))
        used = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'farmer' AND sponsor_institution_id = ?",
                            (inst_id,)).fetchone()[0]
        if used < seats and sub_county.lower() in {c.lower() for c in covered}:
            conn.execute("UPDATE users SET sponsor_institution_id = ? WHERE id = ?", (inst_id, int(user_id)))
            return inst_id
    return None


def farmer_access(user: dict) -> dict:
    """Is this farmer's access paid for right now, and by whom?"""
    sponsor = user.get("sponsor_institution_id")
    if not sponsor:
        return {"active": False, "sponsor": None,
                "reason": "No institution has paid for farmers in your sub-county yet."}
    with connect() as conn:
        _expire_old(conn)
        live = bool(_active(conn, sponsor))
        name = conn.execute("SELECT name FROM institutions WHERE id = ?", (sponsor,)).fetchone()
    return {"active": live, "sponsor": name["name"] if name else None,
            "reason": None if live else f"{name['name'] if name else 'Your institution'}'s payment has run out."}


def activate(conn, subscription_id: int, paid_amount: int) -> dict:
    """Called inside the payment transaction once the provider confirms. Extends an active period if one runs, then
    hands the new seats to waiting farmers."""
    sub = _row(conn, subscription_id)
    if sub is None:
        raise SubscriptionError("Subscription not found.")
    if int(paid_amount) < sub["amount_kes"]:
        raise SubscriptionError(f"Paid {paid_amount} KES but {sub['amount_kes']} KES is due.")
    now = datetime.now(timezone.utc)
    start = now
    if sub["status"] == "ACTIVE" and sub["period_end"]:
        start = max(now, datetime.fromisoformat(sub["period_end"]))
    end = start + timedelta(days=config.SUBSCRIPTION_PERIOD_DAYS)
    conn.execute("UPDATE subscriptions SET status='ACTIVE', period_start=COALESCE(period_start, ?), period_end=?, "
                 "updated_at=? WHERE id=?", (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"),
                                             telemetry.now_iso(), sub["id"]))
    assign_seats(conn, sub["institution_id"])
    return _row(conn, sub["id"])


def entitlement(institution_id: int) -> dict:
    """What the institution's ACTIVE subscriptions cover right now."""
    with connect() as conn:
        _expire_old(conn)
        active = _active(conn, institution_id)
        covered_farmers = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'farmer' AND sponsor_institution_id = ?",
                                       (int(institution_id),)).fetchone()[0]
    seats, sub_counties = _coverage(active)
    return {"active": bool(active), "farmer_seats": seats, "farmers_covered": covered_farmers,
            "seats_free": max(0, seats - covered_farmers), "sub_counties": sub_counties,
            "subscriptions": [s["id"] for s in active],
            "valid_until": max((s["period_end"] for s in active), default=None)}


def require_active(institution_id: int, sub_county: str | None = None) -> dict:
    """Raise SubscriptionError unless a paid subscription is running (and covers `sub_county`, if given)."""
    ent = entitlement(institution_id)
    if not ent["active"]:
        raise SubscriptionError("This needs an active, paid subscription. Pay for your farmers by M-Pesa or card "
                                "first.")
    if sub_county and sub_county.strip().title() not in ent["sub_counties"]:
        raise SubscriptionError(f"Your payment does not cover {sub_county}. Add it when you next pay.")
    return ent

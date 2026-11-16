"""WhatsApp channel (Meta WhatsApp Cloud API), next to SMS and voice calls.

Out: when an officer signs advice, farmers with a smartphone also get it on WhatsApp (SMS is still always queued,
because it reaches every phone). In: farmers can message the TALO number on WhatsApp with the same commands as SMS
(LOG / REMIND / PROBLEM / HELP, in English or Kiswahili) and get the reply on WhatsApp.

Live when WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID are set; otherwise every message is SIMULATED (stored, not sent).
WhatsApp only allows free-form text within 24 h of the farmer's last message; outside that window a pre-approved
template is needed, so set WHATSAPP_TEMPLATE (one body parameter) to send officer advice as a template.

Inbound webhooks are verified: the GET handshake needs WHATSAPP_VERIFY_TOKEN, and every POST must carry Meta's
X-Hub-Signature-256 made with WHATSAPP_APP_SECRET (in live mode a missing secret means inbound is refused).
"""
from __future__ import annotations

import hashlib
import hmac
import re

import httpx

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.core.resilience import with_retry
from crop_pilot.database.db import connect

GRAPH_URL = "https://graph.facebook.com"
MAX_TEXT = 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT,
    phone        TEXT NOT NULL,
    direction    TEXT NOT NULL CHECK (direction IN ('IN','OUT')),
    body         TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- advice | reply | command
    related_id   INTEGER,                -- advisory id for advice, inbound message id for replies
    sent_by      TEXT,
    status       TEXT NOT NULL,          -- SENT | SIMULATED | FAILED | RECEIVED
    provider_id  TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL
);
"""


class WhatsAppError(RuntimeError):
    pass


def live() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def status() -> dict:
    return {"channel": "WhatsApp Cloud API" if live() else "WhatsApp (simulated: no WHATSAPP_TOKEN)",
            "live": live(), "template": config.WHATSAPP_TEMPLATE or None,
            "inbound_verified": bool(config.WHATSAPP_APP_SECRET)}


def _ensure(conn) -> None:
    conn.executescript(SCHEMA)


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _farm_phone(household_id: str) -> tuple[str | None, str | None]:
    with connect() as conn:
        row = conn.execute("SELECT phone, phone_type FROM plots WHERE household_id = ?", (household_id,)).fetchone()
    return (row["phone"], row["phone_type"]) if row else (None, None)


def household_for(phone: str) -> str | None:
    """The farm whose phone number matches (ignores +, spaces and a leading 0 vs 254)."""
    d = _digits(phone)
    if not d:
        return None
    tail = d[-9:]                                        # Kenyan mobile: the last 9 digits identify the line
    with connect() as conn:
        for r in conn.execute("SELECT household_id, phone FROM plots WHERE phone IS NOT NULL"):
            if _digits(r["phone"])[-9:] == tail:
                return r["household_id"]
    return None


def _post(payload: dict) -> str:
    url = f"{GRAPH_URL}/{config.WHATSAPP_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    r = httpx.post(url, json=payload, timeout=10, headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"})
    if r.status_code >= 400:
        detail = (r.json().get("error") or {}).get("message") if "json" in r.headers.get("content-type", "") else ""
        raise WhatsAppError(f"WhatsApp HTTP {r.status_code} {detail or ''}".strip())
    return ((r.json().get("messages") or [{}])[0]).get("id") or ""


def _payload(to: str, text: str, template: bool) -> dict:
    if template and config.WHATSAPP_TEMPLATE:
        return {"messaging_product": "whatsapp", "to": to, "type": "template",
                "template": {"name": config.WHATSAPP_TEMPLATE, "language": {"code": config.WHATSAPP_TEMPLATE_LANG},
                             "components": [{"type": "body", "parameters": [{"type": "text", "text": text}]}]}}
    return {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text, "preview_url": False}}


def send(phone: str, text: str, *, household_id: str | None, kind: str, related_id: int | None = None,
         sent_by: str = "system", template: bool = False) -> dict:
    """Send (or simulate) one WhatsApp message and store it. Never raises: a failure is recorded and returned."""
    body = sanitizer.normalise_text(text)[:MAX_TEXT]
    to = _digits(phone)
    status, provider_id, error = "SIMULATED", None, None
    if not to or not body:
        status, error = "FAILED", "no phone number or empty message"
    elif live():
        try:
            provider_id, _, _ = with_retry(lambda: _post(_payload(to, body, template)), attempts=2,
                                           retry_on=(httpx.HTTPError,))
            status = "SENT"
        except Exception as exc:  # noqa: BLE001 - SMS is still queued; report, do not crash the approval
            status, error = "FAILED", str(exc)[:300]
    with connect() as conn:
        _ensure(conn)
        mid = conn.execute("INSERT INTO whatsapp_messages (household_id, phone, direction, body, kind, related_id, "
                           "sent_by, status, provider_id, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (household_id, to or "-", "OUT", body or "(empty)", kind, related_id, sent_by, status,
                            provider_id, error, telemetry.now_iso())).lastrowid
    telemetry.record(f"whatsapp-{household_id or to}", "whatsapp", f"send_{kind}", {"household_id": household_id},
                     {"message_id": mid, "status": status, "error": error}, latency_ms=0, actor=sent_by,
                     status="ok" if status != "FAILED" else "error")
    return {"message_id": mid, "status": status, "error": error}


def send_advice(household_id: str, text: str, advisory_id: int, officer: str) -> dict | None:
    """Officer-signed advice to a smartphone farmer. None when the farm has no smartphone (SMS covers it)."""
    phone, phone_type = _farm_phone(household_id)
    if not phone or (phone_type or "").lower() != "smartphone":
        return None
    return send(phone, text, household_id=household_id, kind="advice", related_id=advisory_id, sent_by=officer,
                template=True)


def receive(phone: str, text: str, provider_id: str | None = None) -> dict:
    """One inbound WhatsApp text: run it through the same commands as SMS and reply on WhatsApp."""
    from crop_pilot.dispatch import sms          # local import: sms imports approval, which imports this lazily

    hid = household_for(phone)
    body, _ = sanitizer.scrub_free_text(text, 300)
    with connect() as conn:
        _ensure(conn)
        in_id = conn.execute("INSERT INTO whatsapp_messages (household_id, phone, direction, body, kind, sent_by, "
                             "status, provider_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (hid, _digits(phone), "IN", body or "(empty)", "command", hid or "unknown", "RECEIVED",
                              provider_id, telemetry.now_iso())).lastrowid
    if hid is None:
        reply = ("This number is not registered with TALO. Ask your extension officer to add your phone to your farm. "
                 "/ Nambari hii haijasajiliwa na TALO. Muulize afisa wa ugani.")
        result = {"command": None, "error": "unknown sender"}
    else:
        result = sms.receive(hid, body, channel="whatsapp")
        reply = result["reply"].replace("SMS", "WhatsApp")      # the shared replies say "reply by SMS"
    out = send(phone, reply, household_id=hid, kind="reply", related_id=in_id)
    return {k: v for k, v in result.items() if k not in ("in_id", "reply_id")} | {
        "household_id": hid, "in_id": in_id, "reply": reply, "reply_status": out["status"]}


def handle_webhook(payload: dict) -> list[dict]:
    """Meta's webhook body -> one receive() per inbound text message. Statuses and other types are ignored."""
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for msg in (change.get("value") or {}).get("messages") or []:
                if msg.get("type") == "text":
                    out.append(receive(msg.get("from", ""), (msg.get("text") or {}).get("body", ""), msg.get("id")))
    return out


def verify_handshake(mode: str | None, token: str | None) -> bool:
    return (mode == "subscribe" and bool(config.WHATSAPP_VERIFY_TOKEN)
            and hmac.compare_digest(token or "", config.WHATSAPP_VERIFY_TOKEN))


def signature_ok(raw: bytes, header: str | None) -> bool:
    """Meta signs each POST with the app secret. Without a secret, only simulated (non-live) mode accepts posts."""
    if not config.WHATSAPP_APP_SECRET:
        return not live()
    want = "sha256=" + hmac.new(config.WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header or "")


def list_messages(household_id: str | None = None, limit: int = 100) -> list[dict]:
    with connect() as conn:
        _ensure(conn)
        q = ("SELECT * FROM whatsapp_messages" + (" WHERE household_id = ?" if household_id else "")
             + " ORDER BY id DESC LIMIT ?")
        return [dict(r) for r in conn.execute(q, ((household_id,) if household_id else ()) + (int(limit),))]

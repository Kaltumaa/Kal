"""Two-way SMS for farmers without data. Sent for real through Africa's Talking when AT_USERNAME and AT_API_KEY are
set (AT_USERNAME=sandbox sends to the Africa's Talking sandbox simulator), otherwise simulated. Every attempt is
recorded in sms_deliveries with its status, provider id, cost and error.

Out: officer-made content only (photo results, confirmed community reports, replies to the farmer's own SMS
commands). The advisory agent has no route here; signed Plant/Spray/Hold advice goes through approval.py.
In: a farmer texts a short command from any phone. A real gateway (e.g. Africa's Talking) would map the phone number
to the household; the demo passes the household id directly.

    LOG <action> [crop] [details]      e.g. LOG WEEDING whole plot         (Kiswahili: REKODI PALILIA ...)
    REMIND <date> <action> [note]      e.g. REMIND 2026-10-20 SPRAY maize  (KUMBUSHA ...; date can be "tomorrow"/"kesho")
    PROBLEM <what you see>             e.g. PROBLEM holes in maize leaves  (SHIDA ...): goes to the officer to confirm
"""
from __future__ import annotations

import re
from datetime import timedelta

import httpx

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError, sms_parts, sms_safe

SCHEMA = """
CREATE TABLE IF NOT EXISTS sms_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    direction    TEXT NOT NULL CHECK (direction IN ('IN','OUT')),
    body         TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- command | reply | photo_result | community_result
    related_id   INTEGER,
    sent_by      TEXT,                   -- officer name for officer content, 'system' for command replies
    created_at   TEXT NOT NULL,
    sms_parts    INTEGER
);
"""

ACTION_WORDS = {
    "PLANTING": ["PLANTING", "PLANT", "PLANTED", "PANDA", "NIMEPANDA"],
    "WEEDING": ["WEEDING", "WEED", "WEEDED", "PALILIA", "NIMEPALILIA"],
    "SPRAYING": ["SPRAYING", "SPRAY", "SPRAYED", "NYUNYIZA", "NIMENYUNYIZA"],
    "FERTILISER": ["FERTILISER", "FERTILIZER", "MBOLEA"],
    "IRRIGATION": ["IRRIGATION", "WATER", "WATERED", "MAJI", "MWAGILIA"],
    "HARVEST": ["HARVEST", "HARVESTED", "VUNA", "NIMEVUNA", "MAVUNO"],
    "OBSERVATION": ["OBSERVATION", "SAW", "SEEN", "NIMEONA", "ONA"],
    "VARIETY": ["SEED", "VARIETY", "MBEGU"],
}
WORD_TO_ACTION = {w: a for a, words in ACTION_WORDS.items() for w in words}
COMMANDS = {"LOG": "LOG", "REKODI": "LOG", "REMIND": "REMIND", "KUMBUSHA": "REMIND", "PROBLEM": "PROBLEM",
            "SHIDA": "PROBLEM", "HELP": "HELP", "MSAADA": "HELP"}
HELP = {
    "en": "TALO SMS: LOG WEEDING notes | LOG PLANT BEANS | REMIND 2026-10-20 SPRAY notes | "
          "PROBLEM what you see. Your officer replies by SMS.",
    "sw": "TALO SMS: REKODI PALILIA maelezo | REKODI PANDA MAHARAGWE | KUMBUSHA 2026-10-20 NYUNYIZA | "
          "SHIDA unachoona. Afisa atakujibu kwa SMS.",
}


DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS sms_deliveries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,            -- advice (dispatch_outbox) | message (sms_messages)
    source_id    INTEGER,
    household_id TEXT,
    phone        TEXT,
    status       TEXT NOT NULL,            -- SENT | SIMULATED | FAILED
    provider_id  TEXT,
    cost         TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL
);
"""
AT_SMS_URL = "https://api.africastalking.com/version1/messaging"
AT_SMS_SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"


def _ensure(conn) -> None:
    conn.executescript(SCHEMA + DELIVERY_SCHEMA)


def gateway_live() -> bool:
    return bool(config.AT_USERNAME and config.AT_API_KEY) and not config.SMS_SIMULATE


def gateway_status() -> dict:
    sandbox = config.AT_USERNAME == "sandbox"
    return {"live": gateway_live(), "sandbox": gateway_live() and sandbox,
            "channel": ("Africa's Talking sandbox" if sandbox else "Africa's Talking") if gateway_live()
            else "SMS (simulated: no AT_USERNAME / AT_API_KEY)"}


def _at_send(phone: str, text: str) -> tuple[str, str | None]:
    url = AT_SMS_SANDBOX_URL if config.AT_USERNAME == "sandbox" else AT_SMS_URL
    data = {"username": config.AT_USERNAME, "to": phone, "message": text}
    if config.AT_SMS_SENDER:
        data["from"] = config.AT_SMS_SENDER
    r = httpx.post(url, data=data, timeout=15,
                   headers={"apiKey": config.AT_API_KEY, "Accept": "application/json"})
    if r.status_code >= 400:
        raise ApprovalError(f"Africa's Talking HTTP {r.status_code}: {r.text[:120]}")
    rec = ((r.json().get("SMSMessageData") or {}).get("Recipients") or [{}])[0]
    if rec.get("statusCode") not in (100, 101, 102):
        raise ApprovalError(f"Africa's Talking: {rec.get('status') or r.json()}"[:200])
    return rec.get("messageId") or "", rec.get("cost")


def deliver(household_id: str, text: str, source: str, source_id: int | None) -> dict:
    """Send one queued SMS to the farm's phone (or simulate it) and record the result. Never raises."""
    with connect() as conn:
        row = conn.execute("SELECT phone FROM plots WHERE household_id = ?", (household_id,)).fetchone()
    phone = (row["phone"] if row else None) or None
    status, provider_id, cost, error = "SIMULATED", None, None, None
    if not phone:
        status, error = "FAILED", "no phone number on this farm"
    elif gateway_live():
        try:
            provider_id, cost = _at_send(phone, text)
            status = "SENT"
        except Exception as exc:  # noqa: BLE001 - the message stays in the outbox; report, do not crash
            status, error = "FAILED", str(exc)[:300]
    with connect() as conn:
        _ensure(conn)
        did = conn.execute("INSERT INTO sms_deliveries (source, source_id, household_id, phone, status, provider_id, "
                           "cost, error, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                           (source, source_id, household_id, phone, status, provider_id, cost, error,
                            telemetry.now_iso())).lastrowid
    return {"delivery_id": did, "status": status, "error": error, "cost": cost}


def deliveries(limit: int = 100) -> list[dict]:
    with connect() as conn:
        _ensure(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM sms_deliveries ORDER BY id DESC LIMIT ?", (int(limit),))]


def queue_out(household_id: str, text: str, kind: str, related_id: int | None = None, sent_by: str = "system") -> int:
    body = sms_safe(sanitizer.normalise_text(text))[:480]
    with connect() as conn:
        _ensure(conn)
        cur = conn.execute("INSERT INTO sms_messages (household_id, direction, body, kind, related_id, sent_by, "
                           "created_at, sms_parts) VALUES (?,?,?,?,?,?,?,?)",
                           (household_id, "OUT", body, kind, related_id, sent_by, telemetry.now_iso(), sms_parts(body)))
        msg_id = cur.lastrowid
    deliver(household_id, body, "message", msg_id)
    return msg_id


def list_messages(household_id: str | None = None) -> list[dict]:
    with connect() as conn:
        _ensure(conn)
        q = "SELECT * FROM sms_messages" + (" WHERE household_id = ?" if household_id else "") + " ORDER BY id DESC"
        return [dict(r) for r in conn.execute(q, (household_id,) if household_id else ())]


def _farm(household_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM plots WHERE household_id = ?", (household_id,)).fetchone()
    if row is None:
        raise ApprovalError("Unknown sender.")
    return dict(row)


def _say(lang: str, en: str, sw: str) -> str:
    return sw if lang == "sw" else en


def receive(household_id: str, text: str, channel: str = "sms") -> dict:
    """Handle one inbound SMS (or, with channel="whatsapp", a WhatsApp text: the caller stores it and sends the reply
    on WhatsApp, so nothing is written to the SMS log). Returns the command understood and the reply."""
    from crop_pilot.community import forum          # local import: forum imports nothing from here
    from crop_pilot.plots import actions, reminders

    hid = sanitizer.normalise_text(household_id).upper()[:32]
    farm = _farm(hid)
    lang = "sw" if farm.get("language") == "sw" else "en"
    body, hits = sanitizer.scrub_free_text(text, 300)
    in_id = None
    if channel == "sms":
        with connect() as conn:
            _ensure(conn)
            in_id = conn.execute("INSERT INTO sms_messages (household_id, direction, body, kind, created_at, "
                                 "sms_parts) VALUES (?,?,?,?,?,?)", (hid, "IN", body or "(empty)", "command",
                                                                     telemetry.now_iso(), sms_parts(body))).lastrowid
    words = body.split()
    command = COMMANDS.get(words[0].upper()) if words and not hits else None
    try:
        if command == "LOG" and len(words) >= 2 and words[1].upper() in WORD_TO_ACTION:
            action = WORD_TO_ACTION[words[1].upper()]
            rest = words[2:]
            crop = sanitizer.normalise_crop(rest[0]) if rest else None
            if action == "PLANTING" and not crop:
                raise ApprovalError(_say(lang, "Say which crop, e.g. LOG PLANT BEANS.",
                                         "Taja zao, mfano REKODI PANDA MAHARAGWE."))
            r = actions.log_action(hid, action, config.today().isoformat(), crop, " ".join(rest), "farmer", None)
            reply = _say(lang, f"Saved to your plot history: {action.lower()} today.",
                         f"Imehifadhiwa kwenye historia ya shamba: {words[1].lower()} leo.")
            result = {"command": "LOG", "action": action, "action_id": r["action_id"]}
        elif command == "REMIND" and len(words) >= 3:
            word = words[1].lower()
            due = (config.today() + timedelta(days=1) if word in ("tomorrow", "kesho")
                   else sanitizer.parse_date(words[1]))
            action = WORD_TO_ACTION.get(words[2].upper())
            if due is None or action is None or action == "PLANTING":
                raise ApprovalError(_say(lang, "Use: REMIND 2026-10-20 SPRAY note", "Tumia: KUMBUSHA 2026-10-20 NYUNYIZA"))
            r = reminders.create(hid, due.isoformat(), action, " ".join(words[3:]))
            reply = _say(lang, f"Reminder set for {due.isoformat()}: {action.lower()}.",
                         f"Kikumbusho kimewekwa {due.isoformat()}: {words[2].lower()}.")
            result = {"command": "REMIND", "reminder_id": r["reminder_id"]}
        elif command == "PROBLEM" and len(words) >= 2:
            name = re.sub(r"[^A-Za-z '\-.]", "", farm.get("farmer_name") or "Farmer")[:40] or "Farmer"
            post = forum.post(name, "Pests & diseases", " ".join(words[1:]), zone_id=farm.get("zone_id"),
                              household_id=hid, source="sms")
            reply = _say(lang, "Received. Your extension officer will check it and reply by SMS.",
                         "Imepokelewa. Afisa wa ugani ataangalia na kukujibu kwa SMS.")
            result = {"command": "PROBLEM", "post_id": post["id"]}
        else:
            reply, result = HELP[lang], {"command": "HELP"}
    except (ApprovalError, ValueError) as exc:
        reply, result = str(exc), {"command": command or "HELP", "error": True}
    out_id = queue_out(hid, reply, "reply", in_id) if channel == "sms" else None
    telemetry.record(f"{channel}-{hid}", channel, f"inbound_{channel}", {"household_id": hid, "command": result["command"]},
                     {"reply_id": out_id}, latency_ms=0, actor=farm.get("farmer_name") or hid)
    return result | {"reply": reply, "in_id": in_id, "reply_id": out_id}

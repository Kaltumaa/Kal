"""Voice calls to farmers on feature phones (Africa's Talking Voice), after an officer signs.

Only officer-signed text is ever spoken: the signed Plant/Spray/Hold message (approval.approve) or the officer's
photo result (fieldscan.review). The agent has no route here (tests/test_boundaries.py).

Flow
    queue_call -> place: POST https://voice.africastalking.com/call (from = our AT number, to = farmer)  -> SENT
    farmer answers -> AT posts to /voice/callback -> we reply with XML: greeting + message + keypad menu  -> ANSWERED
    farmer presses a key -> AT posts dtmfDigits (to /voice/callback or /voice/dtmf: both work)
        1 = "I understood"                         -> ACKNOWLEDGED
        2 = "I need help from my Nyumba Kumi lead" -> VISIT_REQUESTED: alert on the lead farmer's page + SMS to the
                                                      lead, and a FIELD_VISIT follow-up for the officer
        0 = hear it again (up to VOICE_MAX_PLAYS)
    call ends (isActive=0) -> duration, cost and hangup cause stored; unanswered -> NO_ANSWER

Without Africa's Talking credentials every call is SIMULATED: logged with a fake session id. Then either
  - simulate_telephony_carrier_loop runs in a background thread (VOICE_AUTO_SIMULATE=1, on in `make run`) and plays
    the carrier: real HTTP POSTs to our own /voice/callback (pick-up, keypress, hang-up), or
  - the officer plays the farmer's phone from System -> Phone calls.
Both go through the same handlers a real Africa's Talking call uses. Simulated keypresses are labelled simulated.
"""
from __future__ import annotations

import hmac
import math
import random
import re
import threading
import time
from datetime import timedelta
from xml.sax.saxutils import escape, quoteattr

import httpx

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry
from crop_pilot.database.db import connect
from crop_pilot.dispatch.approval import ApprovalError, sms_safe
from crop_pilot.fieldscan.voice_draft import KEYPAD_EN, KEYPAD_SW

AT_CALL_URL = "https://voice.africastalking.com/call"
PHONE_RE = re.compile(r"^\+254[17]\d{8}$")
STATUSES = ("QUEUED", "SENT", "ANSWERED", "ACKNOWLEDGED", "VISIT_REQUESTED", "NO_ANSWER", "FAILED")
SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    phone        TEXT NOT NULL,
    language     TEXT NOT NULL CHECK (language IN ('en','sw')),
    script       TEXT NOT NULL,            -- exactly what the officer signed; spoken after the greeting
    kind         TEXT NOT NULL,            -- advice | photo_result
    related_id   INTEGER,
    officer      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN
                 ('QUEUED','SENT','ANSWERED','ACKNOWLEDGED','VISIT_REQUESTED','NO_ANSWER','FAILED')),
    channel      TEXT NOT NULL,            -- AFRICAS_TALKING | SIMULATED
    session_id   TEXT,
    digits       TEXT,                     -- keys pressed, in order
    plays        INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    followup_id  INTEGER,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""

# What the farmer hears around the officer's message. Short sentences. "menu" is for farms in a Nyumba Kumi cell
# (2 = help from the lead farmer); "menu_officer" for farms in none (2 = help from the officer).
WORDS = {
    "sw": {"hello": "Habari. Huu ni ujumbe wa Mkulima Hub, kutoka kwa afisa wako wa kilimo, {officer}.",
           "menu": KEYPAD_SW + " Kusikiliza tena, bonyeza sifuri.",
           "menu_officer": "Kama umeelewa, bonyeza moja. Kama unahitaji msaada wa afisa wa kilimo, bonyeza mbili. "
                           "Kusikiliza tena, bonyeza sifuri.",
           "ack": "Asante. Tumepokea. Kwa heri.",
           "visit": "Asante. Tumemwarifu kiongozi wako wa Nyumba Kumi, atakusaidia. Kwa heri.",
           "visit_officer": "Asante. Afisa wa kilimo atawasiliana nawe. Kwa heri.",
           "again": "Sikiliza tena.",
           "bye": "Hatukusikia jibu. Ujumbe huu pia umetumwa kwa SMS. Kwa heri."},
    "en": {"hello": "Hello. This is a Mkulima Hub message from your extension officer, {officer}.",
           "menu": KEYPAD_EN + " To hear it again, press 0.",
           "menu_officer": "If you understood, press 1. If you need help from the extension officer, press 2. "
                           "To hear it again, press 0.",
           "ack": "Thank you. We have noted it. Goodbye.",
           "visit": "Thank you. We have told your Nyumba Kumi lead farmer; they will help you. Goodbye.",
           "visit_officer": "Thank you. Your extension officer will contact you. Goodbye.",
           "again": "Listen again.",
           "bye": "We did not hear an answer. This message was also sent by SMS. Goodbye."},
}
METRIC_COLUMNS = {"duration_seconds": "REAL", "amount": "REAL", "currency": "TEXT", "hangup_cause": "TEXT",
                  "ended_at": "TEXT", "caller_number": "TEXT"}


def _ensure(conn) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(voice_calls)")}
    for col, kind in METRIC_COLUMNS.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE voice_calls ADD COLUMN {col} {kind}")      # fixed names, no user input


def live() -> bool:
    return all((config.AT_USERNAME, config.AT_API_KEY, config.AT_VOICE_NUMBER))


def status() -> dict:
    missing = [n for n, v in (("AT_USERNAME", config.AT_USERNAME), ("AT_API_KEY", config.AT_API_KEY),
                              ("AT_VOICE_NUMBER", config.AT_VOICE_NUMBER), ("VOICE_PUBLIC_URL", config.VOICE_PUBLIC_URL),
                              ("VOICE_WEBHOOK_TOKEN", config.VOICE_WEBHOOK_TOKEN)) if not v]
    return {"channel": "AFRICAS_TALKING" if live() else "SIMULATED", "missing": missing,
            "auto_simulate": not live() and config.VOICE_AUTO_SIMULATE, "sim_digit": config.VOICE_SIM_DIGIT}


def _farm(conn, household_id: str) -> dict:
    row = conn.execute("SELECT household_id, phone, phone_type, cell_id, farmer_name FROM plots "
                       "WHERE upper(household_id) = ?", (sanitizer.normalise_text(household_id).upper()[:32],)).fetchone()
    if row is None:
        raise ApprovalError("Household not found.")
    return dict(row)


def check_phone(household_id: str) -> dict:
    with connect() as conn:
        farm = _farm(conn, household_id)
    if not PHONE_RE.match(farm.get("phone") or ""):
        raise ApprovalError("This farm has no valid phone number (+2547... or +2541...). Add it on the Farms page.")
    return farm


def check(household_id: str, script: str | None, language: str) -> tuple[dict, str]:
    """Refuse before anything is signed: no valid phone number, no message, or instruction-like text."""
    if language not in WORDS:
        raise ApprovalError("Call language must be en or sw.")
    farm = check_phone(household_id)
    text, hits = sanitizer.scrub_free_text(script or "", 600)
    if hits:
        raise ApprovalError("The call script contains instruction-like text; not sent.")
    if len(text) < 10:
        raise ApprovalError("Write the message the farmer will hear (at least a short sentence).")
    return farm, sms_safe(text)


def queue_call(household_id: str, script: str, language: str, kind: str, related_id: int | None,
               officer: str) -> dict:
    farm, text = check(household_id, script, language)
    ts = telemetry.now_iso()
    with connect() as conn:
        _ensure(conn)
        call_id = conn.execute("INSERT INTO voice_calls (household_id, phone, language, script, kind, related_id, "
                               "officer, channel, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (farm["household_id"], farm["phone"], language, text, kind, related_id, officer,
                                "AFRICAS_TALKING" if live() else "SIMULATED", ts, ts)).lastrowid
    return place(call_id)


def _update(conn, call_id: int, **fields) -> None:
    fields["updated_at"] = telemetry.now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)          # keys are fixed names from this module, never user input
    conn.execute(f"UPDATE voice_calls SET {cols} WHERE id = ?", (*fields.values(), call_id))


def get(call_id: int) -> dict | None:
    with connect() as conn:
        _ensure(conn)
        row = conn.execute("SELECT * FROM voice_calls WHERE id = ?", (call_id,)).fetchone()
    return dict(row) if row else None


def place(call_id: int) -> dict:
    """Ask Africa's Talking to ring the farmer (or simulate it). The farmer hears nothing until they answer."""
    call = get(call_id)
    if call is None or call["status"] not in ("QUEUED", "NO_ANSWER", "FAILED"):
        raise ApprovalError("Call not found, or it is already in progress or answered.")
    started = time.perf_counter()
    result: dict = {}
    if call["channel"] == "SIMULATED":
        result = {"status": "SENT", "session_id": f"SIM-{call_id}-{int(time.time())}", "error": None}
    elif not (config.VOICE_WEBHOOK_TOKEN and config.VOICE_PUBLIC_URL):
        result = {"status": "FAILED", "session_id": None,
                  "error": "Set VOICE_PUBLIC_URL and VOICE_WEBHOOK_TOKEN before placing real calls."}
    else:
        try:
            r = httpx.post(AT_CALL_URL, headers={"apiKey": config.AT_API_KEY, "Accept": "application/json"},
                           data={"username": config.AT_USERNAME, "from": config.AT_VOICE_NUMBER, "to": call["phone"]},
                           timeout=20)
            body = r.json() if r.content else {}
            entry = (body.get("entries") or [{}])[0]
            if r.status_code < 300 and entry.get("sessionId") and entry.get("status") == "Queued":
                result = {"status": "SENT", "session_id": entry["sessionId"], "error": None}
            else:
                result = {"status": "FAILED", "session_id": entry.get("sessionId"),
                          "error": str(entry.get("status") or body.get("errorMessage") or r.status_code)[:200]}
        except (httpx.HTTPError, ValueError) as exc:
            result = {"status": "FAILED", "session_id": None, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    with connect() as conn:
        _update(conn, call_id, status=result["status"], session_id=result["session_id"], error=result["error"])
    if call["channel"] == "SIMULATED" and result["status"] == "SENT" and config.VOICE_AUTO_SIMULATE:
        start_carrier_simulator(call["phone"], result["session_id"])
    telemetry.record(f"voice-{call_id}", "voice", "place_call", {"call_id": call_id, "household_id": call["household_id"],
                                                                 "channel": call["channel"]},
                     result, latency_ms=(time.perf_counter() - started) * 1000, actor=call["officer"],
                     approved_by=call["officer"], status="ok" if result["status"] == "SENT" else "error")
    return {"call_id": call_id, "channel": call["channel"]} | result


def token_ok(token: str | None) -> bool:
    """Webhooks carry ?t=<VOICE_WEBHOOK_TOKEN>. With no token configured only simulated calls exist."""
    if not config.VOICE_WEBHOOK_TOKEN:
        return not live()
    return hmac.compare_digest(token or "", config.VOICE_WEBHOOK_TOKEN)


def _by_session(conn, session_id: str | None) -> dict | None:
    if not session_id:
        return None
    row = conn.execute("SELECT * FROM voice_calls WHERE session_id = ?", (session_id[:128],)).fetchone()
    return dict(row) if row else None


def _say(text: str) -> str:
    return f"<Say voice={quoteattr(config.AT_SAY_VOICE)} playBeep=\"false\">{escape(text)}</Say>"


def _xml(*actions: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(actions) + "</Response>"


def _in_cell(conn, household_id: str) -> bool:
    row = conn.execute("SELECT c.lead_household_id FROM plots p JOIN nyumba_cells c ON c.cell_id = p.cell_id "
                       "WHERE p.household_id = ?", (household_id,)).fetchone()
    return bool(row) and row["lead_household_id"] != household_id


def _menu(call: dict, first: bool, in_cell: bool = True) -> str:
    w = WORDS[call["language"]]
    dtmf_url = f"{config.VOICE_PUBLIC_URL}/voice/callback"         # one URL for every carrier event
    if config.VOICE_WEBHOOK_TOKEN:
        dtmf_url += f"?t={config.VOICE_WEBHOOK_TOKEN}"
    officer = re.sub(r"[^A-Za-z '\-.]", "", call["officer"])
    # A script drafted with the keypad sentence already in it must not say it twice.
    script = re.sub(r"\s*(kama umeelewa|if you understood).*$", "", call["script"], flags=re.IGNORECASE).strip()
    menu = w["menu"] if in_cell else w["menu_officer"]
    spoken = (w["hello"].format(officer=officer) + " " if first else w["again"] + " ") + script + " " + menu
    return _xml(f'<GetDigits timeout="20" numDigits="1" finishOnKey="#" callbackUrl={quoteattr(dtmf_url)}>'
                + _say(spoken) + "</GetDigits>", _say(w["bye"]))


def _num(value) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and 0 <= n < 1e6 else None


def handle_callback(form: dict) -> str:
    """The one carrier webhook. Africa's Talking posts form fields:
        isActive=1           the farmer picked up -> greeting + message + keypad menu (XML)
        dtmfDigits=<key>     a keypress (GetDigits) -> handled by handle_dtmf
        isActive=0           the call ended -> durationInSeconds, amount, currencyCode, hangupCause stored
    callerNumber / destinationNumber are logged; the call is found by sessionId, which only we hand out."""
    if str(form.get("dtmfDigits") or "").strip():
        return handle_dtmf(form)
    with connect() as conn:
        _ensure(conn)
        call = _by_session(conn, form.get("sessionId"))
        if call is None:
            return _xml("<Reject/>")
        caller = re.sub(r"[^\d+]", "", str(form.get("callerNumber") or ""))[:16] or None
        if str(form.get("isActive")) == "1":
            if call["plays"] >= config.VOICE_MAX_PLAYS:
                return _xml(_say(WORDS[call["language"]]["bye"]))
            _update(conn, call["id"], status="ANSWERED" if call["status"] == "SENT" else call["status"],
                    plays=call["plays"] + 1, caller_number=caller or call.get("caller_number"))
            xml = _menu(call, first=call["plays"] == 0, in_cell=_in_cell(conn, call["household_id"]))
        else:
            cause = sanitizer.normalise_text(form.get("hangupCause") or form.get("status"))[:80] or None
            metrics = {"ended_at": telemetry.now_iso(), "hangup_cause": cause,
                       "duration_seconds": _num(form.get("durationInSeconds")), "amount": _num(form.get("amount")),
                       "currency": re.sub(r"[^A-Z]", "", str(form.get("currencyCode") or "").upper())[:3] or None}
            if call["status"] == "SENT":                    # rang out, rejected, or unreachable
                metrics |= {"status": "NO_ANSWER", "error": cause}
            _update(conn, call["id"], **metrics)
            xml = _xml()
    telemetry.record(f"voice-{call['id']}", "voice", "call_event",
                     {"isActive": form.get("isActive"), "status": form.get("status"),
                      "duration_s": form.get("durationInSeconds"), "amount": form.get("amount")},
                     {"call_id": call["id"]}, latency_ms=0, actor="carrier-simulator"
                     if call["channel"] == "SIMULATED" else "africastalking")
    return xml


def handle_dtmf(form: dict) -> str:
    """The key the farmer pressed: 1 heard, 2 visit me, 0 repeat. Anything else plays the menu once more."""
    digit = re.sub(r"\D", "", str(form.get("dtmfDigits") or ""))[:1]
    followup_id = None
    with connect() as conn:
        _ensure(conn)
        call = _by_session(conn, form.get("sessionId"))
        if call is None:
            return _xml("<Reject/>")
        w = WORDS[call["language"]]
        digits = ((call["digits"] or "") + (digit or "-"))[-12:]
        if digit == "1":
            if call["status"] != "VISIT_REQUESTED":
                _update(conn, call["id"], status="ACKNOWLEDGED", digits=digits)
            else:
                _update(conn, call["id"], digits=digits)
            xml = _xml(_say(w["ack"]))
        elif digit == "2":
            in_cell = _in_cell(conn, call["household_id"])
            followup_id = _visit_followup(conn, call, in_cell)
            _update(conn, call["id"], status="VISIT_REQUESTED", digits=digits, followup_id=followup_id)
            xml = _xml(_say(w["visit"] if in_cell else w["visit_officer"]))
        elif call["plays"] < config.VOICE_MAX_PLAYS:
            _update(conn, call["id"], digits=digits, plays=call["plays"] + 1)
            xml = _menu(call, first=False, in_cell=_in_cell(conn, call["household_id"]))
        else:
            _update(conn, call["id"], digits=digits)
            xml = _xml(_say(w["bye"]))
    if digit == "2":
        _tell_lead(call)
    telemetry.record(f"voice-{call['id']}", "voice", "keypad", {"digit": digit or None},
                     {"call_id": call["id"], "followup_id": followup_id}, latency_ms=0, actor=call["household_id"])
    return xml


def _visit_followup(conn, call: dict, in_cell: bool = True) -> int:
    from crop_pilot.mcp_server.server import FOLLOWUP_SCHEMA
    conn.executescript(FOLLOWUP_SCHEMA)
    run_id = f"voice-call-{call['id']}"
    row = conn.execute("SELECT id FROM followups WHERE run_id = ? AND kind = 'FIELD_VISIT'", (run_id,)).fetchone()
    if row:
        return row["id"]
    due = (config.today() + timedelta(days=2)).isoformat()
    reason = (f"Farmer pressed 2 on the voice call about {call['kind'].replace('_', ' ')} #{call['related_id']}: "
              + ("asked for help; their Nyumba Kumi lead farmer was alerted. Check in with the lead."
                 if in_cell else "asked for help from the officer."))
    return conn.execute("INSERT INTO followups (run_id, household_id, kind, due_date, reason, created_at) "
                        "VALUES (?,?,?,?,?,?)", (run_id, call["household_id"], "FIELD_VISIT", due, reason,
                                                 telemetry.now_iso())).lastrowid


def _tell_lead(call: dict) -> None:
    """Let the Nyumba Kumi lead farmer know a neighbour asked for a visit (they often walk the officer there)."""
    from crop_pilot.dispatch import sms
    with connect() as conn:
        row = conn.execute("SELECT c.lead_household_id, p.farmer_name FROM plots p JOIN nyumba_cells c "
                           "ON c.cell_id = p.cell_id WHERE p.household_id = ?", (call["household_id"],)).fetchone()
    if row and row["lead_household_id"] != call["household_id"]:
        sms.queue_out(row["lead_household_id"], f"Mkulima Hub: your neighbour {row['farmer_name'] or call['household_id']}"
                      " pressed 2 on the officer's call: they need your help. Please visit them; the officer is informed.", "cell_visit",
                      call["id"], "system")


# --- Internal carrier simulator -----------------------------------------------------------------------------------
def _sim_digit() -> str | None:
    choice = config.VOICE_SIM_DIGIT
    if choice == "random":
        return random.choice(["1", "1", "1", "2"])               # most farmers press 1
    return choice if choice in ("0", "1", "2") else None         # "none": picks up, presses nothing


def simulate_telephony_carrier_loop(farmer_phone: str, server_url: str, session_id: str, digit: str | None = None,
                                    post=None, ring_s: float | None = None, talk_s: float | None = None) -> list[dict]:
    """Play the carrier for one SIMULATED call, the way Africa's Talking would, with real HTTP POSTs:

        wait ring_s  -> POST isActive=1 (farmer picked up)       -> our XML: greeting, message, keypad menu
        wait talk_s  -> POST dtmfDigits=<digit> (keypress)       -> our XML: thank-you line
                     -> POST isActive=0 with duration and cost   -> call closed and metered

    Runs in a background thread (start_carrier_simulator). Duration is measured; the cost is a SIMULATED figure
    (VOICE_SIM_RATE_KES_PER_MIN, not a real tariff). `post` is injectable for tests."""
    post = post or httpx.post
    ring_s = config.VOICE_SIM_RING_S if ring_s is None else ring_s
    talk_s = config.VOICE_SIM_TALK_S if talk_s is None else talk_s
    url = f"{server_url.rstrip('/')}/voice/callback" + (f"?t={config.VOICE_WEBHOOK_TOKEN}"
                                                         if config.VOICE_WEBHOOK_TOKEN else "")
    base = {"sessionId": session_id, "direction": "Outbound", "callerNumber": config.AT_VOICE_NUMBER or "+254700000000",
            "destinationNumber": farmer_phone}
    events = []

    def send(fields: dict) -> None:
        try:
            r = post(url, data=base | fields, timeout=10)
            events.append({"sent": fields, "status": r.status_code, "xml": r.text})
        except Exception as exc:                   # a simulator problem must never break the officer's request
            events.append({"sent": fields, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})

    time.sleep(ring_s)
    started = time.monotonic()
    send({"isActive": "1", "callSessionState": "Answered"})
    time.sleep(talk_s)
    if digit is not None:
        send({"isActive": "1", "dtmfDigits": digit})
    duration = max(1, round(time.monotonic() - started))
    cost = round(config.VOICE_SIM_RATE_KES_PER_MIN * math.ceil(duration / 60), 2)
    send({"isActive": "0", "callSessionState": "Completed", "status": "Success", "hangupCause": "NORMAL_CLEARING",
          "durationInSeconds": str(duration), "amount": str(cost), "currencyCode": "KES"})
    return events


def start_carrier_simulator(farmer_phone: str, session_id: str) -> threading.Thread:
    t = threading.Thread(target=simulate_telephony_carrier_loop, name=f"carrier-sim-{session_id}", daemon=True,
                         args=(farmer_phone, config.VOICE_SIM_SERVER_URL, session_id, _sim_digit()))
    t.start()
    return t


def simulate(call_id: int, answer: bool, digit: str | None = None) -> dict:
    """Demo only: act as the farmer's phone for a SIMULATED call, through the same handlers a real call uses."""
    call = get(call_id)
    if call is None or call["channel"] != "SIMULATED":
        raise ApprovalError("Only simulated calls can be answered from here.")
    if call["status"] not in ("SENT", "ANSWERED"):
        raise ApprovalError(f"The call is {call['status']}; nothing to answer.")
    spoken = []
    if not (call["status"] == "ANSWERED" and digit is not None):     # already on the line: just press the key
        spoken.append(handle_callback({"sessionId": call["session_id"], "isActive": "1" if answer else "0"}))
    if answer and digit is not None:
        spoken.append(handle_dtmf({"sessionId": call["session_id"], "dtmfDigits": digit}))
        if digit in ("1", "2"):
            handle_callback({"sessionId": call["session_id"], "isActive": "0"})
    return {"call": get(call_id), "xml": spoken}


def list_calls(household_id: str | None = None, cell_id: str | None = None) -> list[dict]:
    with connect() as conn:
        _ensure(conn)
        if cell_id:
            q, args = ("SELECT v.* FROM voice_calls v JOIN plots p ON p.household_id = v.household_id "
                       "WHERE p.cell_id = ? ORDER BY v.id DESC", (cell_id,))
        elif household_id:
            q, args = "SELECT * FROM voice_calls WHERE household_id = ? ORDER BY id DESC", (household_id,)
        else:
            q, args = "SELECT * FROM voice_calls ORDER BY id DESC LIMIT 200", ()
        return [dict(r) for r in conn.execute(q, args)]

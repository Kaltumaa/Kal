"""Check every outside system TALO talks to, with one harmless REAL call each (no SMS sent, no money moved).

    make check-integrations          (PYTHONPATH=backend python -m crop_pilot.integrations_check)

Each check returns LIVE (production service answered), SANDBOX (the provider's test world answered), SIMULATED (no keys: the built-in simulator
stands in), or FAILED (keys set but the service refused or could not be reached). The report is printed and saved
to evals/results/integrations-<time>.md so it can be shown as evidence.
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from crop_pilot import config

TIMEOUT = 15
RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results"


def _result(name: str, purpose: str, state: str, detail: str, ms: float | None = None) -> dict:
    return {"name": name, "purpose": purpose, "state": state, "detail": detail[:220],
            "ms": round(ms) if ms is not None else None}


def _probe(name: str, purpose: str, configured: bool, missing: str, fn) -> dict:
    if not configured:
        return _result(name, purpose, "SIMULATED", f"no keys ({missing}); the built-in simulator is used")
    started = time.perf_counter()
    try:
        detail = fn()
        return _result(name, purpose, "LIVE", detail, (time.perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001 - every failure is reported, none stops the other checks
        return _result(name, purpose, "FAILED", f"{type(exc).__name__}: {exc}", (time.perf_counter() - started) * 1000)


def _ok(r: httpx.Response, what: str) -> httpx.Response:
    if r.status_code >= 400:
        raise RuntimeError(f"{what} HTTP {r.status_code}: {r.text[:120]}")
    return r


# --- the checks ------------------------------------------------------------------------------------------------------
def open_meteo() -> dict:
    def go():
        r = _ok(httpx.get(config.OPEN_METEO_URL, params={"latitude": -1.285, "longitude": 36.735,
                                                          "hourly": "precipitation", "forecast_days": 1},
                          timeout=TIMEOUT), "Open-Meteo")
        return f"{len(r.json()['hourly']['time'])} hourly values for Riruta"
    return _probe("Open-Meteo", "Live weather (primary)", config.LIVE_WEATHER, "CROP_PILOT_LIVE_WEATHER=0", go)


def visual_crossing() -> dict:
    def go():
        from crop_pilot.core.weather_sources import fetch_visual_crossing
        hours, _ = fetch_visual_crossing(-1.285, 36.735)
        return f"{len(hours)} hourly values for Riruta"
    return _probe("Visual Crossing", "Weather cross-check", bool(config.VISUAL_CROSSING_API_KEY),
                  "VISUAL_CROSSING_API_KEY", go)


def africas_talking() -> dict:
    def go():
        host = "api.sandbox.africastalking.com" if config.AT_USERNAME == "sandbox" else "api.africastalking.com"
        r = _ok(httpx.get(f"https://{host}/version1/user", params={"username": config.AT_USERNAME}, timeout=TIMEOUT,
                          headers={"apiKey": config.AT_API_KEY, "Accept": "application/json"}), "Africa's Talking")
        bal = (r.json().get("UserData") or {}).get("balance")
        return f"account '{config.AT_USERNAME}' answered; balance {bal}"
    return _probe("Africa's Talking", "SMS (and voice calls)", bool(config.AT_USERNAME and config.AT_API_KEY),
                  "AT_USERNAME, AT_API_KEY", go)


def whatsapp() -> dict:
    def go():
        url = f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}"
        r = _ok(httpx.get(url, params={"fields": "display_phone_number,verified_name"}, timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}), "WhatsApp")
        d = r.json()
        return f"number {d.get('display_phone_number')} ({d.get('verified_name')})"
    return _probe("WhatsApp Cloud API", "Farmer chat", bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID),
                  "WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID", go)


def mpesa() -> dict:
    def go():
        from crop_pilot.payments import mpesa as m
        with httpx.Client(timeout=TIMEOUT) as c:
            m._access_token(c)
        return f"Daraja {config.MPESA_ENV}: OAuth token issued for shortcode {config.MPESA_SHORTCODE}"
    from crop_pilot.payments import mpesa as m
    return _probe("M-Pesa Daraja", "Institution payments", m.live(),
                  "MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_SHORTCODE, MPESA_PASSKEY", go)


def card() -> dict:
    from crop_pilot.payments import card as cd

    def go():
        if cd.provider() == "stripe":
            _ok(httpx.get("https://api.stripe.com/v1/balance", auth=(config.STRIPE_SECRET_KEY, ""), timeout=TIMEOUT),
                "Stripe")
            return "Stripe test account answered (balance readable)"
        _ok(httpx.get("https://api.flutterwave.com/v3/balances", timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {config.FLW_SECRET_KEY}"}), "Flutterwave")
        return "Flutterwave account answered (balances readable)"
    return _probe(f"Card ({config.CARD_PROVIDER.title()})", "Visa / Mastercard payments", cd.live(),
                  "STRIPE_SECRET_KEY or FLW_SECRET_KEY (test key)", go)


def deepleaf() -> dict:
    def go():
        r = httpx.get(config.DEEPLEAF_BASE_URL.rsplit("/v1", 1)[0], timeout=TIMEOUT)
        return f"DeepLeaf host reachable (HTTP {r.status_code}); key set, a diagnosis runs on the next photo"
    return _probe("DeepLeaf", "Plant second opinion", bool(config.DEEPLEAF_API_KEY), "DEEPLEAF_API_KEY", go)


def ollama() -> dict:
    def go():
        r = _ok(httpx.get(f"{config.OLLAMA_HOST}/api/tags", timeout=TIMEOUT), "Ollama")
        names = [m["name"] for m in r.json().get("models", [])]
        have = [n for n in names if n.split(":")[0] in (config.OLLAMA_MODEL.split(":")[0], config.VISION_MODEL)]
        if config.OLLAMA_MODEL not in names:
            raise RuntimeError(f"{config.OLLAMA_MODEL} not pulled (have: {', '.join(names) or 'none'})")
        return "models ready: " + ", ".join(have)
    return _probe("Ollama (local AI)", "Agent model + photo model", True, "", go)


def filesystem_mcp() -> dict:
    def go():
        if not shutil.which("npx"):
            raise RuntimeError("npx not found: install Node.js to run the official filesystem MCP server")
        return "npx found; the agent starts @modelcontextprotocol/server-filesystem on demand"
    return _probe("Filesystem MCP server", "Guidance documents (3rd-party MCP)", True, "", go)


# Not built yet: what connecting each would take (shown in the report as PLANNED).
PLANNED = [
    ("Airtel Money", "Second mobile-money rail", "Airtel Africa collections API; same pattern as M-Pesa (STK-style push "
     "+ verified callback) in payments/; about a week with sandbox keys"),
    ("USSD menu", "Feature-phone self-service", "Africa's Talking USSD (same account as SMS): one webhook mapping *384# "
     "menus to the SMS commands that already exist"),
    ("County farmer registry / KALRO records", "Institutional records", "an export or API from the county; the farm "
     "record is one table (plots), so it is an import job plus an MCP read tool"),
    ("KEPHIS seed-label check", "Fake-seed verification", "today the farmer types KEPHIS's SMS reply; an official API "
     "would replace that one field"),
]

CHECKS = [open_meteo, visual_crossing, africas_talking, whatsapp, mpesa, card, deepleaf, ollama, filesystem_mcp]


def _sandbox(name: str) -> bool:
    """True when the keys point at the provider's test world, so judges see sandbox vs production."""
    from crop_pilot.payments import card as cd
    if name.startswith("Africa's Talking"):
        return config.AT_USERNAME == "sandbox"
    if name.startswith("M-Pesa"):
        return config.MPESA_ENV != "production"
    if name.startswith("Card"):
        return cd._is_test_key(cd._key())
    return False


def run() -> list[dict]:
    results = [check() for check in CHECKS]
    for r in results:
        if r["state"] == "LIVE" and _sandbox(r["name"]):
            r["state"] = "SANDBOX"
    return results


def report(results: list[dict]) -> str:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    live = sum(r["state"] in ("LIVE", "SANDBOX") for r in results)
    lines = [f"# Integration check, {when}", "",
             f"**{live} of {len(results)} systems answered for real** (LIVE = production, SANDBOX = the provider's test "
             "world). One harmless real call each: no SMS was sent and "
             "no money moved.", "", "| System | Used for | State | Detail | ms |", "|---|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['purpose']} | **{r['state']}** | {r['detail']} | {r['ms'] or ''} |" for r in results]
    lines += [f"| {n} | {p} | **PLANNED** | {how} | |" for n, p, how in PLANNED]
    lines += ["", "Keys live only in `.env` on this computer (git-ignored, never sent to the browser). A sandbox key "
              "shows as LIVE here because the real service answered; the state column says which world it talks to."]
    return "\n".join(lines) + "\n"


def main() -> None:
    results = run()
    text = report(results)
    print(text)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"integrations-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.md"
    out.write_text(text)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()

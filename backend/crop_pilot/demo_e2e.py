"""One complete outcome, end to end, through the real systems wherever keys are set (simulators otherwise).

    make demo-live                                   # farm HH-DS-001
    make demo-live ARGS="--farm HH-DS-002 --farmer-phone +2547XXXXXXXX --payer-phone 254708374149"

Steps, each timed and logged:
  1. integration check (which systems are live)
  2. live ward weather (Open-Meteo + Visual Crossing)
  3. the agent drafts advice for one farm (local model + MCP tools), self-checks, and freezes at the human gate
  4. a named extension officer signs it (citing the draft's own records)
  5. delivery: SMS (Africa's Talking) and WhatsApp (Meta) to the farmer
  6. the farmer answers by WhatsApp with an SMS-style command
  7. the institution pays for farmer access by M-Pesa (Daraja STK push)
  8. the cost of this one completed outcome

`--farmer-phone` temporarily puts YOUR phone on the farm so live SMS/WhatsApp reach you (restored afterwards).
The report is printed and saved to evals/results/e2e-<time>.md. This writes to the local database like a real day.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from crop_pilot import config, integrations_check
from crop_pilot.agent import llm
from crop_pilot.agent.workflow import build_graph, resume_run, start_run
from crop_pilot.core import weather_sources
from crop_pilot.database.db import connect
from crop_pilot.database.init_db import ensure_schema
from crop_pilot.dispatch import approval, sms, whatsapp
from crop_pilot.payments import mpesa, subscriptions

RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results"
WATTS = 35.0                     # laptop draw while the model runs (same estimate as EVALS.md)
KES_PER_KWH = 25.0


def _env_float(name: str) -> float | None:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return None


class Log:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def step(self, title: str, fn):
        started = time.perf_counter()
        try:
            out = fn()
            ok, err = True, None
        except Exception as exc:  # noqa: BLE001 - the demo reports every failure and carries on
            out, ok, err = None, False, f"{type(exc).__name__}: {exc}"
        self.steps.append({"title": title, "ok": ok, "s": round(time.perf_counter() - started, 2), "error": err})
        print(f"[{'ok' if ok else 'FAILED'}] {title} ({self.steps[-1]['s']} s){' - ' + err if err else ''}")
        return out


def _officer_name() -> str:
    with connect() as conn:
        row = conn.execute("SELECT full_name FROM users WHERE role='extension_officer' AND active=1 "
                           "ORDER BY id LIMIT 1").fetchone()
    return row["full_name"] if row else "Demo Officer"


def _institution_id() -> int | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM institutions ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def _run_cost(run_id: str) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT COUNT(*) AS calls, COALESCE(SUM(token_estimate),0) AS tokens, "
                         "SUM(CASE WHEN server='ollama' THEN 1 ELSE 0 END) AS model_calls, "
                         "SUM(CASE WHEN server IN ('crop-pilot','filesystem') THEN 1 ELSE 0 END) AS mcp_calls "
                         "FROM tool_calls WHERE run_id = ?", (run_id,)).fetchone()
    return dict(r)


def main() -> None:
    ap = argparse.ArgumentParser(description="TALO end-to-end demo")
    ap.add_argument("--farm", default="HH-DS-001")
    ap.add_argument("--farmer-phone", help="your phone (+2547...) so live SMS/WhatsApp reach you")
    ap.add_argument("--payer-phone", default="254708374149", help="M-Pesa payer (Daraja sandbox test number)")
    ap.add_argument("--farmers", type=int, default=1, help="farmer places the institution pays for")
    args = ap.parse_args()
    hid = args.farm.upper()
    log = Log()
    with connect() as conn:
        ensure_schema(conn)
        old_phone = conn.execute("SELECT phone FROM plots WHERE household_id = ?", (hid,)).fetchone()
    if old_phone is None:
        raise SystemExit(f"Unknown farm {hid}")
    if args.farmer_phone:
        with connect() as conn:
            conn.execute("UPDATE plots SET phone = ? WHERE household_id = ?", (args.farmer_phone, hid))

    try:
        checks = log.step("1. Integration check", integrations_check.run)
        weather = log.step("2. Live ward weather", lambda: weather_sources.refresh_ward_forecasts("e2e-weather"))
        llm_ok = asyncio.run(llm.is_available())
        graph = build_graph(InMemorySaver())
        run = log.step(f"3. Agent drafts advice for {hid}", lambda: asyncio.run(start_run(graph, hid, "End-to-end demo")))
        adv = (run or {}).get("advisory") or {}
        officer = _officer_name()
        approved = None
        if adv.get("status") == "PENDING_REVIEW":
            with connect() as conn:
                row = conn.execute("SELECT sources_json FROM pending_advisories WHERE id = ?",
                                   (adv["advisory_id"],)).fetchone()
            import json
            sources = json.loads(row["sources_json"])
            citation = "Checked " + " and ".join(sources[:2])
            approved = log.step(f"4-5. {officer} signs; SMS and WhatsApp go out",
                                lambda: approval.approve(adv["advisory_id"], officer, citation=citation,
                                                         languages=("en",)))
            if approved:
                log.step("   graph closes after the officer's decision",
                         lambda: asyncio.run(resume_run(graph, run["run_id"], "APPROVED", officer)))
        else:
            log.steps.append({"title": f"4. Officer signs: not possible, draft is {adv.get('status')} "
                                       "(escalated or held; this is the agent asking for help)", "ok": True, "s": 0,
                              "error": None})
        reply = log.step("6. Farmer answers on WhatsApp",
                         lambda: whatsapp.receive(args.farmer_phone or old_phone["phone"] or "", "LOG WEEDING demo"))
        inst = _institution_id()
        payment = None
        if inst:
            def pay():
                sub = subscriptions.create(inst, "per_farmer", args.farmers, ["Dagoretti South"])
                return {"subscription": sub["id"], "amount_kes": sub["amount_kes"],
                        **mpesa.stk_push(sub, args.payer_phone, "success")}
            payment = log.step("7. Institution pays by M-Pesa", pay)
    finally:
        if args.farmer_phone:
            with connect() as conn:
                conn.execute("UPDATE plots SET phone = ? WHERE household_id = ?", (old_phone["phone"], hid))

    # --- cost of this one completed outcome ---------------------------------------------------------------------------
    cost = _run_cost(run["run_id"]) if run else {}
    agent_s = (run or {}).get("elapsed_s") or 0
    electricity = WATTS * agent_s / 3600 / 1000 * KES_PER_KWH
    sms_rows = (approved or {}).get("sms") or []
    sms_parts = sum(1 for _ in sms_rows)
    sms_cost_live = [r.get("cost") for r in sms_rows if r.get("cost")]
    sms_price = _env_float("COST_SMS_KES")
    officer_rate, review_min = _env_float("COST_OFFICER_KES_PER_HOUR"), _env_float("OFFICER_REVIEW_MINUTES")
    lines_cost = [f"| Local AI compute (electricity, {WATTS:.0f} W × {agent_s:.0f} s) | KSh {electricity:.3f} | measured time |",
                  "| Cloud AI spend | KSh 0 | the model runs on this computer |"]
    if sms_cost_live:
        lines_cost.append(f"| SMS ({sms_parts}) | {', '.join(sms_cost_live)} | Africa's Talking's own figure |")
    elif sms_price is not None:
        lines_cost.append(f"| SMS ({sms_parts} × KSh {sms_price}) | KSh {sms_parts * sms_price:.2f} | COST_SMS_KES |")
    else:
        lines_cost.append(f"| SMS ({sms_parts}) | not priced | simulated; set COST_SMS_KES or add Africa's Talking keys |")
    if officer_rate is not None and review_min is not None:
        lines_cost.append(f"| Officer review ({review_min:g} min at KSh {officer_rate:g}/h) | "
                          f"KSh {officer_rate * review_min / 60:.2f} | COST_OFFICER_KES_PER_HOUR, OFFICER_REVIEW_MINUTES |")
    else:
        lines_cost.append("| Officer review | not priced | set COST_OFFICER_KES_PER_HOUR and OFFICER_REVIEW_MINUTES |")

    when = datetime.now(timezone.utc)
    live = [f"{c['name']} ({c['state'].lower()})" for c in checks or [] if c["state"] in ("LIVE", "SANDBOX")]
    md = [f"# End-to-end demo, {when.strftime('%Y-%m-%d %H:%M UTC')}", "",
          f"Farm **{hid}** · officer **{officer}** · local model **{config.OLLAMA_MODEL}** "
          f"· run `{(run or {}).get('run_id')}` (its full tool-call log is on the Activity log page) "
          f"({'used' if (run or {}).get('llm_used') else 'not available: deterministic fallback'}"
          f"{'' if llm_ok else ', Ollama model missing'})", "",
          f"**Live systems:** {', '.join(live) or 'none'}. Everything else ran on its built-in simulator.", "",
          "## Steps", "", "| Step | Result | Seconds |", "|---|---|---|"]
    md += [f"| {s['title']} | {'ok' if s['ok'] else 'FAILED: ' + (s['error'] or '')} | {s['s']} |" for s in log.steps]
    md += ["", "## What happened", ""]
    if weather:
        md.append(f"- **Weather:** {len(weather['updated'])} wards updated from "
                  + ", ".join(sorted({p for u in weather['updated'] for p in u['sources']})) + ".")
    if run:
        sc = run["self_check"]
        md.append(f"- **Agent:** status {adv.get('status')}, verdict {(run.get('decision') or {}).get('verdict')}, "
                  f"self-check {sc['outcome']}" + (f"; unsure: {'; '.join(u['detail'] for u in sc['uncertainty'])}"
                                                    if sc["uncertainty"] else "")
                  + f"; {cost.get('mcp_calls', 0)} MCP tool calls, {cost.get('model_calls', 0)} model calls, "
                  f"{cost.get('tokens', 0)} tokens, {agent_s} s.")
        if run.get("recovery"):
            md.append(f"- **Recovered:** {len(run['recovery'])} failure(s) handled (retry / failover / fallback).")
    if approved:
        md.append(f"- **Human gate:** signed by {approved['officer']}; SMS "
                  + ", ".join(f"{r['status'].lower()}" + (f" ({r['error']})" if r.get('error') else '') for r in sms_rows)
                  + "; WhatsApp " + (", ".join(w["status"].lower() + (f" ({w['error']})" if w.get("error") else "")
                                               for w in approved.get("whatsapp") or []) or "not sent (no smartphone)")
                  + ".")
    if reply:
        md.append(f"- **Farmer reply:** command {reply.get('command')}, answered on WhatsApp "
                  f"({reply.get('reply_status', '').lower()}): \"{reply.get('reply')}\".")
    if payment:
        tx = payment.get("transaction") or payment
        md.append(f"- **Payment:** KES {payment['amount_kes']} by M-Pesa, status {tx.get('status')}"
                  + (", simulated" if tx.get("simulated") else ", sent to Daraja") + ".")
    md += ["", "## Cost of this one completed outcome", "", "| Item | Cost | Source |", "|---|---|---|"] + lines_cost
    md += ["", "The institution pays KES 50 per farmer per month; one farmer typically gets several signed advisories a "
               "month, so the price covers SMS and officer time only when those stay below KES 50 per farmer."]
    text = "\n".join(md) + "\n"
    print("\n" + text)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"e2e-{when.strftime('%Y%m%dT%H%M%S')}.md"
    out.write_text(text)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()

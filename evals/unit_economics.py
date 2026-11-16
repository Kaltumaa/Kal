"""The team fact sheet and unit economics, from MEASURED eval logs plus clearly labelled assumptions.

    PYTHONPATH=backend python evals/unit_economics.py          -> FACT_SHEET.md

Follows the challenge's "Unit Economics Teams Must Bring":
  cost per answer  = input tokens × input price + output tokens × output price
  cost per outcome = cost per answer × model calls per outcome + tool, SMS, API and hosting fees
  margin per outcome = price per outcome − cost per outcome
One completed outcome = one officer-signed advisory delivered to one farmer by SMS.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "results"


def latest_model_eval() -> tuple[Path, dict]:
    """The newest eval file that actually ran the local model (meta.llm true)."""
    for f in sorted(RESULTS.glob("2*.json"), reverse=True):
        d = json.loads(f.read_text())
        if d.get("meta", {}).get("llm") and any(r.get("llm_used") for r in d.get("results", [])):
            return f, d
    raise SystemExit("No model eval found: run `make evals` first.")


def main() -> None:
    a = {k: v for k, v in json.loads((ROOT / "evals" / "unit_economics.json").read_text()).items()
         if not k.startswith("_")}
    v = {k: x["value"] for k, x in a.items()}
    f, d = latest_model_eval()
    model = d["meta"]["model"]
    runs = [r for r in d["results"] if r.get("llm_used") and r.get("tokens")]
    outcomes = [r for r in runs if r.get("status") == "PENDING_REVIEW"]       # drafts an officer can sign and send
    base = outcomes or runs
    tok = [r["tokens"] for r in base]
    calls = [r["llm_calls"] for r in base]
    secs = [r["elapsed_s"] for r in base]
    tools = [r["tool_calls"] for r in base]
    tok_mean, tok_max = statistics.mean(tok), max(tok)
    calls_mean, calls_max = statistics.mean(calls), max(calls)
    sec_mean = statistics.mean(secs)
    per_call = tok_mean / calls_mean if calls_mean else 0

    fx = v["kes_per_usd"]
    usd = lambda kes: kes / fx  # noqa: E731
    price_kes = v["price_kes_per_farmer_per_month"] / v["advisories_per_farmer_per_month"]
    sms_kes = v["sms_parts_per_outcome"] * v["sms_kes_per_part"]
    capacity = 30 * 24 * 3600 * v["server_utilisation"] / sec_mean          # outcomes one server drafts a month

    def scenario(mult: int) -> dict:
        farmers = v["pilot_farmers"] * mult
        n = farmers * v["advisories_per_farmer_per_month"]
        servers = max(1, math.ceil(n / capacity))
        hosting_usd = servers * v["server_usd_per_month"] / n
        cost_usd = 0.0 + hosting_usd + usd(sms_kes)                          # model tokens: $0 (open weights, local)
        return {"mult": mult, "farmers": farmers, "outcomes": n, "servers": servers, "hosting": hosting_usd,
                "sms": usd(sms_kes), "cost": cost_usd, "price": usd(price_kes), "margin": usd(price_kes) - cost_usd,
                "officer_hours": n * v["officer_review_minutes"] / 60}
    sc = [scenario(m) for m in (1, 10, 100)]
    p = sc[0]

    def src(k: str) -> str:
        return a[k]["source"]
    today = v["user_cost_today_kes"]
    acre = v["maize_bags_per_acre"] * v["maize_kes_per_bag"]
    spray = v["pesticide_kes_per_acre"] + v["labour_kes_per_day"]
    early, late = acre * v["planting_gain_low"], acre * v["planting_gain_late"]
    faw = acre * v["faw_loss_share"]
    weekly = v["officer_review_hours_per_week"] * 60 / v["officer_review_minutes"]
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = [f"# TALO team fact sheet ({when})", "",
          "Measured figures come from the eval logs "
          f"(`{f.relative_to(ROOT)}`: {len(runs)} model runs of `{model}`, {len(base)} of them reaching a signable "
          "draft). Everything marked *assumption* is in `evals/unit_economics.json` with its source; replace it with "
          "confirmed figures. Regenerate: `PYTHONPATH=backend python evals/unit_economics.py`.", "",
          "**One completed outcome** = one advisory drafted by the agent, signed by a named extension officer, and "
          "delivered to the farmer by SMS.", "",
          "| Figure | Team's number | Verified in demo? |", "|---|---|---|",
          f"| Model(s) and price per 1M input / output tokens | `{model}` (open weights, runs locally in Ollama): "
          "**$0 / $0** per 1M tokens; compute is paid as hosting below | Yes: Ollama logs, AI assurance page |",
          f"| Tokens per answer (input + output) | **{per_call:,.0f}** per model call; **{tok_mean:,.0f}** per completed "
          f"outcome on average, **{tok_max:,}** at worst (measured) | Yes: `tool_calls.token_estimate`, Activity log |",
          f"| Model calls per completed outcome | **{calls_mean:.1f}** on average, **{calls_max}** at worst; plus "
          f"{statistics.mean(tools):.1f} MCP tool calls (measured); {sec_mean:.0f} s per outcome on a laptop CPU | "
          "Yes: Activity log |",
          f"| Tool, SMS, API and hosting fees per outcome | SMS **KES {sms_kes:.2f}** (${p['sms']:.4f}; *assumption*: "
          f"{v['sms_parts_per_outcome']} parts × KES {v['sms_kes_per_part']}); hosting **${p['hosting']:.4f}** at pilot "
          f"(*assumption*: ${v['server_usd_per_month']}/month server); weather (Open-Meteo, Visual Crossing free tier), "
          "MCP, model: $0 | Partly: live SMS cost appears in the demo once Africa's Talking keys are set |",
          f"| Cost per completed outcome (USD) | **${p['cost']:.4f}** ≈ KES {p['cost'] * fx:.2f} at pilot | "
          "Partly (assumed SMS and hosting prices) |",
          "| User's cost today for the same outcome | " + (
              f"From **KES {today:,}** (one spray washed off by rain) to **KES {faw:,.0f}** (a Fall Armyworm attack "
              f"nobody warned about) per acre of maize; a late planting costs **KES {late:,.0f}**; see the table below"
              if today is not None else "**TODO**") + " | Sourced estimates, not measured on Murang'a farms |",
          f"| Price, and who pays | **KES {v['price_kes_per_farmer_per_month']} per farmer per month** ≈ KES "
          f"{price_kes:.2f} (${p['price']:.3f}) per outcome at {v['advisories_per_farmer_per_month']} advisories a "
          "month (*assumption*); paid by the institution (county agriculture department, cooperative or NGO) by "
          "M-Pesa or card; free for farmers | Yes: payment page; Daraja sandbox answered in `make demo-live` (STK push sent) |",
          "| Margin per outcome at pilot / 10× / 100× | " + " / ".join(f"**${s['margin']:.3f}**" for s in sc)
          + " | Calculated (table below) |", "",
          "## Margin at pilot, 10× and 100×", "",
          "| | Pilot | 10× | 100× |", "|---|---|---|---|",
          "| Farmers | " + " | ".join(f"{s['farmers']:,}" for s in sc) + " |",
          "| Outcomes a month | " + " | ".join(f"{s['outcomes']:,}" for s in sc) + " |",
          "| Servers needed | " + " | ".join(str(s["servers"]) for s in sc) + " |",
          "| Model tokens | $0 | $0 | $0 |",
          "| Hosting per outcome | " + " | ".join(f"${s['hosting']:.4f}" for s in sc) + " |",
          "| SMS per outcome | " + " | ".join(f"${s['sms']:.4f}" for s in sc) + " |",
          "| **Cost per outcome** | " + " | ".join(f"**${s['cost']:.4f}**" for s in sc) + " |",
          "| Price per outcome | " + " | ".join(f"${s['price']:.4f}" for s in sc) + " |",
          "| **Margin per outcome** | " + " | ".join(f"**${s['margin']:.4f}**" for s in sc) + " |",
          "| Officer review time a month | " + " | ".join(f"{s['officer_hours']:,.0f} h" for s in sc) + " |", "",
          "## Cost curve", "",
          "- **Gets cheaper with scale:** hosting per outcome (one server drafts about "
          f"{capacity:,.0f} outcomes a month at {sec_mean:.0f} s each), and the model costs nothing per token.",
          "- **Stays flat:** SMS per outcome (no volume discount assumed). It is most of the cost, so negotiating a "
          "bulk SMS rate, or sending WhatsApp to smartphone farmers where Meta's pricing is lower, is the main lever.",
          f"- **Grows linearly:** officer review ({v['officer_review_minutes']} min per outcome, *assumption*). It is the "
          "institution's own staff time, not a TALO fee; at 100× it needs more officers or review in batches "
          "(a ward at a time), never removing the human signature.",
          "- **Other levers:** cache the guidance reads (the same files every run), skip the model for drafts the rules "
          "already settle (the verdict never comes from the model), and use a GPU or a smaller quantised model to "
          "cut seconds per outcome.", "",
          "## What advice is worth to a farmer (one acre of maize)", "",
          f"A conservative acre: {v['maize_bags_per_acre']} bags × KES {v['maize_kes_per_bag']:,} = **KES {acre:,.0f}** "
          "of harvest. What wrong, missing or late advice costs, against TALO's price per advisory:", "",
          "| What goes wrong | What it costs the farmer | Working |", "|---|---|---|",
          f"| Sprays, then it rains: the spray washes off and must be redone | **KES {spray:,.0f}** | pesticide KES "
          f"{v['pesticide_kes_per_acre']:,} + a day of labour KES {v['labour_kes_per_day']} |",
          f"| Travels to the ward office to ask | **at least KES {v['labour_kes_per_day']}** | a lost working day; "
          "the fare comes on top (farms average 6.5-8.3 km from the nearest extension provider, Tegemeo 2015) |",
          f"| Plants at the wrong time | **KES {early:,.0f}-{late:,.0f}** | {v['planting_gain_low']:.0%} of the harvest, "
          f"{v['planting_gain_late']:.0%} for late planters |",
          f"| Fall Armyworm arrives and nobody warns them | **up to KES {faw:,.0f}** | about {v['faw_loss_share']:.0%} "
          "of the harvest, Kenya's average FAW loss |",
          f"| **TALO, per signed advisory** | **KES {price_kes:.2f}**, paid by the institution, free to the farmer | "
          f"KES {v['price_kes_per_farmer_per_month']} a month ÷ {v['advisories_per_farmer_per_month']} advisories |", "",
          f"One avoided washed-out spray pays for **{spray / price_kes:,.0f} advisories**; one avoided late planting "
          f"for **{late / price_kes:,.0f}**. And it is not only money: a lost third of the maize is school fees, food "
          "until the next season, and a family's trust in the next piece of advice.", "",
          "## How many advisories one officer can review", "",
          f"- **Per draft:** about {v['officer_review_minutes']} minutes (a {v['draft_words_measured']}-word draft with "
          f"5 sources). So **{60 / v['officer_review_minutes']:.0f} an hour**, and **{weekly:,.0f} a week** if one day "
          f"({v['officer_review_hours_per_week']} h) goes to the desk.",
          f"- **The gap:** at one advisory a week, an officer serving 13,000 farmers would need "
          f"**{13000 * v['officer_review_minutes'] / 60:,.0f} hours a week**. One person can't do that, with or without AI.",
          f"- **Even the pilot doesn't fit one desk day:** {v['pilot_farmers']} farmers with weekly advice is "
          f"{v['pilot_farmers'] * v['officer_review_minutes'] / 60:,.0f} h a week. So the pilot is shaped to fit: send "
          "only when something changes (a real rain onset, a verified pest nearby, a stage that needs action) rather "
          f"than every week (every two weeks halves it to {v['pilot_farmers'] * v['officer_review_minutes'] / 120:,.1f} "
          "h); sign groups of identical drafts (same ward, crop, stage and verdict) in one review, which is the next "
          "feature to build; and let lead farmers (Nyumba Kumi) pass signed advice on to their cells.",
          "- **Not measured yet:** no published time-use study of Kenyan extension officers was found. Timing "
          "Dennis and Wilson on real drafts is the first pilot measurement.", "",
          "## Assumptions used", "", "| Input | Value | Source |", "|---|---|---|"]
    md += [f"| {k} | {v[k]} | {src(k)} |" for k in a]
    text = "\n".join(md) + "\n"
    (ROOT / "FACT_SHEET.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()

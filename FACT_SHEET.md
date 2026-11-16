# TALO team fact sheet (2026-11-16)

Measured figures come from the eval logs (`evals/results/2026-11-17T001608.json`: 4 model runs of `qwen2.5:7b`, 4 of them reaching a signable draft). Everything marked *assumption* is in `evals/unit_economics.json` with its source; replace it with confirmed figures. Regenerate: `PYTHONPATH=backend python evals/unit_economics.py`.

**One completed outcome** = one advisory drafted by the agent, signed by a named extension officer, and delivered to the farmer by SMS.

| Figure | Team's number | Verified in demo? |
|---|---|---|
| Model(s) and price per 1M input / output tokens | `qwen2.5:7b` (open weights, runs locally in Ollama): **$0 / $0** per 1M tokens; compute is paid as hosting below | Yes: Ollama logs, AI assurance page |
| Tokens per answer (input + output) | **3,022** per model call; **28,712** per completed outcome on average, **31,900** at worst (measured) | Yes: `tool_calls.token_estimate`, Activity log |
| Model calls per completed outcome | **9.5** on average, **10** at worst; plus 11.8 MCP tool calls (measured); 290 s per outcome on a laptop CPU | Yes: Activity log |
| Tool, SMS, API and hosting fees per outcome | SMS **KES 1.60** ($0.0124; *assumption*: 2 parts × KES 0.8); hosting **$0.0200** at pilot (*assumption*: $40/month server); weather (Open-Meteo, Visual Crossing free tier), MCP, model: $0 | Partly: live SMS cost appears in the demo once Africa's Talking keys are set |
| Cost per completed outcome (USD) | **$0.0324** ≈ KES 4.18 at pilot | Partly (assumed SMS and hosting prices) |
| User's cost today for the same outcome | **TODO** from Dennis and Wilson: travel to the officer or a farm visit, waiting time, losses from a wrong spray | No |
| Price, and who pays | **KES 50 per farmer per month** ≈ KES 12.50 ($0.097) per outcome at 4 advisories a month (*assumption*); paid by the institution (county agriculture department, cooperative or NGO) by M-Pesa or card; free for farmers | Yes: payment page; Daraja sandbox answered in `make demo-live` (STK push sent) |
| Margin per outcome at pilot / 10× / 100× | **$0.064** / **$0.076** / **$0.077** | Calculated (table below) |

## Margin at pilot, 10× and 100×

| | Pilot | 10× | 100× |
|---|---|---|---|
| Farmers | 500 | 5,000 | 50,000 |
| Outcomes a month | 2,000 | 20,000 | 200,000 |
| Servers needed | 1 | 4 | 38 |
| Model tokens | $0 | $0 | $0 |
| Hosting per outcome | $0.0200 | $0.0080 | $0.0076 |
| SMS per outcome | $0.0124 | $0.0124 | $0.0124 |
| **Cost per outcome** | **$0.0324** | **$0.0204** | **$0.0200** |
| Price per outcome | $0.0969 | $0.0969 | $0.0969 |
| **Margin per outcome** | **$0.0645** | **$0.0765** | **$0.0769** |
| Officer review time a month | 100 h | 1,000 h | 10,000 h |

## Cost curve

- **Gets cheaper with scale:** hosting per outcome (one server drafts about 5,356 outcomes a month at 290 s each), and the model costs nothing per token.
- **Stays flat:** SMS per outcome (no volume discount assumed). It is most of the cost, so negotiating a bulk SMS rate, or sending WhatsApp to smartphone farmers where Meta's pricing is lower, is the main lever.
- **Grows linearly:** officer review (3 min per outcome, *assumption*). It is the institution's own staff time, not a TALO fee; at 100× it needs more officers or review in batches (a ward at a time), never removing the human signature.
- **Other levers:** cache the guidance reads (the same files every run), skip the model for drafts the rules already settle (the verdict never comes from the model), and use a GPU or a smaller quantised model to cut seconds per outcome.

## Assumptions used

| Input | Value | Source |
|---|---|---|
| kes_per_usd | 129 | assumption: approximate KES/USD rate; update on the day |
| sms_kes_per_part | 0.8 | assumption: Africa's Talking Kenya SMS rate per part; confirm in your Africa's Talking dashboard (the live demo records AT's own cost) |
| sms_parts_per_outcome | 2 | assumption: a signed advisory is up to 320 characters (2 SMS parts), one language |
| advisories_per_farmer_per_month | 4 | assumption: about one signed advisory a week during a season; confirm with Dennis and Wilson |
| price_kes_per_farmer_per_month | 50 | TALO's price. Kept low because Dennis and Wilson (Murang'a officers) said paying is 50/50 and depends on value; payers: their organisation or NGOs such as One Acre Fund |
| pilot_farmers | 500 | assumption: one officer's active farmers; confirm with Dennis and Wilson |
| server_usd_per_month | 40 | assumption: one CPU server (e.g. a small VPS or a mini PC) running the local model, the API and the database |
| server_utilisation | 0.6 | assumption: share of the month the server is busy drafting |
| officer_review_minutes | 3 | assumption: reading the draft and its sources, then signing; measure with Dennis and Wilson |
| user_cost_today_kes | None | TODO: what one advice costs a farmer today (travel to the officer, waiting, a wrong spray). Ask Dennis and Wilson |

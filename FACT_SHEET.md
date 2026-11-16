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
| User's cost today for the same outcome | From **KES 1,785** (one spray washed off by rain) to **KES 14,850** (a Fall Armyworm attack nobody warned about) per acre of maize; a late planting costs **KES 9,000**; see the table below | Sourced estimates, not measured on Murang'a farms |
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

## What advice is worth to a farmer (one acre of maize)

A conservative acre: 15 bags × KES 3,000 = **KES 45,000** of harvest. What wrong, missing or late advice costs, against TALO's price per advisory:

| What goes wrong | What it costs the farmer | Working |
|---|---|---|
| Sprays, then it rains: the spray washes off and must be redone | **KES 1,785** | pesticide KES 1,400 + a day of labour KES 385 |
| Travels to the ward office to ask | **at least KES 385** | a lost working day; the fare comes on top (farms average 6.5-8.3 km from the nearest extension provider, Tegemeo 2015) |
| Plants at the wrong time | **KES 3,150-9,000** | 7% of the harvest, 20% for late planters |
| Fall Armyworm arrives and nobody warns them | **up to KES 14,850** | about 33% of the harvest, Kenya's average FAW loss |
| **TALO, per signed advisory** | **KES 12.50**, paid by the institution, free to the farmer | KES 50 a month ÷ 4 advisories |

One avoided washed-out spray pays for **143 advisories**; one avoided late planting for **720**. And it is not only money: a lost third of the maize is school fees, food until the next season, and a family's trust in the next piece of advice.

## How many advisories one officer can review

- **Per draft:** about 3 minutes (a 129-word draft with 5 sources). So **20 an hour**, and **160 a week** if one day (8 h) goes to the desk.
- **The gap:** at one advisory a week, an officer serving 13,000 farmers would need **650 hours a week**. One person can't do that, with or without AI.
- **Even the pilot doesn't fit one desk day:** 500 farmers with weekly advice is 25 h a week. So the pilot is shaped to fit: send only when something changes (a real rain onset, a verified pest nearby, a stage that needs action) rather than every week (every two weeks halves it to 12.5 h); sign groups of identical drafts (same ward, crop, stage and verdict) in one review, which is the next feature to build; and let lead farmers (Nyumba Kumi) pass signed advice on to their cells.
- **Not measured yet:** no published time-use study of Kenyan extension officers was found. Timing Dennis and Wilson on real drafts is the first pilot measurement.

## Assumptions used

| Input | Value | Source |
|---|---|---|
| kes_per_usd | 129 | assumption: approximate KES/USD rate; update on the day |
| sms_kes_per_part | 0.8 | assumption: Africa's Talking Kenya SMS rate per part; confirm in your Africa's Talking dashboard (the live demo records AT's own cost) |
| sms_parts_per_outcome | 2 | assumption: a signed advisory is up to 320 characters (2 SMS parts), one language |
| advisories_per_farmer_per_month | 4 | assumption: about one signed advisory a week during a season |
| price_kes_per_farmer_per_month | 50 | TALO's price. Kept low because Dennis and Wilson (Murang'a officers) said paying is 50/50 and depends on value; payers: their organisation or NGOs such as One Acre Fund |
| pilot_farmers | 500 | assumption: a first pilot group of 500 farmers in one Murang'a ward (officers there serve about 13,000) |
| server_usd_per_month | 40 | assumption: one CPU server (e.g. a small VPS or a mini PC) running the local model, the API and the database |
| server_utilisation | 0.6 | assumption: share of the month the server is busy drafting |
| officer_review_minutes | 3 | estimate from the measured draft: ~129 words read at ~200 words a minute (about 40 s) plus checking 5 cited sources (about 2 min). For comparison, careful review of a short AI-drafted email is put at 45-90 s (firstsales.io, unmeasured). Measure it with Dennis and Wilson in the pilot |
| user_cost_today_kes | 1785 | computed below as the cheapest single loss: one spray washed off by rain (pesticide + a day of labour). See 'What advice is worth to a farmer' in FACT_SHEET.md for the others |
| maize_bags_per_acre | 15 | conservative low end: national average 22 bags (90 kg) per acre (KALRO/MoA survey, Dec 2025); a Murang'a (Kiharu) farmer reports 17-24 (The Star, Apr 2026) |
| maize_kes_per_bag | 3000 | farm-gate price per 90 kg bag, KES 2,800-3,250 in Nov 2025 (Nation / Milling MEA reports); NCPB buys at 3,500 |
| pesticide_kes_per_acre | 1400 | FAW insecticide for one acre: KES 350 per 50 ml bottle, about 20 knapsack pumps per acre (Standard, Machakos farmer); Egerton estimate KES 1,500 per acre |
| labour_kes_per_day | 385 | agricultural minimum wage, unskilled, KES 385.24 a day (Regulation of Wages (Agricultural Industry) (Amendment) Order 2026, Grant Thornton wages guide 2026) |
| faw_loss_share | 0.33 | Fall Armyworm cost Kenya about a third of its maize: 37% (2017), 33% (2018), De Groote et al. 2020, 1,439 farmers in 121 communities |
| planting_gain_low | 0.07 | optimal planting time: +7-10% yield overall (Black et al., Frontiers in Climate 2023; Kenya, Rwanda, Uganda, Zambia, Malawi) |
| planting_gain_late | 0.2 | optimal planting time: up to +20% for farmers who plant late (same study) |
| draft_words_measured | 129 | measured: farmer message + rationale of a TALO draft in data/database.db (1 draft; re-measure on the pilot), with 5 cited sources |
| officer_review_hours_per_week | 8 | assumption: one working day a week at the desk; the rest stays field work. No published time-use study of Kenyan extension officers was found |

# TALO against the judging framework

Each claim points to something you can run or open. What is simulated, assumed or missing is said plainly.
Numbers: `FACT_SHEET.md` (regenerate with `PYTHONPATH=backend python evals/unit_economics.py`).

## 1. Tool integration & interoperability (30%)

**Integration map** (`make check-integrations` writes the current state, with one harmless real call per system, to
`evals/results/integrations-*.md`):

| System | Used for | State today | With keys |
|---|---|---|---|
| Open-Meteo | Live ward weather | **Live** | (keyless) |
| Ollama: Qwen 2.5 (7B measured; 3B default), Moondream, Whisper | Agent, photo check, voice notes (local) | **Live** | (local) |
| Filesystem MCP server (official, 3rd party) | Guidance documents | **Live** | (local) |
| Our MCP server (`crop_pilot/mcp_server`) | The agent's tools; reusable by any MCP client | **Live** | (local) |
| Visual Crossing | Weather cross-check | Simulated (falls back to single source) | Live (free tier) |
| Africa's Talking | SMS out and in, voice calls | Keys entered; sandbox refused them (HTTP 401), so simulated | Sandbox (`AT_USERNAME=sandbox` + a key made inside the sandbox app) |
| WhatsApp Cloud API (Meta) | Advice to smartphone farmers, farmer commands | Simulated | Sandbox (Meta test number) |
| M-Pesa Daraja | Institution pays per farmer | **Sandbox** (OAuth + STK push answered in `make demo-live`) | Production keys |
| Stripe / Flutterwave | Visa, Mastercard | Simulated | Sandbox (test keys) |
| DeepLeaf | Plant second opinion (officer only) | Off | Live with a key |
| Airtel Money, USSD, county registry / KALRO, KEPHIS API | | **Planned** | see the integration report |

**The agent plans, selects and chains tools** (`agent/workflow.py`): it writes a 7-step plan, the local model chooses
MCP tools (photo check → farm record → outbreak cluster → two weather providers → guidance via the filesystem MCP
server), the rule engine decides, a self-check can send it back once, the draft is written through an MCP write tool,
a follow-up is scheduled, and the run freezes at the human gate. Signed advice then goes out by SMS and WhatsApp.

**Show us the tool-call log:** every call (inputs, outputs, tokens, latency, who approved) is in `tool_calls` and on
the **Activity log** page, filterable to one run. `make demo-live` prints the run id it used.

**If a tool times out or errors:** MCP calls are retried; weather fails over to the other provider, then the last
good forecast, then the ward baseline; the model being down falls back to templates; a corrupt database falls back to
a paper-form backup (eval task 8); SMS / WhatsApp / M-Pesa failures are recorded and never undo a signed advisory.
Each recovery goes to `recovery_log` and the AI assurance page.

**Human approval for consequential actions:** sending advice (named officer types their own name, which must match
their account, and cites the draft's records), confirming a farmer's pest report, verifying a photo diagnosis,
resolving an escalation. The agent has no tool that can send; the database refuses unsigned approvals.

**Credentials:** only in `.env` on the machine running the API (git-ignored; `.env.example` lists them, empty). Never
sent to the browser; webhooks verify each provider's token or signature.

**Connecting to the institution's real system next week:** SMS, WhatsApp and M-Pesa are already written against the
real APIs (switch sandbox → production keys). Airtel Money and a USSD menu follow the same patterns (about a week
each). A county farmer registry is an import into one table plus an MCP read tool.

**Evidence:** `evals/results/integrations-20261116T205614.md` (4 of 9 answered for real: Open-Meteo, Daraja sandbox, Ollama, filesystem MCP) and `evals/results/e2e-20261116T205319.md` (one full outcome: live weather → agent (qwen2.5:7b, 10 MCP tool calls) → officer signs → WhatsApp reply → M-Pesa sandbox payment).

**Gaps:** Visual Crossing, WhatsApp, Stripe and DeepLeaf keys not yet entered, and the Africa's Talking sandbox key was refused, so those rows show Simulated; the 3B model rarely chooses every tool itself
(the harness fills in what it misses, logged per run in EVALS.md).

## 2. Problem relevance & local insight (20%)

**Problem in one line:** in Murang'a County one extension officer serves thousands of smallholders (about 13,000 in
the area officers described to us; 1 : 6,000 published for the county, against FAO's 1 : 400), so farmers like Johnson
decide when to plant, spray or hold without advice, and advice comes late or not at all.

**Pilot: Murang'a County.** Johnson, a young farmer there, and officers there told us farmers mostly don't know the best
time to plant. Planting at the optimal time alone is estimated at +7–10% yield, up to +20% for late planters.
Sources: [FarmBiz Africa, Jan 2025](https://farmbizafrica.com/muranga-gives-extension-to-12000-farmers-a-year-by-funding-agripreneurs/)
(Murang'a 1:6,000; FAO recommends 1:400; 22 ward agriculture officers);
[MoALD Agriculture Extension Manual](https://fsrp.go.ke/sites/default/files/2025-08/Agriculture%20Extension%20Manual%20v1%20final.pdf)
(Kenya about 1:1,380, target 1:600); [CGIAR](https://cgspace.cgiar.org/server/api/core/bitstreams/c1933d15-2928-4bbe-b901-647e2b6ea0e7/content)
(Murang'a about 1:3,500, most wards have a single extension worker);
[Black et al., Frontiers in Climate 2023](https://www.frontiersin.org/articles/10.3389/fclim.2022.993511) (planting at
the optimal time: +7–10% yield, up to +20% for late planters; data from Kenya, Rwanda, Uganda, Zambia, Malawi).

| Check | Status |
|---|---|
| Evidenced | Johnson, a farmer in Murang'a; two extension officers in Murang'a, Dennis and Wilson (about 1 officer : 13,000 farmers in their area; farmers don't know the best time to plant); published ratios with sources above (**TODO:** the rest of their points) |
| Named user | Extension officer at a county agriculture department; the farmer receives the advice |
| Sized | Farmers per officer: about 13,000 (field), 1 : 6,000 (published, Murang'a), 1 : 1,380 (Kenya). Yield at stake from timing: 7–10%, up to 20%. **TODO:** advisories a week, time per farm by hand |
| Today's workaround | **TODO with the officers:** how they advise today (visits, WhatsApp groups, barazas) and why it fails |
| Local reality | Kiswahili and English; feature phones (SMS, voice keypad), Nyumba Kumi lead farmers; data cost (SMS needs none); M-Pesa; Kenya Data Protection Act (gaps listed in README) |
| Why agentic | Each advisory needs several sources checked in order (photo, outbreak cluster, two forecasts, crop stage, rotation, guidance), a judgement on whether it is safe, and asking a human when unsure: a form or chatbot cannot do that |

**Before and after (officer's workflow):**

| | Before | With TALO |
|---|---|---|
| Signals | Forecasts, WhatsApp pest reports and farmer calls arrive separately | Gathered per farm by the agent |
| Cross-check | By hand, farm by farm | Drafted with sources in about 80 s a farm; a ward in minutes |
| Unsure cases | Officer judgement only | Agent flags them and asks; never guesses a treatment |
| Delivery | Visits, calls | SMS (any phone), WhatsApp, voice call; signed by the officer |
| Record | Paper or memory | Every step and signature in the audit log |

**What could make an institution refuse:** no budget line, data-protection concerns, officers not trusting drafts.
Answers: per-farmer price, local model (data stays in the county), the officer signs everything.

## 3. Feasibility & cost-to-serve (20%)

- **Live prototype:** `make run`; `make demo-live` (one complete outcome through the real systems).
- **Unscripted input:** any farm, any officer note (instruction-like notes are caught and the draft locked), any
  farmer SMS / WhatsApp command, any photo.
- **Tokens per answer:** measured from `tool_calls` (Ollama's own counts), model named; live on the AI assurance page,
  and in `FACT_SHEET.md`.
- **Cost per completed outcome, in USD with the working:** `FACT_SHEET.md`.
- **Levers:** local open-weights model ($0 per token), skip the model where the rules settle it, cache guidance
  reads, GPU / smaller quantised model for speed, bulk SMS rate.
- **Weak connection / SMS:** the farmer side needs no data (SMS, voice); the officer's desk and model run on one
  machine, so a slow internet link only affects sending and live weather (which falls back to cached forecasts).
- **Built in the sprint vs reused:** reused open-source libraries (FastAPI, LangGraph, Streamlit, MCP SDK) and open
  models; everything in `backend/` and `frontend/` was written for this challenge.

## 4. User value & willingness to pay (15%)

**Value ladder** (figures in `FACT_SHEET.md`):

| Rung | Figure |
|---|---|
| Cost to serve (per outcome) | measured + assumed, see the fact sheet |
| Price | KES 50 per farmer per month, paid by the institution |
| Willingness to pay | **TODO:** what Dennis and Wilson said about price and budget |
| User's cost today | **TODO:** from the officers (travel, waiting, losses) |

**Who pays:** the institution (county agriculture department, cooperative or NGO) from its extension budget; farmers
pay nothing. **TODO:** the budget line the officers named.

## 5. Scalability & sustainable impact (15%)

- **Margin per outcome at pilot / 10× / 100×:** `FACT_SHEET.md` (positive at all three under the stated assumptions;
  hosting falls with scale, SMS stays flat, officer review grows linearly).
- **Measured at scale:** `make load-test`: the weekly plan for 5,000 farms in under 2 s; 25 officers at once, no
  errors (`evals/results/load-*.md`).
- **Rollout path:** **pilot in Murang'a County** (where we spoke with Dennis, Wilson and Johnson; not yet an agreement) →
  neighbouring counties (Kiambu, Nyeri, Kirinyaga) → other counties; languages beyond Kiswahili and English; USSD and Airtel Money as channels.
- **Oversight at scale:** review by ward in batches, escalations routed to the right sub-county officer, AI assurance
  page counting sign-offs and overrides.
- **Impact metrics (tracked in the audit tables, baseline from the officers):** days from signal to signed advice;
  share of drafts signed vs rejected; sprays blocked before rain; farmers reached by SMS / WhatsApp / voice.

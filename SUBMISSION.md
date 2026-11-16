# Submission text (~300 words)

**Mkulima Hub: climate-smart advisory co-pilot for the Dagoretti South extension desk**

**Track:** Agriculture, The Extension Backlog. **Sub-theme:** 1, Climate-smart advisory (when to plant, spray or hold).
**Why.** Johnson is a young farmer in Murang'a County. Officers there told us one officer serves about 13,000 farmers
in their area (published: 1:6,000 for the county, 1:1,380 for Kenya, against FAO's 1:400). So nobody tells Johnson if
the rains are real or when to plant, and planting on time alone is worth 7–10% more yield. **Our pilot is Murang'a.**
The demo desk is modelled on Dagoretti South's five wards; signals come in, household advice goes out, and a named
officer approves in between.

**What it does.** For each household, or a whole ward in one batch, Mkulima Hub checks rainfall and pest signals
against the plot's history and crop calendar, then drafts a Plant, Spray or Hold advisory and an SMS.

- **Rainfall:** the 7-day outlook, the season against normal, late rains and false starts.
- **Pests:** officer-verified alerts scored by distance and age.
- **Plot history:** crop-rotation risk.
- **Crop calendar:** the growth stage and when pests can damage the crop.

A LangGraph agent on a local open-weights model (Qwen 2.5 via Ollama) chooses which tools to call on our own MCP
server. It also reads pest and pesticide guidance through the official filesystem MCP server. It then stages the draft
and schedules the desk's follow-up, such as a re-scout seven days after spraying. Deterministic rules decide the
safety-critical verdict; the model explains it. Messy records are repaired, prompt injections lock the draft, and a
missing profile halts.

**Human in the loop.** The agent cannot send anything. Drafts wait until an officer types their full name. Database
constraints block unsigned approvals, and a draft built on an outdated forecast cannot be signed. Every action is logged
with its inputs, outputs, tokens and the approving officer, and every recommendation cites its rainfall, plot and
pest-alert records.

**Around the advisory:** officer-verified photo checks; live weather (Open-Meteo, cross-checked with Visual
Crossing); SMS, WhatsApp and voice delivery; institutions pay KES 50 per farmer a month by M-Pesa or card. Every role
signs in, and the API enforces it.

**Honest AI.** Unsure (bad photo, low confidence, forecasts disagreeing, missing data, advice an officer rejected
before), the agent says so and asks the officer. It retries and fails over when tools fail.

**Honesty.** Farm data is synthetic. We spoke with Johnson and two Murang'a extension officers, Dennis and Wilson.
[TODO: the rest of Dennis and Wilson's points.] `make check-integrations`, `make demo-live` and `make load-test` show what runs
live; EVALS.md reports 8 tasks × 5 runs, variation, cost and unfixed failures.

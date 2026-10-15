# Submission text (~300 words)

**Mkulima Hub: climate-smart advisory co-pilot for the Dagoretti South extension desk**

**Track:** Agriculture, The Extension Backlog. **Sub-theme:** 1, Climate-smart advisory (when to plant, spray or hold).
**Office and workflow:** Ministry of Agriculture, Nairobi County extension office, Dagoretti South, five wards. A few
officers serve thousands of smallholders. Signals come in, household advice goes out, and a named officer approves in
between.

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

**Around the advisory:** farmer photos checked by a local vision model and verified by an officer; a crop-calendar view
per household; a learning hub and a moderated community board.

**Honesty.** All data is synthetic and documented as such, and we have not yet validated the workflow with an
extension officer. EVALS.md reports 8 tasks × 5 runs (35/36 pass), run-to-run variation, cost per run, and the failures
we did not fix.

# Submission text (~300 words)

**Crop-Pilot: climate-smart advisory co-pilot for the Dagoretti South extension desk**

**Track:** Agriculture, The Extension Backlog. **Sub-theme:** 1, Climate-smart advisory (when to plant, spray or hold).
**Office and workflow:** Ministry of Agriculture, Nairobi County extension office, Dagoretti South. A few officers serve
thousands of smallholders. Signals come in, household-level advice goes out, and a named officer sits in between.

**What it does.** For each household, Crop-Pilot cross-checks a rainfall outlook (CHIRPS-style cache) and officer-verified
pest alerts against the household's plot history and crop calendar. It then drafts a Plant, Spray or Hold advisory plus
an SMS. A LangGraph agent on a local open-weights model (Qwen 2.5 via Ollama) chooses which tools to call on our MCP
server. That server scrubs messy plot records, computes a spray-safety index, scores pest threats by distance and age,
and writes drafts to a staging queue. The agent also reads pest and pesticide guidance through the official filesystem
MCP server and cites it. Safety-critical ordering is deterministic:
- missing data halts;
- a prompt injection locks the draft;
- washout rain overrides spraying.

**Human in the loop.** The agent cannot send anything. Drafts freeze at an interrupt until an officer types their full
name and confirms. Database constraints make unsigned approvals impossible. Every action is logged with its inputs,
outputs, latency, tokens and the approving officer.

**Around the advisory.** A field-scan page sends farmers' plant photos to a local vision model and matches them against
a pest guide. A photo only becomes a pest alert after an officer verifies it. A Learn hub (pests, pesticides, weeds,
soils, greenhouses, crop suitability) and a moderated community board support farmers between visits.

**Honesty.** All households and weather values are synthetic and documented as such. We have not yet validated the
workflow with an extension officer. EVALS.md reports 8 task types × 5 real runs on the local model, including failures
we did not fix.

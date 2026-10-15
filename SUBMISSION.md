# Submission text (~300 words)

**Crop-Pilot: a climate-smart advisory co-pilot for the Dagoretti South extension desk**

**Track:** Agriculture, The Extension Backlog. **Sub-theme:** 1, Climate-smart advisory (plant, spray or hold).
**Institution and workflow:** Ministry of Agriculture, Nairobi County extension office, Dagoretti South. A desk of a
few officers serves thousands of smallholders. The workflow is: signals in, household-level advice out, with a named
officer in between.

**What it does.** For each household, Crop-Pilot cross-checks a rainfall outlook (CHIRPS-style cache), officer-verified
pest alerts and the household's plot history and crop calendar. It then drafts a Plant, Spray or Hold advisory with a
short SMS for the farmer. A local open-weights model (Qwen 2.5 via Ollama) runs a LangGraph agent. The agent decides
which tools to call on our own MCP server (plot context with data scrubbing, a spray-safety index, pest threat scoring,
and a draft-writing tool). It also reads guidance documents through the official third-party filesystem MCP server.

Safety-critical ordering is deterministic code:
- missing data halts;
- prompt injection locks the draft;
- washout rain overrides spraying.

The model explains the result and writes the message. Where it disagrees with the rules, the disagreement is shown.

**Human in the loop.** The agent has no send capability. Drafts land in a staging queue and the LangGraph thread
freezes at an interrupt. An officer must type their full name and confirm before the message reaches the (simulated)
SMS outbox. Database constraints make an unsigned approval impossible. Every recommendation cites the plot, rainfall,
pest-alert and guidance records it used. Every tool call, model call and human decision is logged with inputs,
outputs, latency, tokens and the approving officer's name.

**Sovereignty and honesty.** Data, checkpoints and model weights stay on the desk's machine (SQLite and Ollama). All
households and weather values are synthetic and documented as such. EVALS.md reports 8 task types × 5 real runs,
including a failure we did not fix.

# Architecture (one page)

**Workflow served:** MoA Nairobi County extension desk, Dagoretti South. Signals in (rainfall outlook, verified pest
alerts, household plot records) → household-level Plant / Spray / Hold **draft** → **named officer signs** → outbound.

```
 Streamlit Control Desk ──HTTP──► FastAPI (backend/crop_pilot/api)
                                     │  POST /runs                      POST /advisories/{id}/approve
                                     ▼                                    │ (typed full name + confirm)
   LangGraph (SQLite checkpointer)                                        ▼
   planner → data_gatherer → advisory_compiler → human_gate ──interrupt──► crop_pilot.dispatch
                 │  model picks tools      │ rules decide; model explains     │ only code that can APPROVE
                 ▼                         ▼                                  │ or write dispatch_outbox
   MCP stdio ┬─ crop-pilot server (ours): get_plot_context, get_rainfall_outlook,
             │                            get_pest_reports, draft_advisory (WRITE → staging queue only)
             └─ filesystem server (3rd-party, read tools only) → data/reference/*.md|csv
                                  ▼
                       SQLite data/database.db (local)  ·  Ollama qwen2.5:3b (local)
```

## Agent shape

| Node | What it does |
|---|---|
| `planner` | Normalises intake, scrubs the officer note, writes the 6-step plan and a run id to telemetry. |
| `data_gatherer` | **The local model chooses the tool calls** (Ollama tool-calling over MCP tool schemas, ≤ 10 turns). A guard blocks out-of-scope households, paths outside the reference library, and any tool not allowed in this phase (including invented ones such as `send_sms`; these are logged as `blocked`). Then the harness checks **coverage and argument correctness**: missing evidence is auto-filled and wrong arguments (e.g. the stale recorded growth stage) are corrected, with an `auto_filled:` / `corrected_args:` flag. |
| `advisory_compiler` | The **deterministic rule engine** (`core/agronomy.decide`) produces the safe verdict. The model sees only a typed, scrubbed evidence view (never raw notes) and returns JSON `{verdict, rationale, farmer_message}`. If its verdict disagrees with the rules, the rules win and a `model_disagreement` flag is shown to the officer. The draft is committed via the MCP `draft_advisory` tool. |
| `human_gate` | `interrupt()`: the thread freezes in the checkpointer. Only the API resumes it, **after** `dispatch` has validated a named officer. |
| `execution_complete` | Closes the run in the audit log with the officer's name. |

**Plot history and household clusters.** The compiler adds a deterministic crop-rotation assessment
(`core/history.py`) to every verdict, as a cited reason plus a farmer tip; it never changes the verdict. `POST
/wards/{zone}/runs` drafts every household in a ward in one batch and logs the cluster's total time, which is the
brief's "household cluster in ~15 minutes versus a season by hand".

## Why this split between rules and model

A 3B model on a CPU must not decide whether to spray before a storm. Safety-critical ordering (missing profile →
injection lock → washout HOLD → verified threat SPRAY → planting window PLANT → monitor) is code that we test and can
defend line by line. The model adds **agency** (it plans and calls the tools) and **language** (rationale, SMS draft).
Its proposals are measured against the rules in EVALS.md.

## Human-in-the-loop is enforced in five independent places

1. **No send tool exists.** Our MCP server has 6 tools, and a test asserts that exact set. The two writes (`draft_advisory`, `schedule_followup`) only touch the staging queue and the desk's internal follow-up list. The filesystem server is filtered to read tools.
2. **`draft_advisory` can only write** `PENDING_REVIEW | SECURITY_LOCK | NEEDS_DATA`. It cannot write APPROVED.
3. **Database CHECK constraints:** APPROVED/REJECTED requires a signature of at least 5 characters; `transmitted_at` requires APPROVED; an outbox row requires a signature; every advisory needs at least one source.
4. **`dispatch` lives outside the agent.** It is reachable only through the API form. A static test fails the build if `agent/`, `mcp_server/` or `core/` import it.
5. **SECURITY_LOCK and NEEDS_DATA drafts cannot be approved**, only rejected.
6. **A draft built on an out-of-date forecast cannot be approved.** "Rainfall estimates shift" (the brief). If a newer
   forecast arrives (`POST /weather/{zone}`) and the spray band, washout risk or 7-day rain changed, `dispatch`
   refuses to sign and the queue asks the officer to re-run the agent.

## MCP servers: built vs borrowed

* **Built: `crop-pilot`** (`backend/crop_pilot/mcp_server/server.py`, Python MCP SDK 1.x / FastMCP). Every tool computes
  something:
  * a spray-safety index formula;
  * a scrubber that repairs corrupt fields, re-derives the growth stage and redacts injections;
  * haversine × severity × recency threat scoring;
  * season anomaly, rainfall versus the long-term mean, and false-start detection (`get_weather_pattern`);
  * a validated, idempotent, source-enforcing write (`draft_advisory`);
  * an internal follow-up scheduler (`schedule_followup`): after every draft the agent books the next desk action
    (re-scout 7 days after a SPRAY, re-check after a washout, seedling check after a false start, field visit for an
    incomplete profile). An officer closes it by name.
* **Borrowed: `@modelcontextprotocol/server-filesystem@2026.8.31`** (official reference server, via `npx`), scoped to
  `data/reference/`. *Why it beats writing our own: path sandboxing and traversal protection are security code, so we
  reuse the maintained, widely audited implementation instead of rolling our own file reader.*

## Farmer hub features and how they feed the advisory loop

* **Field scan:** photo → local `moondream` vision model (via Ollama, on this machine) → caption scrubbed as untrusted text →
  deterministic keyword match against `pest_symptoms.json` → `field_scans` row, status **UNVERIFIED**. Only a named
  officer (`fieldscan.review`, API-only, not importable by the agent) can turn it into a **verified `pest_alert`**. The
  advisory agent then picks that alert up through `get_pest_reports`. A database CHECK makes VERIFIED/DISMISSED
  impossible without a reviewer name. This is a second human gate, on the *input* side.
* **Learn:** the knowledge library in `data/reference/` is the same folder the third-party filesystem MCP server
  exposes to the agent. When the agent drafts a SPRAY it also reads and cites `pesticides_safety.md`. The "What can I
  grow?" tool is a deterministic score over `crop_suitability.csv`.
* **Greenhouse check:** `core/greenhouse.py` computes VPD (Tetens) and dew point (Magnus) from temperature and humidity
  and maps them to plain advice. Readings come from a farmer typing them or a sensor POSTing to `/greenhouse/readings`;
  they are stored in `greenhouse_readings` and are farmer guidance only, never an advisory signal.
* **Community:** a discussion board. Posts are scrubbed, instruction-like posts are held, and the agent never reads it:
  unverified chat is not a signal.

## Data sovereignty

The SQLite file, the LangGraph checkpoints, field-scan photos and both models' weights all live on the officer's machine. The model is
served by local Ollama on `127.0.0.1`. No tokens or records leave the machine at run time.
`npx` downloads the filesystem server from npm once during setup.

## Logging

`tool_calls` records every MCP call, model call, guard block and human decision with: run id, hash, timestamp,
server, tool, actor, inputs, outputs, status, token count (Ollama-reported for model calls, ~4 characters per token
estimated otherwise), latency, and **`approved_by`**, which is back-filled on every row of the run when an officer signs.

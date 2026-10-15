# Mkulima Hub: Architecture (one page)

**Office and workflow:** MoA extension desk, Dagoretti South (Nairobi). Rainfall, pest and plot signals come in; a
household-level **Plant / Spray / Hold draft** goes out; a **named officer signs** before any (simulated) SMS.

```
Streamlit Control Desk ──HTTP──► FastAPI ──► LangGraph (SQLite checkpointer)
                    planner → data_gatherer → advisory_compiler → self_check ⟲ (retry once) → commit_draft → human_gate ─┐
                                               │ model picks tools   │ rules decide, model explains  │
                                               ▼                     ▼                               ▼
   MCP (stdio) ─┬─ crop-pilot (ours, 6 tools): get_plot_context · get_rainfall_outlook ·      dispatch/ (API only):
                │    get_pest_reports · get_weather_pattern · draft_advisory (WRITE) ·        named officer signs →
                │    schedule_followup (WRITE)                                                 outbox, audit log
                └─ filesystem (borrowed, read-only) → data/reference/ guidance, CHIRPS-format history
   Local only: SQLite data/database.db · Ollama qwen2.5:3b (text) + moondream (photos)
```

## Agent shape

- **planner:** normalises the request, scrubs the officer note, writes the plan and run id to the log.
- **data_gatherer:** the local model **chooses its own MCP tool calls** (up to 10 turns).
  - A guard blocks other households, paths outside the library, and invented tools such as `send_sms` (logged
    as `blocked`).
  - The harness then **recovers**: it auto-fills missing evidence and corrects wrong arguments, flagging each fix
    (`auto_filled:` / `corrected_args:`). If the model is down, the run degrades to deterministic gathering.
- **advisory_compiler:**
  - A **deterministic rule engine** decides the verdict, in this order: missing profile → injection lock →
    washout HOLD → verified, in-range pest on a susceptible stage SPRAY → crop-specific planting rain PLANT →
    monitor.
  - **Plot history** (rotation risk) and the **weather pattern** (season vs normal, late rains, false start) add
    cited reasons and one SMS tip. They never flip the verdict.
  - The model writes the rationale and SMS and proposes its own verdict. Where it disagrees, the rules win and the
    officer sees `model_disagreement`.
- **self_check (reflection):** before anything is written, this node checks the draft:
  - the most stringent rain signal wins (no PLANT or SPRAY during a washout or unsafe-spray reading);
  - the ward is in Dagoretti South;
  - the evidence and sources are complete;
  - the SMS is valid.

  On a problem it loops back to `data_gatherer` once; if the check fails again, the draft is withheld as NEEDS_DATA.
- **commit_draft:** calls `draft_advisory`, then `schedule_followup` (e.g. re-scout 7 days after SPRAY).
- **human_gate:** a LangGraph `interrupt()`. Only the API resumes it, after `dispatch` validates a named officer.

**Why rules decide and the model explains:** a 3B model on a CPU must not decide whether to spray before a storm. The
safety ordering is tested code; the model adds agency (tool choice) and language. EVALS.md measures both.

## Human approval is enforced in seven independent places

1. **No send tool exists:** a test asserts our server's exact tool set, and the borrowed server is filtered to read tools.
2. **Limited draft statuses:** `draft_advisory` can only write `PENDING_REVIEW`, `SECURITY_LOCK` or `NEEDS_DATA`, and it
   refuses advice with no source.
3. **Database CHECKs:** approval needs a signature; transmission needs approval; an outbox row needs a signature; every
   advisory needs at least one source.
4. **`dispatch` sits outside the agent:** a static test fails if `agent/`, `mcp_server/` or `core/` import it.
5. **Locked or incomplete drafts:** they can only be rejected.
6. **Changed forecasts:** if a newer forecast changes the spray band, washout risk or 7-day rain, the draft cannot be
   signed until the agent is re-run.
7. **Citations:** sending requires an officer citation that references at least one of the draft's own records.
   It is stored with the approval.

The same pattern gates photos: the farmer never sees the AI's guess. A photo becomes a pest alert, and a result
the farmer can see, only when a named officer verifies it.
The app has an **officer view** (all farms, the only place advice is approved) and a **farmer view** (own farm, signed
advice only, plot-history entries and photo reports). The switch is a demo convenience, not authentication.

## MCP servers: built vs borrowed

- **Built: `crop-pilot`** (Python MCP SDK, FastMCP; runs standalone over stdio, see README). Every tool computes
  something; none proxies an endpoint:
  - a spray-safety formula;
  - a record scrubber (repairs, calendar-derived stage, injection redaction);
  - distance × severity × recency pest scoring;
  - rainfall-pattern analysis;
  - two validated, idempotent writes.
- **Borrowed: `@modelcontextprotocol/server-filesystem@2026.8.31`** (official), scoped to `data/reference/`. *Why it
  beats writing our own:* path sandboxing and traversal protection are security code, so we reuse the maintained,
  audited implementation.

## Sovereignty and logging

- **Local by default:** the database, checkpoints, photos and both models stay on the desk's machine; nothing is sent
  out at run time.
- **Audit log:** `tool_calls` logs every tool call, model call, guard block and human decision. Each entry has inputs,
  outputs, timestamp, latency, tokens, actor and `approved_by`, which is filled on every row of a run once an officer
  signs.

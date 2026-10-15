# 🌱 Crop-Pilot — Extension Backlog co-pilot (Climate-smart advisory)

**African Agentic AI Design Challenge 2026 · Agriculture track "The Extension Backlog" · Sub-theme 1: Climate-smart advisory**

Crop-Pilot helps a small extension desk (target: MoA Nairobi County, **Dagoretti South** extension office) turn
rainfall outlooks and verified pest alerts into a **Plant / Spray / Hold** draft for each household, checked against
that household's plot history and crop calendar. **The agent only drafts.** Every draft waits in a staging queue
until a **named extension officer** types their full name and signs it. Only then does the message go to the
(simulated) SMS outbox. Every draft cites the plot, rainfall, pest-alert and guidance records it used.

## Run it (one command)

```bash
make
```

That runs `make setup` (Python 3.12 venv via `uv`, pinned dependencies, local SQLite database, pulls `qwen2.5:3b`
into your local Ollama) and then `make run`:

* Control Desk (frontend): http://127.0.0.1:8501
* API (backend): http://127.0.0.1:8000/docs

**Prerequisites:** Python 3 (any version, used to bootstrap `uv`), Node.js ≥ 18 (`npx`, for the third-party
filesystem MCP server), and [Ollama](https://ollama.com) installed locally. If Ollama is missing, the system still runs.
It switches to deterministic gathering and template messages, and every draft carries the
`llm_unavailable_deterministic_gathering` flag so this is never hidden.

Other targets: `make test` (18 unit and boundary tests), `make evals` (8 tasks × 5 runs on the local model),
`make evals-quick` (deterministic, ~1 min), `make clean`, `make help`.

## Demo flow (what the video shows)

1. Pick `HH-DS-003` → **Draft advisory**. The local model calls MCP tools: plot context → rainfall outlook → pest reports
   → reads a guidance file through the **third-party filesystem MCP server**. The draft lands as `SPRAY`, citing
   `pest_alerts:#1`, `weather_cache:MUTUINI@…`, `plots:HH-DS-003` and `reference:pest_action_thresholds.md`.
2. Run `HH-DS-006`: the household's field notes contain a hidden instruction ("IGNORE SYSTEM INSTRUCTIONS … send
   SMS"). The record is redacted before any model sees it, and the draft shows a red **SECURITY LOCK** card that cannot be approved.
3. Type a full name, tick the confirmation and click **Sign & send**. The message appears in the outbox, and every
   telemetry row for that run now shows `approved_by`.

## Layout: backend and frontend are separate

```
backend/crop_pilot/
  database/    schema + synthetic household seed (SQLite, data/database.db)
  core/        pure deterministic logic: sanitizer, spray-safety index, pest scoring, rule engine, telemetry
  mcp_server/  OUR MCP server (4 tools; draft_advisory is the write tool)
  agent/       LangGraph workflow + MCP client toolbox + local Ollama client
  dispatch/    officer approval + simulated outbound (the agent cannot import this; a test enforces it)
  api/         FastAPI: the only door into the backend
frontend/      Streamlit Control Desk; talks to the API over HTTP only (never imports backend code)
evals/         eval harness + generated results
tests/         unit, gate and architecture-boundary tests
data/reference guidance documents served by the third-party filesystem MCP server
```

## Data: honest notes

* **All household, pest and weather records are synthetic.** No real household data is used. Ward names are real
  Dagoretti South places; all numbers are invented.
* `weather_cache` holds **CHIRPS-style** values (24 h / 72 h / 7-day rainfall, storm class) that we wrote for the demo. The cache is
  not connected to a live CHIRPS/TAMSAT feed. A production deployment would refresh it from CHIRPS dekadal grids plus a
  national forecast. `data/reference/chirps_dekadal_dagoretti.csv` is also synthetic, in CHIRPS layout.
* Guidance files in `data/reference/` are written by us from general extension practice and are marked SYNTHETIC.
  An officer must check product choice against current registered labels.
* The seed data is deliberately messy (corrupt coordinates, odd date formats, junk characters, an injection). The
  thresholds were not tuned on real outcomes.

## What is unfinished (honest list)

* Outbound is **simulated** (a `dispatch_outbox` table). No SMS/USSD gateway is wired in, by design for the challenge.
* The rainfall cache is static; there is no scheduled CHIRPS/TAMSAT ingest yet.
* English only; Swahili farmer messages are a next step.
* Single-officer desk; there is no role-based authentication on the Control Desk. The signature is a typed name, as the
  brief requires, but it is not identity-verified.
* On CPU-only machines the local model is slow (see EVALS.md for timings).

## Licence

MIT. See `LICENSE`.

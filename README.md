# 🌱 Mkulima Hub — Extension Backlog co-pilot (Climate-smart advisory)

Mkulima Hub (codename crop-pilot in the code).

**African Agentic AI Design Challenge 2026 · Agriculture track "The Extension Backlog" · Sub-theme 1: Climate-smart advisory**

Mkulima Hub helps a small extension desk (target: MoA Nairobi County, **Dagoretti South** extension office) turn
rainfall outlooks and verified pest alerts into a **Plant / Spray / Hold** draft for each household, checked against
that household's plot history and crop calendar. **The agent only drafts.** Every draft waits in a staging queue
until a **named extension officer** types their full name and signs it. Only then does the message go to the
(simulated) SMS outbox. Every draft cites the plot, rainfall, pest-alert and guidance records it used.

## Run it (one command)

```bash
make
```

That runs `make setup` (Python 3.12 venv via `uv`, pinned dependencies, local SQLite database, pulls `qwen2.5:3b`
and `moondream` (vision) into your local Ollama) and then `make run`:

* Control Desk (frontend): http://127.0.0.1:8501 (open it in Chrome, Edge or Safari; the camera needs a real browser)
* API (backend): http://127.0.0.1:8000/docs

**Prerequisites:** Python 3 (any version, used to bootstrap `uv`), Node.js ≥ 18 (`npx`, for the third-party
filesystem MCP server), and [Ollama](https://ollama.com) installed locally. If Ollama is missing, the system still runs.
It switches to deterministic gathering and template messages, and every draft carries the
`llm_unavailable_deterministic_gathering` flag so this is never hidden.

Other targets: `make test` (47 unit, gate, reflection, injection and boundary tests), `make evals` (8 tasks × 5 runs on the local model),
`make evals-quick` (deterministic, ~1 min), `make clean`, `make help`.

## What is in the Control Desk

| Section | Page | What it does |
|---|---|---|
| Advisory | **Dashboard** | Rainfall outlook per ward (spray-safety band, planting window, washout risk), a map of households and verified pest alerts, and what is waiting for you |
| | **Review queue** | Opens with **every farm this week**: Plant now / Spray now / Hold / Ready for harvest / Needs data / Record locked, with the reason from that farm's plot history, crop stage, area rainfall and confirmed pests (a rule preview, no model), and a Draft advice button. Then run the agent for one household or a **whole ward** (a household cluster, timed against the by-hand baseline); each draft shows an urgency state (**When to plant / When to spray / When to hold / Ready for harvest**) and a **Farm & plot history** tab. Sending (**🚀 Send Local Advisory Notification to Farmer**) needs the officer's name, a confirmation and a **citation** that references the draft's own records. **This is the human gate.** A draft whose rainfall forecast has since changed cannot be signed until the agent is re-run |
| | **Farms** | One farm at a time (by farmer name): plot history and rotation risk, a **crop-calendar timeline** with today's position and the stages when pests can damage the crop, the ward's weather pattern, and every draft and follow-up for that household |
| | **Plot history** | Past seasons, rotation risk and the field log. **Farmers add entries** (planting, variety, fertiliser, irrigation, weeding, spraying, harvest) and finished reminders; a planting entry updates the record the agent reads. Read-only for the officer |
| | **Verify photos** (officer) / **AI Scan** (farmer): "Identify plants, weeds, pests & sick plants" | The farmer takes or uploads a photo and sees only "waiting for your officer"; **the AI's guess goes to the officer, never to the farmer**. The officer verifies or changes the diagnosis; the message to the farmer is pre-filled from `data/reference/problem_guide.json` (**what it is, how to fix it, how to prevent it**) and can be edited. The farmer gets it in **Notifications**. A **local** vision model (moondream) describes it, the guide suggests the plant, weed or pest ("AI Analysis: … ⏳ Awaiting Verification"), and an officer must **Verify Assessment** before it becomes an alert the agent uses |
| Farmer hub | **Learn** | Guides on pests & diseases, pesticides & safe use, weeds, soils, greenhouse growing and the crop calendar, plus a **"What can I grow?"** tool filled from each ward's season outlook (reasons quote the numbers, e.g. "420 mm of season rain is within the 300–600 mm this crop needs"; with "Plant now?" from this week's rain and a harvest date), and a **greenhouse check**: type temperature and humidity, or let a sensor POST them to `/greenhouse/readings`, and get VPD, dew point and what to do |
| | **Community** | Discussion board for farmers and officers. Posts are scrubbed; instruction-like posts are held for moderation. The agent never reads it: chat is not a verified signal |
| System | **Activity log** | Every step and decision in plain words, with who approved it; technical details on request |
| | **Sent messages** | Officer-signed (simulated) SMS messages, and the manual backup form used when the database is corrupt |

## Demo flow (what the video shows)

1. **Review queue → New draft**, pick **Grace Wanjiku · Mutu-ini** (`HH-DS-003`), **Run agent**. The local model calls MCP tools: plot context → rainfall outlook → pest reports
   → reads a guidance file through the **third-party filesystem MCP server**. The draft lands as `SPRAY`, citing
   `pest_alerts:#1`, `weather_cache:MUTUINI@…`, `plots:HH-DS-003` and `reference:pest_action_thresholds.md`.
2. Run **Samuel Kiprono** (`HH-DS-006`): his farm record's field notes contain a hidden instruction ("IGNORE SYSTEM INSTRUCTIONS … send
   SMS"). The record is redacted before any model sees it, and the draft is marked **Security lock** and cannot be signed, only rejected.
3. Type a full name, tick the confirmation and click **Sign & send**. The message appears under **Sent messages**, and
   every audit-log row for that run now shows `approved_by` (printed in the backend terminal as `[audit] … approved_by=…`).

## Why one office, and how to add another

The rubric asks whether *a named office* does a real thing faster, so the demo is built around one: the MoA extension
desk for **Dagoretti South** (wards Riruta, Waithaka, Mutu-ini, Ngando, Uthiru/Ruthimitu). Nothing in the code is tied
to it. Wards, households, rainfall and season outlooks are rows of data. To serve another sub-county:
1. add its wards to `weather_cache` and `data/reference/season_outlook.csv` (centroid, rainfall, temperature, soil);
2. load its households into `plots` and its verified alerts into `pest_alerts`;
3. adjust the crop calendar in `config.py` if the altitude differs a lot.

## How a draft is decided (theme 1: rainfall and pest signals against plot history and crop calendar)

| Signal | Where it comes from | What it changes |
|---|---|---|
| Rainfall | `weather_cache` (CHIRPS-style) → `get_rainfall_outlook` | Spray-safety index, planting window, washout HOLD |
| Pests | Officer-verified `pest_alerts` (and verified field-scan photos) → `get_pest_reports` | SPRAY when a verified threat is within its action radius and the crop stage is susceptible |
| Crop calendar | Planting date → calendar-derived growth stage | Which pests matter now; PLANT only before planting and at rain onset |
| Weather pattern | CHIRPS-format dekadal history + season outlook → `get_weather_pattern` | Season below/above normal → variety and drainage advice; late rains; **false-start risk** → "plant in two batches". Never flips the verdict |
| Self-check (reflection) | `self_check` node in the graph, before anything is written | Checks the most stringent rain signal is respected, the ward is in Dagoretti South, and evidence and sources are complete. On a problem it re-gathers once; if it still fails, the draft is withheld as NEEDS_DATA |
| Plot history | `crop_history` (past seasons, oldest → newest) → `core/history.py` | Rotation risk (e.g. maize after maize raises Fall Armyworm, MLN and Striga carry-over), a sourced reason and an SMS tip. It never flips the verdict |

## Two views: extension officer and farmer

The sidebar's **"I am"** switch picks the view:
- **Extension officer** sees every farm, runs the agent, and is the **only one who can approve** advice.
- **Farmer** (e.g. Grace Wanjiku, Mutu-ini) sees only their own farm: crop calendar, alerts, the rainfall numbers
  and rainfall pattern for their area, plot history (read-only), and **advice an officer has already signed**. They
  can set **Reminders** (ticking one done adds it to the field log and the activity log) and send photos to identify
  a plant, weed or pest (an officer verifies). They never see or approve drafts.

This switch is a demo convenience, **not authentication**; real logins are a next step. Farmer names are invented for
the synthetic households, and the codes (e.g. `HH-DS-003`) appear only as references.

## Farmer notifications

A farmer's **Notifications** page lists advice their extension officer signed and sent, results for photos the
officer reviewed, and their own reminders that are due. Drafts and AI output never appear there.

## Security: SQL injection and prompt injection

- **SQL injection:** every query uses parameter placeholders (`?`); user input is never pasted into SQL text.
  Inputs are also validated first (lengths, allowed values, patterns). `tests/test_sql_injection.py` attacks the API
  with classic payloads (`' OR '1'='1`, `; DROP TABLE plots;--`, `UNION SELECT`, …) and checks that no data changed
  and integrity is intact.
- **Prompt injection:** free text from records, forum posts, notes and model output is scrubbed. Instruction-like
  text is redacted or held, and the draft is locked (eval task 6).

## Activity log (readable audit trail)

The officer's **Activity log** page lists every step in plain words: what happened, who did it (local AI, our MCP
tools, the borrowed MCP server, the safety guard, the officer or the farmer), the result, and who approved it.
Inputs, outputs, timings and tokens are under "Technical details". The same records are in `tool_calls`
(`data/database.db`), at `GET /telemetry`, and printed as `[audit]` lines in the backend terminal.

## Reuse our MCP server in your own agent

The `crop-pilot` MCP server is standalone (stdio) and does not depend on our agent or UI. Point any MCP client at it:

```json
{
  "mcpServers": {
    "crop-pilot": {
      "command": "/path/to/crop-pilot/.venv/bin/python",
      "args": ["-m", "crop_pilot.mcp_server.server"],
      "env": {"PYTHONPATH": "/path/to/crop-pilot/backend", "CROP_PILOT_DB": "/path/to/your.db"}
    }
  }
}
```

Or explore it interactively:

```bash
PYTHONPATH=backend npx @modelcontextprotocol/inspector .venv/bin/python -m crop_pilot.mcp_server.server
```

| Tool | Input | Output | Side effects |
|---|---|---|---|
| `get_plot_context` | `household_id` | Scrubbed record: normalised crop, calendar-derived growth stage, repaired coordinates, `data_quality` list, `injection_detected` | none |
| `get_rainfall_outlook` | `lat`/`lon` or `zone_id` | Spray-safety index 0–100 + band, planting window, washout risk, staleness, formula, citation | none |
| `get_pest_reports` | `zone_id`, `lat`, `lon`, `crop`, `growth_stage` | Verified alerts scored by severity × distance × recency; unverified ones listed as ignored; actionable top threat | none |
| `get_weather_pattern` | `zone_id`, `rain_7d_mm` | Season outlook vs normal, last 20 days vs the long-term mean (CHIRPS-format dekads), onset status incl. false-start risk, advice | none |
| `schedule_followup` | `run_id`, `household_id`, `kind`, `days_from_now`, `reason` | Follow-up id and due date | Writes **one** internal task to `followups` (re-scout, re-check after rain, field visit…). Never contacts the farmer; a named officer closes it |
| `draft_advisory` | `run_id`, verdict, message, rationale, `sources`, evidence | Staged draft id | Writes **one** row to `pending_advisories` (non-final status only, idempotent per run, refuses unsourced advice). Cannot send. |

Bring your own data by pointing `CROP_PILOT_DB` at a database with the same schema (`backend/crop_pilot/database/init_db.py`).

## Field validation (honest status)

We have **not yet** tested this with an extension officer or farmer. Everything about the Dagoretti South desk
(caseload, the Plant/Spray/Hold decision, SMS as the channel) is our assumption from public descriptions of Kenyan
extension work. The questions we would take to an officer first:
1. Would you trust a drafted SMS enough to sign it after reading the sources, or would you rewrite it?
2. Which signal arrives first in practice: rainfall forecasts, WhatsApp pest reports, or farmer visits?
3. Is a typed name an acceptable signature, or does the office need an officer ID?

## Layout: backend and frontend are separate

```
backend/crop_pilot/
  database/    schema + synthetic household seed (SQLite, data/database.db)
  core/        pure deterministic logic: sanitizer, spray-safety index, pest scoring, rule engine, telemetry
  mcp_server/  OUR MCP server (6 tools; draft_advisory and schedule_followup write)
  agent/       LangGraph workflow + MCP client toolbox + local Ollama client
  dispatch/    officer approval + simulated outbound (the agent cannot import this; a test enforces it)
  fieldscan/   camera photos -> local vision model -> symptom match -> officer verification -> pest alert
  community/   discussion board (scrubbed, moderated; never read by the agent)
  api/         FastAPI: the only door into the backend
frontend/      Streamlit Control Desk (multi-page: views/); talks to the API over HTTP only
data/reference knowledge library (pests, pesticides, weeds, soils, greenhouse, crop calendar, crop suitability);
               served to the agent by the third-party filesystem MCP server
evals/         eval harness + generated results
tests/         unit, gate and architecture-boundary tests
```

## Data: honest notes

* **All household, pest and weather records are synthetic.** No real household data is used.
* The five wards are the real wards of Dagoretti South Constituency, Nairobi: Mutu-ini, Ngando, Riruta,
  Uthiru/Ruthimitu and Waithaka (source: [NG-CDF Dagoretti South](https://dagoretti-south.ngcdf.go.ke)). Their map
  points are approximate centroids, and every number attached to them is invented.
* `weather_cache` holds **CHIRPS-style** values (24 h / 72 h / 7-day rainfall, storm class) that we wrote for the demo. The cache is
  not connected to a live CHIRPS/TAMSAT feed. A production deployment would refresh it from CHIRPS dekadal grids plus a
  national forecast. `data/reference/chirps_dekadal_dagoretti.csv` is also synthetic, in CHIRPS layout.
* `data/reference/season_outlook.csv` (expected season rain, temperature and soil per ward, used by **Learn → What can I
  grow?**) is synthetic, in the shape a CHIRPS climatology plus a seasonal forecast would give.
* Guidance files in `data/reference/` are written by us from general extension practice and are marked SYNTHETIC.
  An officer must check product choice against current registered labels.
* The seed data is deliberately messy (corrupt coordinates, odd date formats, junk characters, an injection). The
  thresholds were not tuned on real outcomes.
* **Where our data is unusually clean (said plainly, as the brief asks):** the *household* records are messy on purpose,
  but the *rainfall* data is not. Every ward has a complete, on-time forecast with no gaps, no conflicting sources
  and no late CHIRPS dekads. The system flags a stale forecast and halts if a ward has none, but it has never been
  tested against real CHIRPS/TAMSAT latency, gaps or disagreement between products. Pest alerts are also tidier than
  real WhatsApp reports: each has a clean location and date. The advisories would be less certain on real feeds.
* **Officer-entered data is ground truth.** Structured fields (e.g. the planting date) always win over numbers parsed
  from free text, and conflicts are reported; field notes are never parsed into numbers. On **Learn**, numbers the
  officer types override the ward outlook.
* Planting thresholds are rules of thumb: about 25 mm in a week for maize, beans, potato and kale; about 15 mm for
  sorghum and cowpeas, 18 mm for sweet potato vines and 20 mm for groundnut (`config.py`). They should be checked
  with the county's agronomist.

## What is unfinished (honest list)

* Outbound is **simulated** (a `dispatch_outbox` table). No SMS/USSD gateway is wired in, by design for the challenge.
* The rainfall cache is static; there is no scheduled CHIRPS/TAMSAT ingest yet.
* English only; Swahili farmer messages are a next step.
* The vision model is small (1.9 B) and unreliable on its own. We found and fixed real failures. A leading
  prompt made it invent "holes and chewed edges" on a healthy weed, which was then matched to Fall Armyworm. It
  also returns nothing for "answer with one word", and its weed/crop answer flips with word order. It now gets
  neutral questions:
  - "what plant, what condition";
  - weed-or-crop asked three ways, with the majority deciding;
  - "do the leaves look healthy?".

  Matches are filtered by type and host crop, and when the answers disagree the result is "unclear", not a guess.
  If the description names an insect (e.g. "likely aphids"), the photo is treated as a pest photo: your real
  aphid photo is now "Aphids" and your weed photo is "Weed (species unclear)".
  It is still a triage aid for the officer, not a diagnosis.
* The community board has no login; display names are not verified.
* The officer/farmer switch is not authentication; anyone with the app can pick either view.
* Greenhouse: **no physical sensor is connected** in this demo. The "Simulate a sensor reading" button posts a random
  reading through the same endpoint a device (e.g. ESP32 + DHT22) would use. The endpoint has no device authentication
  yet, so expose it only on the office's local network.
* Single-officer desk; there is no role-based authentication on the Control Desk. The signature is a typed name, as the
  brief requires, but it is not identity-verified.
* On CPU-only machines the local model is slow (see EVALS.md for timings).
* `POST /weather/{zone}` (record a newer forecast) has no login yet; in production it would accept only the
  forecast feed or a signed-in officer.
* The full 5-run model evaluation ran just before weather patterns, follow-ups, crop-specific planting and the
  forecast-change guard were added. These do not change the verdict for the eight test households, and the
  deterministic evals pass 8/8 on the final code, but the model-run numbers in EVALS.md describe the earlier build.
* The 3B model rarely completes its own evidence plan; the harness fills and corrects it (see EVALS.md).

## Licence

MIT. See `LICENSE`.

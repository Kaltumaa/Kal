# 🌱 Mkulima Hub — Extension Backlog co-pilot (Climate-smart advisory)

Mkulima Hub (codename crop-pilot in the code).

**African Agentic AI Design Challenge 2026 · Agriculture track "The Extension Backlog" · Sub-theme 1: Climate-smart advisory**

Mkulima Hub helps a small extension desk (target: MoA Nairobi County, **Dagoretti South** extension office) turn
rainfall outlooks and verified pest alerts into a **Plant / Spray / Hold** draft for each household, checked against
that household's plot history and crop calendar. **The agent only drafts.** Every draft waits in a staging queue
until a **named extension officer** types their full name and signs it. Only then does the message go to the
(simulated) SMS outbox. Every draft cites the plot, rainfall, pest-alert and guidance records it used.

## Contents

[Problem statement](#problem-statement) · [Solution overview](#solution-overview) · [Target users](#target-users) ·
[Architecture](#architecture) · [Setup / installation instructions](#setup--installation-instructions) ·
[Usage instructions](#usage-instructions) · [Technology stack](#technology-stack) ·
[Agent architecture](#agent-architecture) · [MCP implementation](#mcp-implementation) ·
[MCP tools / servers](#mcp-tools--servers) · [Human-in-the-loop workflow](#human-in-the-loop-workflow) ·
[Feature phones: Nyumba Kumi, DeepLeaf, voice calls](#nyumba-kumi-cells-deepleaf-and-voice-calls-farmers-without-a-smartphone) ·
[Limitations](#limitations) · [Future improvements](#future-improvements)

## Problem statement

In Kenya, one extension officer can cover over a thousand smallholder farms. Farmers depend on that officer to know
when to plant, when to spray and when to hold off. The short rains have become unreliable (late starts, false starts,
early stops) and pests like Fall Armyworm spread fast between small plots. Good advice means checking each farm's
rainfall, nearby pest reports, plot history and crop stage, and no officer has time to do that for every farm every
week. So advice comes late, generic, or not at all, and a wrong planting or spraying decision costs a smallholder
household seed, money and part of the harvest. The bottleneck is officer time, not knowledge.

## Solution overview

For each farm, or a whole ward at once, an AI agent gathers the 7-day rainfall outlook, the season's weather pattern,
officer-verified pest reports nearby, the plot's history and the crop's growth stage through MCP tools. It drafts a
**Plant / Spray / Hold** advisory and a short SMS, citing every record it used, checks its own draft, and schedules a
follow-up. Nothing reaches a farmer until a named extension officer reviews and signs it. Farmers have their own view:
signed advice, notifications, plot history, reminders, and photos they send for the officer to check.

## Target users

* **Extension officers** (primary): the Dagoretti South desk, Nairobi County. They run the agent, review and sign advice,
  and verify farmers' photos.
* **Smallholder farmers** (beneficiaries): they receive signed advice for their own plot, log their plot history, set
  reminders and send crop photos.

## Architecture

Separate backend (FastAPI + LangGraph agent + MCP servers + SQLite) and frontend (Streamlit, HTTP only). Full one-page
description: [ARCHITECTURE.md](ARCHITECTURE.md).

```mermaid
flowchart LR
  Farmer([Farmer]) -->|plot history, photos| UI[Streamlit frontend]
  Officer([Extension officer]) -->|review + sign| UI
  UI -->|HTTP only| API[FastAPI backend]
  API --> Agent[LangGraph agent<br/>plan > gather > draft > self-check]
  Agent --> LLM[Qwen 2.5 3B<br/>local, Ollama]
  API --> Vision[Moondream<br/>local, Ollama]
  Agent -->|MCP client| Ours[crop-pilot MCP server<br/>6 tools]
  Agent -->|MCP client| FS[Filesystem MCP server<br/>read-only]
  Ours --> DB[(SQLite<br/>farms, history, alerts,<br/>drafts, log)]
  FS --> REF["data/reference<br/>guides, rainfall"]
  Ours --> REF
  Agent -->|draft waits| Gate{{Officer approval gate}}
  Gate -->|signed advice only| Farmer
```

No external APIs are called: the models run locally and all data is synthetic (see [Data](#data-honest-notes)).

## Setup / installation instructions

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

## Usage instructions

1. Open http://127.0.0.1:8501. In the sidebar, **"I am"** picks the view: Extension officer, or a farmer by name.
2. As the officer: **Review queue → Draft advice** for one farm, or run a whole ward. Read the draft and its sources,
   then sign with your full name to send it. **Verify photos** handles farmers' photos.
3. As a farmer: see **My farm** and **Notifications**, add entries in **Plot history**, set **Reminders**, and send a
   photo from **AI Scan**.
4. **Activity log** shows every agent step, tool call and approval in plain words.

What each page does:


| Section | Page | What it does |
|---|---|---|
| Advisory | **Dashboard** | Rainfall outlook per ward (spray-safety band, planting window, washout risk), a map of households and verified pest alerts, and what is waiting for you |
| | **Review queue** | Opens with **every farm this week**: Plant now / Spray now / Hold / Ready for harvest / Needs data / Record locked, with the reason from that farm's plot history, crop stage, area rainfall and confirmed pests (a rule preview, no model), and a Draft advice button. Then run the agent for one household or a **whole ward** (a household cluster, timed against the by-hand baseline); each draft shows an urgency state (**When to plant / When to spray / When to hold / Ready for harvest**) and a **Farm & plot history** tab. Sending (**🚀 Send Local Advisory Notification to Farmer**) needs the officer's name, a confirmation and a **citation** that references the draft's own records. **This is the human gate.** A draft whose rainfall forecast has since changed cannot be signed until the agent is re-run |
| | **Farms** | One farm at a time (by farmer name): terrain (slope, soil, companion crop), plot history and rotation risk, the ward's weather pattern, and every draft and follow-up for that household |
| | **Crop calendar** (officer and farmer) | One calendar per crop on the plot, picked with a button (e.g. **Maize / Beans** for an intercropped plot): growth stages from the planting date, today's position, and the stages when pests can damage that crop |
| | **Plot history** | Past seasons with **every crop grown together** (e.g. "Maize + Beans"; written `Maize+Beans>Kale` in the record, while rotation checks use the main crop), rotation risk and the field log. **Farmers add entries** (planting, also "planted alongside my main crop", variety and seed-label check, fertiliser, irrigation, weeding, spraying, harvest, observations), by typing or a **voice note**; a planting entry updates the record the agent reads. Read-only for the officer |
| | **Verify photos** (officer) / **AI Scan** (farmer): "Identify plants, weeds, pests & sick plants" | The farmer takes or uploads a photo and sees only "waiting for your officer"; **the AI's guess goes to the officer, never to the farmer**. The officer verifies or changes the diagnosis; the message to the farmer is pre-filled from `data/reference/problem_guide.json` (**what it is, how to fix it, how to prevent it**) and can be edited. The farmer gets it in **Notifications**. A **local** vision model (moondream) describes it, the guide suggests the plant, weed or pest ("AI Analysis: … ⏳ Awaiting Verification"), and an officer must **Verify Assessment** before it becomes an alert the agent uses |
| Farmer hub | **Learn** | Guides on pests & diseases, pesticides & safe use, weeds, soils and greenhouse growing, each with a **search box** (it shows only the matching sections and table rows; the two short rule pages, pest action thresholds and when it is safe to spray, have none). Plus **"What can I grow?"**, filled from each ward's season outlook, saying in words how suitable each crop is (**Very suitable / Suitable / Possible with care / Not suitable this season**) with the reasons, "Plant now?" and a harvest date, and a **greenhouse check** (VPD, dew point, what to do) |
| | **Community** | Discussion board for farmers and officers. Posts are scrubbed; instruction-like posts are held. The agent never reads it, **except** that the officer sees farmers' pest reports (also those sent by SMS) under **Pest reports to confirm**: **Confirm** makes a verified pest alert the advice uses and answers with today's **spray-safety reading** for that ward; **Not confirmed** answers too. The answer is posted and texted to farmers who reported by SMS |
| | **Notifications** (farmer) | Signed advice, photo results and due reminders, in the farmer's chosen language. **No internet? Use SMS**: `LOG WEEDING …`, `REMIND 2026-10-20 SPRAY …`, `PROBLEM …` (Kiswahili `REKODI`, `KUMBUSHA`, `SHIDA`) log field work, set reminders and report a problem from any phone; replies, photo results and confirmed reports come back by SMS. A simulated gateway in this build |
| | **Reminders** (farmer) | The farmer's own reminders, typed or by **voice note**; ticking one done adds it to the field log |
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
| Rain-fastness | `weather_cache.dry_hours_ahead`: hours until the next forecast rain | SPRAY becomes **HOLD: Rain due: spray would wash off** if rain is due within 6 hours (desk guidance; the label's rain-fast time may be shorter). The self-check also refuses a SPRAY in that case |
| Wind | `weather_cache.wind_kmh` → `get_rainfall_outlook` | SPRAY becomes **HOLD: Too windy: drift risk to neighbours** above 15 km/h (drift onto neighbours' crops, beehives and water, a common cause of disputes between tightly packed plots); re-check tomorrow morning |
| Field log: weeds | Farmer's own `OBSERVATION` entries with a **"needs weeding: Yes/No"** answer → `get_plot_context` | PLANT becomes **HOLD: Vegetation moisture trap** (clear weeds first) if the latest answer is Yes and no weeding is logged since. Free-text notes are never read for this |
| Field log: past sprays | `SPRAYING` entries with a mode-of-action group (IRAC/FRAC), within the last year | SPRAY advice names the last group **of the same kind** (insect sprays for pests, disease sprays for diseases), notes "twice in a row", and lists the other groups the desk guide gives for that pest (and says if the last one is not on that list, e.g. pyrethroids for Fall Armyworm); cites `plot_actions:#N` |
| False start | `weather_cache.dry_spell_days_ahead`: the longest dry run in the 2-week outlook after this week | PLANT becomes **HOLD: Deceptive false start** when 10 or more dry days are forecast after the rain (seed would sprout, then dry out). A dry past on its own is normal before the season starts, so it only adds "plant in two batches" |
| Slope and soil | `plots.slope` and `plots.soil`, recorded by the officer on a field visit (Farms page) | Slope changes **how** to plant, never whether: farmers on hillsides plant at the rains, so gentle and steep plots get "plant along the contour", and steep ones "tied ridges or fanya juu terraces". Flat black-cotton or clay-loam plots with 60 mm or more in a week: **HOLD: Waterlogging risk** (wait 2–3 dry days or plant on ridges). Unknown terrain behaves exactly as before |
| Rainfall intensity | `weather_cache.peak_rain_mm_h` and its date: the heaviest hour of rain, observed (past) or forecast (today onwards) | A violent downpour (25 mm or more in an hour) forecast in the next 2 days: **HOLD: Hold seeding: violent storm forecast**, because rain that hard on newly sown soil crusts it over the seed; sow just after it passes. One that already fell before sowing does not hold (digging the planting holes breaks that crust). One that fell after sowing tells the officer to check the seedlings are coming through |
| Soil moisture by hand | Farmer's `OBSERVATION` with **"soil moist to a hand's depth (about 15 cm)? Yes/No"**, the check farmers already use | A No in the last 3 days: PLANT becomes **HOLD: Soil not moist yet**. A Yes is quoted in the advice. With no answer, PLANT advice reminds the farmer to check first |
| Intercropping | `plots.intercrop`: the companion crop in the same plot (e.g. beans with maize), set by the officer | Before sowing, a below-normal season adds standard dry-season advice: keep the usual layout (one bean row between maize rows), no extra plants, early-maturing seed, mulch. An above-normal season adds "keep rows open so air moves". A tip only: it never changes the verdict |
| Pest just outside radius | Verified alerts up to 2× the action radius | **Scout within 3 days**, do not spray yet |
| Pest risk window | Crop and growth stage against each pest's susceptible stages, with no confirmed report near | **HOLD: Pest risk window: scout**, with the scouting method and action threshold from the desk guide (e.g. armyworm: 20 plants in a W, act at 10 % fresh damage). It never sprays ahead of a pest: preventive spraying wastes money, kills natural enemies and speeds up resistance |
| Photo quality | Sharpness and brightness of the farmer's photo (no model), plus the vision model's "is there a plant, leaf or insect?" answer | A blurry, dark or unreadable photo is marked **Inconclusive image capture: requires a manual field call** and its AI suggestion is hidden from the officer; the farmer gets a tip to retake it in daylight. A photo with no plant or pest can be closed as **not applicable** (no advice) |
| Group photo review | Waiting photos that are clear, from the same ward, with the same top AI suggestion (symptom-match score 50 % or more) | Shown together as a grid. The officer unticks any that differ and signs once; every photo still gets its own review record and audit line under the officer's name. The score is a symptom match, not a calibrated certainty, so nothing is approved without the officer looking |
| Seed label (KEPHIS) | Farmer's seed or planting entry: **"Seed label check: verified / did not verify / not checked"** after scratching the KEPHIS label and sending the code by SMS | "Did not verify" turns PLANT into **HOLD: Unverified seed** (possible fake seed: return it, report it to KEPHIS). "Verified" is quoted in the advice; otherwise PLANT advice explains how to check. We cannot query KEPHIS from here, so the farmer records the reply |
| Language and delivery | The farmer's preferred language (English, Kiswahili or both, set on their Notifications page) and when they last opened the app | The officer's send boxes start from the farmer's choice. Every signed message is queued as **SMS whatever the farmer's connection** (it needs no data), with typographic punctuation swapped for plain characters so it stays in the cheap SMS alphabet, and the number of SMS parts recorded. The in-app copy is extra, not the main channel |

## Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 (`uv`, pinned `requirements.lock`) |
| Agent orchestration | LangGraph, with a SQLite checkpointer (agent memory, pause/resume at the human gate) |
| LLMs | Qwen 2.5 3B (text) and Moondream (vision), open-weights, run locally with Ollama |
| MCP | MCP Python SDK (FastMCP) for our server and the client; official `@modelcontextprotocol/server-filesystem` (Node.js / `npx`) |
| Backend API | FastAPI + Uvicorn |
| Frontend | Streamlit (multi-page) |
| Database | SQLite (parameterised queries only) |
| Tests / evals | pytest (126 tests), `evals/run_evals.py` (8 tasks × 5 runs) |
| External APIs | None |

## Agent architecture

The agent is a LangGraph state graph:

1. **Planner**: decides which evidence this household needs.
2. **Data gatherer** (MCP client): calls the MCP tools. If the local model is offline it gathers with a fixed plan
   and flags it.
3. **Advisory compiler**: fixed agronomy rules decide Plant / Spray / Hold (safety-critical, never the LLM); the LLM
   explains it and writes the SMS.
4. **Self-check**: checks citations, rain safety and ward. On a problem it goes back to the gatherer once; if it still
   fails, the draft is withheld as NEEDS_DATA.
5. **Commit draft**: `draft_advisory` stages it, and `schedule_followup` adds a desk task.
6. **Human gate**: LangGraph `interrupt()`; the run is checkpointed and waits for the officer.

Memory: run state in the LangGraph checkpointer, and each plot's history in SQLite. Every step is logged to `tool_calls`.

## MCP implementation

The agent is an **MCP client** and connects to two **MCP servers** over stdio at the start of each run:

* **`crop-pilot`** (ours, Python FastMCP): 4 read tools and 2 write tools over our database and reference data. Write
  tools can only stage a draft or add a desk task; nothing can send to a farmer.
* **Filesystem MCP server** (official, borrowed): run with `npx`, limited to `data/reference/` and filtered to its
  read-only tools (`read_text_file`, `read_file`, `list_directory`). The agent reads pest, pesticide and crop guides
  with it and cites them.

The agent discovers the tools at runtime and chooses which to call. Every call is logged with inputs, outputs and
timing. If the filesystem server is unavailable, the run continues and is flagged `third_party_mcp_unavailable`.

## Human-in-the-loop workflow

1. The agent drafts; the draft waits as PENDING_REVIEW in the **Review queue**. The agent has no way to send.
2. The officer reads the draft, its sources and the farm's history, and can edit the message.
3. To send, the officer types their **full name**, ticks a confirmation and adds a **citation** to the draft's own
   records. Database constraints reject unsigned approvals; a draft whose forecast changed, or that tripped the
   injection guard, cannot be signed.
4. Only then does the message go to the (simulated) SMS outbox and the farmer's Notifications.
5. Farmers' photos follow the same rule: the AI's suggestion goes to the officer only, and the farmer sees the
   officer's verified answer.

### Two views: extension officer and farmer

The sidebar's **"I am"** switch picks the view:
- **Extension officer** sees every farm, runs the agent, and is the **only one who can approve** advice.
- **Farmer** (e.g. Grace Wanjiku, Mutu-ini) sees only their own farm: crop calendar, alerts, the rainfall numbers
  and rainfall pattern for their area, plot history (read-only), and **advice an officer has already signed**. They
  can set **Reminders** (ticking one done adds it to the field log and the activity log) and send photos to identify
  a plant, weed or pest (an officer verifies). They never see or approve drafts.

This switch is a demo convenience, **not authentication**; real logins are a next step. Farmer names are invented for
the synthetic households, and the codes (e.g. `HH-DS-003`) appear only as references.

## Nyumba Kumi cells, DeepLeaf and voice calls (farmers without a smartphone)

Many farmers here, especially older ones, have a feature phone (kabambe) and no data. Three pieces reach them:

- **Nyumba Kumi cells.** Up to ten neighbouring households; one **lead farmer** with a smartphone can send a photo
  for a neighbour (**My farm → Nyumba Kumi**). The photo is filed under the neighbour's farm and marked as sent by the
  lead. The lead sees only waiting / the officer's finding, never the AI's guess. The officer records each farm's
  phone, phone type and cell on **Farms**. Demo cells: Riruta (lead Peter Njoroge) and Uthiru (lead Paul Mutua).
  Phone numbers in the demo are fake (`+25470000xxxx`) and are never sent to the browser.
- **DeepLeaf second opinion (optional, off by default).** With `DEEPLEAF_API_KEY` (an organisation key) in `.env`,
  each photo also goes to DeepLeaf's Agronomist through their OpenAI-compatible server API
  (`POST https://api.deepleaf.org/v1/agronomist/chat/completions`, `model: "agronomist"`, `x-deepleaf-farmer-id`
  header, photo as a base64 data URL; checked against their published `/v1/openapi.json`). The key must be an
  Auth-issued organisation key (`feed_the_world_…`) with the `agronomist` scope. No SDK is needed: their `@deepleaf/agronomist-sdk` is
  a React package for browsers, and organisation keys must stay on the server, which is where this call runs. Its reply is shown to the officer as
  "second opinion · not verified", next to the local AI. It never reaches a farmer unless the officer puts it in
  their own message, and it never changes a Plant/Spray/Hold verdict. Before sending, the photo is re-encoded (this
  drops EXIF, including GPS) and the farmer id is a salted hash, not a name or phone number. The API returns
  text, so we ask for an English note to the officer and a short Kiswahili draft the officer can edit into a call.
  We have not run it against the live API yet; the request format is tested against DeepLeaf's documented shape. Turning it on sends farmers' photos to a cloud service,
  so get the farmer's consent first.
- **Photo drafts from Qwen (two keys).** After the vision step, qwen2.5:3b turns the diagnosis text (DeepLeaf's if on,
  else the local model's) into `{"extension_officer_draft", "farmer_kiswahili_voice_script"}`
  (`fieldscan/voice_draft.py`). Both are drafts on **Verify photos**; the officer edits and signs. The Kiswahili
  script always ends with *"Kama umeelewa, bonyeza moja. Kama unahitaji msaada wa kiongozi wako wa Nyumba Kumi,
  bonyeza mbili."*, added by code. **qwen2.5:3b cannot write Kiswahili**: asked for it, it looped one word until the
  JSON was cut off. So by default it writes only the English officer draft and the Kiswahili comes from a plain
  template with common pest names (viwavijeshi, vidukari, ukungu). `CROP_PILOT_SW_MODEL=1` asks a stronger model for
  both keys; a loop guard still rejects broken Kiswahili. The templates still need a native speaker's review.
- **Voice calls.** When signing advice or verifying a photo, the officer can tick **Also phone the farmer**. The call
  reads out exactly what the officer signed (Kiswahili if they signed Kiswahili), then: *press 1 if you understood,
  2 if you need help from your Nyumba Kumi lead farmer, 0 to hear it again* (farms in no cell: 2 = help from the
  officer). Pressing 2 puts a **Needs help** alert on the lead farmer's Nyumba Kumi page, texts the lead, and adds a
  follow-up to the officer's Dashboard. The SMS is always sent too, and a call problem never undoes a signed SMS.
  One webhook, `POST /voice/callback`, takes every carrier event as form fields (`isActive`, `callerNumber`,
  `dtmfDigits`, `hangupCause`, `durationInSeconds`, `amount`); the hang-up stores duration and cost.
- **Built-in phone company (no telecom account).** Carrier accounts need a business registration and payment, so the
  demo simulates the carrier. When a simulated call is placed, `simulate_telephony_carrier_loop` runs in a background
  thread: after 2 s it POSTs a pick-up to our own `/voice/callback`, after 5 s a keypress (`VOICE_SIM_DIGIT`: usually
  1, sometimes 2), then the hang-up with the measured duration and a **simulated** cost (3 KES a minute, not a real
  tariff). It is real HTTP through the same handler a live Africa's Talking call would hit, so switching to the real
  carrier is configuration only. It is on in `make run` (`VOICE_AUTO_SIMULATE=1`); set it to 0 to press the keys
  yourself on **System → Phone calls**. Simulated keypresses are labelled as such and are not farmer responses.

### Real calls: Africa's Talking + ngrok

Only the small webhook app (`crop_pilot.api.voice_hooks`, port 8001) goes on the internet. The main API (8000)
holds the officer's approve buttons and has no login, so **never run `ngrok http 8000`**.

1. In Africa's Talking, get a **voice number** (voice does not work in the sandbox; calls cost airtime) and an API key.
2. Start the app as usual: `make run`.
3. In a second terminal, start ngrok on the webhook port and copy the `https://…` forwarding URL:
   `ngrok http 8001` (a reserved domain, e.g. `ngrok http --url=mkulima.ngrok-free.app 8001`, keeps the URL the same
   between restarts, so step 6 is done once).
4. Pick a secret: `openssl rand -hex 16`.
5. Export the same settings in **both** terminals (the API places calls; the webhook app answers them), then restart
   `make run` and start the hooks with `make voice-hooks`:

   ```bash
   export AT_USERNAME=your_at_username AT_API_KEY=your_at_key AT_VOICE_NUMBER=+2547XXXXXXXX
   export VOICE_PUBLIC_URL=https://mkulima.ngrok-free.app VOICE_WEBHOOK_TOKEN=the_secret_from_step_4
   ```
6. In the Africa's Talking dashboard (Voice → your number → callback URL) set
   `https://mkulima.ngrok-free.app/voice/callback?t=the_secret_from_step_4`. Keypresses come back to the same URL.
7. Check: `curl https://mkulima.ngrok-free.app/health` shows `"channel": "AFRICAS_TALKING"`, and **System → Phone
   calls** no longer says "Simulated".

Africa's Talking does not sign its requests, so the webhooks refuse any request without the token (403) and any
session id we did not place (`<Reject/>`). Test a real call on your own phone first. **Listen to the Kiswahili**:
the spoken voice is Africa's Talking's text-to-speech (`AT_SAY_VOICE`, default `woman`), and we have not yet heard
how it pronounces Kiswahili. If it sounds wrong, the next step is a recorded message played with `<Play>`.

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

## MCP tools / servers

| Server | Transport | Tools |
|---|---|---|
| `crop-pilot` (ours) | stdio | `get_plot_context`, `get_rainfall_outlook`, `get_pest_reports`, `get_weather_pattern`, `draft_advisory` (write), `schedule_followup` (write) |
| `@modelcontextprotocol/server-filesystem@2026.8.31` (official) | stdio via `npx` | `read_text_file`, `read_file`, `list_directory` (read-only, `data/reference/` only) |

### Reuse our MCP server in your own agent

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

**We spoke with one smallholder farmer** (name withheld; no personal details recorded). What they told us:
- Farmers like them still rely mainly on **traditional methods** and their own experience to decide when to plant
  and when to spray.
- They **don't know of any website or app** that gives this kind of help for their own farm.
- They said there is **real demand** for a tool like this.

This is one conversation, not a study, and it did not test the app itself. We have **not yet** spoken with an
extension officer. Everything about the Dagoretti South desk (caseload, the Plant/Spray/Hold decision, SMS as the
channel) is our assumption from public descriptions of Kenyan extension work. The questions we would take to an
officer first:
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
* Wind speeds per ward (`weather_cache.wind_kmh`) are synthetic, like the rainfall. The 15 km/h spraying limit and the
  photo sharpness/brightness cut-offs are our rules of thumb (the photo ones were measured on real farmer photos against
  blurred and darkened copies); they should be checked with the county's agronomist. Lucy Wambui (`HH-DS-010`,
  Riruta) is a demo farm added to show the wind hold.
* The 2-week dry-spell outlook (`dry_spell_days_ahead`) is synthetic; a real one would come from KMD or ICPAC
  sub-seasonal forecasts. The 10-day line follows the usual false-start idea (a long dry spell soon after onset) and
  should be checked with the county's agronomist. Rose Chebet (`HH-DS-014`, Mutuini, cowpeas) shows the false-start
  hold.
* Slope and soil are entered by the officer from a pick-list, not worked out from GPS: we have no elevation or soil
  map in this build. Dagoretti is mostly red volcanic soil, so the waterlogging hold (black cotton or clay loam,
  60 mm in a week, our rule of thumb) will rarely fire there. Daniel Kamau (`HH-DS-011`, Riruta, steep hillside) shows
  slope advice: he plants with Peter, along the contour.
* Peak rain per hour (`peak_rain_mm_h`) is synthetic. Real values come from automatic weather stations, radar or a
  thunderstorm warning, not from CHIRPS (which is daily). The 25 mm/h line is the usual threshold for erosive tropical
  rain (Hudson). Faith Akinyi (`HH-DS-012`, Uthiru, sorghum, 42 mm/h storm forecast tomorrow) and John Otieno
  (`HH-DS-013`, Ngando, maize with beans in a below-normal season) show the storm hold and the intercrop tip.
* Hours to the next rain (`dry_hours_ahead`) are synthetic; a real value would come from a short-range forecast
  (KMD or a nowcast). Paul Mutua (`HH-DS-015`, Uthiru, beans just up) shows the pest risk window. Every maize farm in
  the demo sits within 5 km of a confirmed armyworm report, which is realistic for a sub-county this small.
* KEPHIS seed labels are verified by scratching the label and sending the code by SMS (1393 on most labels; one 2026
  campaign used 1397, so the app says "the number on the label"). This build has no link to the KEPHIS system.
* All the planting and spraying holds above were reviewed for how farmers actually work, but only one farmer has been spoken to so
  far: every threshold needs checking with extension officers and the county agronomist before real use.
* Planting thresholds are rules of thumb: about 25 mm in a week for maize, beans, potato and kale; about 15 mm for
  sorghum and cowpeas, 18 mm for sweet potato vines and 20 mm for groundnut (`config.py`). They should be checked
  with the county's agronomist.

## Limitations

* Outbound is **simulated** (a `dispatch_outbox` table). No SMS/USSD gateway is wired in, by design for the challenge.
* **Offline, honestly:** the web app itself needs a connection, and a photo cannot travel without data (basic phones
  cannot send pictures by SMS). What works offline is SMS: field-log entries, reminders and problem reports in, and
  every answer out. A photo is sent from AI Scan when the farmer has a connection, or taken by the officer on a visit.
  Making the app itself work offline (queue entries on the phone, send later) needs a mobile or installable web app.
* **Voice notes** use Whisper ("small", via `faster-whisper`, `make voice`) on this computer; nothing leaves it. It
  handles English and Kiswahili; Sheng and other local languages are not offered. The text is only a draft that the
  farmer checks before saving. Tested on English speech; Kiswahili accuracy on real farmer recordings is not yet
  measured. Not installed on the free online demo, where the record button says so and the farmer types instead.
* We do not guess whether a farmer is online: SMS goes to everyone, because a missed planting or spraying window costs
  more than a text. "Last opened the app" is shown to the officer for context only. Sheng and other regional wording
  are not generated: they vary by area and a small model would invent them; the officer can reword any message.
* The rainfall cache is static; there is no scheduled CHIRPS/TAMSAT ingest yet.
* Swahili farmer messages use **fixed templates** for Plant / Spray / Hold (shown next to the English draft; the
  officer edits them and ticks which language(s) to send under one signature). Crop and pest names stay in English
  unless a Swahili term is in `data/reference`. The templates do not include the English seasonal or rotation tip,
  and they have not yet been checked by a native-speaker extension officer.
  Translation by the local model exists but is off by default (`CROP_PILOT_SW_MODEL=1`). Its output must keep every
  number and name and must not repeat itself, or the template is used. In our tests, though, `qwen2.5:3b` wrote
  Swahili that passed those checks and still meant nothing.
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

## Future improvements

* Real SMS / USSD delivery through a gateway such as Africa's Talking, after officer sign-off.
* Live CHIRPS / TAMSAT rainfall and a national forecast feed instead of the static cache.
* Slope from a digital elevation model (e.g. SRTM) and soil from a soil map (e.g. iSDAsoil) at the plot's GPS point,
  as a suggestion the officer confirms on the visit, instead of entering both by hand.
* Swahili messages reviewed by native-speaker officers, a stronger local translation model, and other local languages.
* Officer and farmer logins, with a verified officer ID as the signature.
* Field validation with Dagoretti South extension officers and farmers, then tuning thresholds on real outcomes.
* A larger, field-tested vision model for crop photos.
* More sub-counties: add their wards and households as data (see "Why one office").

## Online demo (free hosting)

The live link runs on Streamlit Community Cloud. It is free, so it has no room for the local AI models: drafts come
from the fixed rules (the agent's normal fallback), and photos reach the officer without an AI suggestion. The officer
review, signing, citations, follow-ups, farmer view and our MCP server work the same; the borrowed filesystem
MCP server runs only if the host has a recent Node.js. `frontend/cloud.py` starts the
backend as its own process there; locally `make run` does that instead. To deploy your own copy: share.streamlit.io →
Create app → this repo, branch `main`, file `frontend/app.py`, Python 3.12.

## Licence

MIT. See `LICENSE`.

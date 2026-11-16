# Plant AI service

A leaf-disease model trained on PlantVillage and PlantDoc, a `fastmcp` server with three tools, and a FastAPI orchestration layer for the frontend. Outbreak alerts wait for a named officer before they are sent.

| File | What it does |
|---|---|
| `prepare_dataset.py` | Merges the 28 crop-disease classes that PlantVillage (`raw/color`) and PlantDoc (`train`, `test`) share into `~/plant_ai_data/dataset/{train,val}/<crop>__<condition>/`. It checks every image, removes exact duplicates, and keeps validation images out of training. |
| `train.py` | Fine-tunes `timm` EfficientNet-B0 (ImageNet weights) on the merged set and saves `plant_ai_model.pth` plus `plant_ai_model.metrics.json`. |
| `plant_model.py` | The model, the image transforms and the checkpoint loader, shared by training and serving. |
| `mcp_server.py` | MCP server `plant-ai` with three tools: `diagnose_crop_leaf`, `check_regional_outbreak` (SQLite `data/plant_ai.db`) and `draft_extension_advisory`. It has no send tool. |
| `agent.py` | The diagnosis agent. It writes a numbered plan, runs each step with retries and fallbacks, checks its own answer, re-plans once to fix what it can, and otherwise answers "I'm not sure" and queues the case for an officer. |
| `weather.py` | Gets the forecast from Open-Meteo (through the MCP server, or the direct API if that server is down) and from Visual Crossing, and cross-checks them. A provider that fails is retried, then the other one is used, then a cached forecast. |
| `agent_api.py` | FastAPI app with CORS. It connects `plant-ai` and the external Open-Meteo MCP server (`open-meteo-mcp-server@2.5.6`, MIT, keyless), runs the diagnose pipeline, and holds outbreak alerts for a named officer's approval. |

## Setup

```bash
python3.13 -m venv ~/.venvs/plantai && ~/.venvs/plantai/bin/pip install -r backend/plant_ai/requirements.txt
```

The merged dataset is written outside the project, to `~/plant_ai_data/dataset`. Writing about 41,000 small files into an iCloud-synced Desktop stalled the merge. Change the location with `--out`/`--data` or `PLANT_AI_DATASET`.

Keep the venv outside iCloud-synced folders. On a synced Desktop, macOS offloaded 1,901 of the venv's files to iCloud, and Python then stalled while importing them.

Set `VISUAL_CROSSING_API_KEY` to turn on the second weather source. Without it, forecasts come from Open-Meteo only and are reported as `SINGLE_SOURCE` (not cross-checked).

This service has its own venv because `fastmcp` 4 needs `mcp` 2.x, while the main backend pins `mcp<2`. The weather server needs Node.js (`npx`). Set `WEATHER_MCP_COMMAND` to run it some other way.

```bash
~/.venvs/plantai/bin/python backend/plant_ai/prepare_dataset.py --clean
cd backend/plant_ai && ~/.venvs/plantai/bin/python train.py --epochs 10
~/.venvs/plantai/bin/python -m uvicorn agent_api:app --port 8010
```

## API (JSON)

| Method | Path | |
|---|---|---|
| GET | `/api/health` | Model file and MCP servers, with their tools |
| POST | `/api/diagnose` | `{image_base64, region, lat?, lon?, crop?}` returns diagnosis, outbreak, weather, advisory, `alert`, `trace` |
| POST | `/api/diagnose/upload` | The same, as a multipart form (`image`, `region`, `lat`, `lon`, `crop`) |
| GET | `/api/weather?lat=&lon=` | Forecast through the weather MCP server |
| GET | `/api/outbreaks?region=&days=` | Case counts per region and disease |
| GET | `/api/reviews?status=` | Cases where the agent said "I'm not sure" (`POST /api/reviews/{id}/resolve` with `{officer_name, diagnosis}`) |
| GET | `/api/recovery?run_id=` | Self-check audit log: each failure, the recovery action taken, and what was used instead |
| GET | `/api/alerts?status=` | Outbreak alerts (`PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `DISPATCHED`) |
| POST | `/api/alerts/{id}/approve` | `{officer_name, note?, message?}`: the human gate. Only this sends (simulated SMS outbox). |
| POST | `/api/alerts/{id}/reject` | `{officer_name, note?}` |

## What `/api/diagnose` returns

- **`answer_status`:** `CONFIDENT` or `UNCERTAIN`. A photo it cannot read returns HTTP 400 with the plan and the reason.
- **`message`:** plain language. When uncertain it starts with "I'm not sure: …", gives the reasons, and says an officer will check.
- **`plan`:** seven steps (diagnose, outbreak, weather, advise, self_check, recover, human_gate), each with a status and a note.
- **`uncertainty`:** a list of reasons, each with a code: `low_confidence`, `photo_quality`, `close_call`, `weather_disagreement`, `no_weather`.
- **`recovery`:** each failure and what was done about it, for example "retried" or "failover to Visual Crossing".
- **Also included:** `self_check`, `trace`, `diagnosis`, `outbreak`, `weather` (with `agreement`: `AGREE`, `DISAGREE`, `SINGLE_SOURCE` or `NO_DATA`), `advisory`, `alert` and `review_request`.

## Rules

- **Confidence threshold.** Below 75% confidence, or with a blurry or dark photo, the diagnosis is marked `needs_human_review`. The advisory then refuses to name a treatment, and the case is not counted toward outbreaks.
- **Outbreak spike.** A spike is at least 3 cases of one disease in a region within 7 days, and at least twice the weekly average of the 4 weeks before. A spike creates one `PENDING_APPROVAL` alert per region and disease.
- **Rain and spraying.** If rain is due within 6 hours, or heavy rain within 24 hours, the advice says to spray only after it passes.
- **Allowed origins.** CORS origins come from `PLANT_AI_CORS_ORIGINS` (comma list). The default `*` is for local development only.

## Tests

```bash
~/.venvs/plantai/bin/python -m pytest backend/plant_ai/tests -q
```

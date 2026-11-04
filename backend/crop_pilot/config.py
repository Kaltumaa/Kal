"""Central configuration. Every threshold the agent relies on lives here so it can be audited."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
REFERENCE_DIR = DATA_DIR / "reference"

DB_PATH = Path(os.environ.get("CROP_PILOT_DB", DATA_DIR / "database.db"))
CHECKPOINT_DB_PATH = Path(os.environ.get("CROP_PILOT_CHECKPOINT_DB", DATA_DIR / "checkpoints.db"))
FALLBACK_QUEUE_PATH = Path(os.environ.get("CROP_PILOT_FALLBACK", DATA_DIR / "manual_fallback.jsonl"))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
VISION_MODEL = os.environ.get("CROP_PILOT_VISION_MODEL", "moondream")
LLM_TIMEOUT_S = float(os.environ.get("CROP_PILOT_LLM_TIMEOUT", "120"))
DISABLE_LLM = os.environ.get("CROP_PILOT_DISABLE_LLM") == "1"
# Swahili farmer messages come from fixed templates unless this is on. Off by default: in our tests qwen2.5:3b wrote
# Swahili that kept the numbers and names but was meaningless (and once vulgar). Turn on for a stronger local model.
SW_TRANSLATE_WITH_MODEL = os.environ.get("CROP_PILOT_SW_MODEL") == "1"

# --- Optional cloud second opinion on photos: DeepLeaf Agronomist (their server API) ----------------------------
# Off unless a key is set. The local vision model still runs; DeepLeaf's reply is shown to the officer only.
DEEPLEAF_API_KEY = os.environ.get("DEEPLEAF_API_KEY", "")
# Server API (OpenAI-compatible), as published in https://api.deepleaf.org/v1/openapi.json ("servers").
DEEPLEAF_BASE_URL = os.environ.get("DEEPLEAF_BASE_URL") or "https://api.deepleaf.org/v1/agronomist"
DEEPLEAF_TIMEOUT_S = 60.0
# Farmers are sent to DeepLeaf as a salted hash of the household id, never a name or phone number.
DEEPLEAF_ID_SALT = os.environ.get("DEEPLEAF_ID_SALT") or "mkulima-hub"

# --- Voice calls to feature phones: Africa's Talking Voice -------------------------------------------------------
# All four must be set for real calls; otherwise calls are SIMULATED (logged, answered from the officer's screen).
AT_USERNAME = os.environ.get("AT_USERNAME", "")
AT_API_KEY = os.environ.get("AT_API_KEY", "")
AT_VOICE_NUMBER = os.environ.get("AT_VOICE_NUMBER", "")          # your Africa's Talking voice number, +254...
VOICE_PUBLIC_URL = os.environ.get("VOICE_PUBLIC_URL", "").rstrip("/")   # e.g. https://abcd.ngrok-free.app
# Shared secret in the webhook URLs (?t=...). Africa's Talking does not sign callbacks, so without it anyone who
# finds the URL could mark calls answered. Required for real calls.
VOICE_WEBHOOK_TOKEN = os.environ.get("VOICE_WEBHOOK_TOKEN", "")
AT_SAY_VOICE = os.environ.get("AT_SAY_VOICE") or "woman"
# Internal carrier simulator (no telecom account): after a simulated call is placed, a background thread posts
# pick-up, keypress and hang-up to our own /voice/callback. On in `make run`; off by default (tests, scripts).
VOICE_AUTO_SIMULATE = os.environ.get("VOICE_AUTO_SIMULATE") == "1"
VOICE_SIM_SERVER_URL = os.environ.get("VOICE_SIM_SERVER_URL") or "http://127.0.0.1:8000"
VOICE_SIM_DIGIT = os.environ.get("VOICE_SIM_DIGIT") or "random"       # 1 | 2 | 0 | none | random
VOICE_SIM_RING_S = float(os.environ.get("VOICE_SIM_RING_S") or 2)
VOICE_SIM_TALK_S = float(os.environ.get("VOICE_SIM_TALK_S") or 5)
VOICE_SIM_RATE_KES_PER_MIN = 3.0   # SIMULATED cost per started minute, for the demo meter; not a real tariff
VOICE_MAX_PLAYS = 3            # a farmer can press 0 to hear the message again, up to this many plays in all
NYUMBA_KUMI_MAX = 10           # households in one cell, the lead farmer included

# Third-party MCP server (official reference filesystem server), pinned to a release > 2 weeks old.
FS_MCP_PACKAGE = "@modelcontextprotocol/server-filesystem@2026.8.31"
FS_MCP_ALLOWED_TOOLS = {"read_text_file", "read_file", "list_directory"}  # write tools are never exposed


def today() -> date:
    """Reference date. Pinned via env var so evals are reproducible."""
    pinned = os.environ.get("CROP_PILOT_TODAY")
    return date.fromisoformat(pinned) if pinned else date.today()


# --- Rainfall / spray-safety thresholds -------------------------------------------------
SPRAY_SAFE_MIN = 70          # index >= 70 -> SAFE
SPRAY_CAUTION_MIN = 40       # 40..69 -> CAUTION, < 40 -> UNSAFE
STORM_PENALTY = {"LOW": 0, "MODERATE": 15, "HIGH": 40}
PLANTING_RAIN_7D_MM = 25.0   # onset rule of thumb: >= 25 mm expected over 7 days (maize, beans, potato, kale)
# Drought-tolerant crops can be sown on less rain (rule of thumb used by this desk; see crop_calendar_nairobi.md).
PLANTING_RAIN_BY_CROP = {"Sorghum": 15.0, "Cowpeas": 15.0, "Sweet Potato": 18.0, "Groundnut": 20.0}
WASHOUT_RAIN_72H_MM = 50.0   # flash-washout risk
WEATHER_STALE_DAYS = 3

# The office this deployment serves. The self-check refuses drafts for plots outside these wards.
DAGORETTI_SOUTH_WARDS = {"RIRUTA", "WAITHAKA", "MUTUINI", "NGANDO", "UTHIRU"}

# --- Pest threat ------------------------------------------------------------------------
# Spraying in wind drifts the product onto neighbours' crops, water and bees (pesticides_safety.md: "not in wind").
SPRAY_MAX_WIND_KMH = 15.0
# Plot terrain, recorded by the officer on a field visit. Slope never delays planting (farmers on hillsides plant at
# the rains); it changes how to plant.
SLOPES = ["flat", "gentle", "terraced", "steep"]
SLOPE_ADVICE = {
    "gentle": "Plant along the contour (rows across the slope) so the rows hold water and soil.",
    "terraced": "Keep the terrace edges and grass strips in good repair, and plant along the contour.",
    "steep": "Steep plot: plant along the contour, and dig tied ridges or fanya juu terraces when you can, so the rain "
             "soaks in instead of washing seed and topsoil downhill.",
}
SOILS = ["red loam", "black cotton", "sandy loam", "clay loam"]   # same names as the "What can I grow?" tool
WATERLOG_SOILS = {"black cotton", "clay loam"}
WATERLOG_RAIN_7D_MM = 60.0   # flat clay plots stay waterlogged after a week this wet: seed rots
# Rain above about 25 mm in an hour is erosive on tropical soils (Hudson's threshold) and crusts newly sown soil.
CRUST_RAIN_MM_H = 25.0
# A false start: rain now, then a long dry spell. 10 or more dry days in the 2-week outlook after this week.
FALSE_START_DRY_SPELL_DAYS = 10
# Seed label check: the farmer scratches the KEPHIS label and SMSes the code (1393 on most labels); the reply names
# the variety, producer and lot. We cannot query KEPHIS from here, so the farmer records the result.
SEED_CHECKS = ["VERIFIED", "FAILED", "NOT_CHECKED"]
# The farmer's "soil moist to a hand's depth?" answer counts for this many days.
SOIL_CHECK_FRESH_DAYS = 3
# Mode-of-action groups (IRAC for insecticides, FRAC for fungicides) a farmer can pick when logging a spray.
CHEM_GROUPS = ["Pyrethroids (IRAC 3A)", "Organophosphates (IRAC 1B)", "Avermectins / emamectin (IRAC 6)",
               "Spinosyns (IRAC 5)", "Diamides (IRAC 28)", "Bt, biological (IRAC 11A)", "Neem, botanical",
               "Mancozeb / dithiocarbamates (FRAC M03)", "Metalaxyl / phenylamides (FRAC 4)", "Copper (FRAC M01)",
               "Not sure"]

# Rain-fastness: a spray needs this many dry hours after it (desk guidance: "no rain for 6 h"; labels may say less).
SPRAY_DRY_HOURS = 6
# Mode-of-action groups the desk guide (pesticides_safety.md) lists for each target, for the rotation advice.
PEST_GROUPS = {
    "fall armyworm": ["Avermectins / emamectin (IRAC 6)", "Spinosyns (IRAC 5)", "Diamides (IRAC 28)",
                      "Bt, biological (IRAC 11A)"],
    "late blight": ["Mancozeb / dithiocarbamates (FRAC M03)", "Copper (FRAC M01)",
                    "Metalaxyl / phenylamides (FRAC 4)"],
    "aphids": ["Neem, botanical", "Pyrethroids (IRAC 3A)"],
}
# What to scout for during each pest's risk window (pest_action_thresholds.md). Scouting, not spraying, comes first.
SCOUT_ADVICE = {
    "fall armyworm": "scout 20 plants in a W pattern twice a week, and act only if 10 % or more show fresh "
                     "window-pane damage (20 % after knee height)",
    "late blight": "check the lower leaves twice a week, especially after cold, wet nights; remove infected leaves "
                   "and do not water overhead",
    "aphids": "check the undersides of the leaves twice a week",
    "bean fly": "check the stems near the soil twice a week, and earth up the stems",
}

PEST_RADIUS_KM = {"fall armyworm": 5.0, "late blight": 3.0, "aphids": 2.0, "bean fly": 3.0}
DEFAULT_PEST_RADIUS_KM = 3.0
SEVERITY_WEIGHT = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 1.0}
PEST_RECENCY_HALF_LIFE_DAYS = 14
PEST_MAX_AGE_DAYS = 30
PEST_ACTION_SCORE = 0.25

# --- Crop calendar (days after planting -> stage), Nairobi highlands (~1,700 m) ------------
CROP_STAGES: dict[str, list[tuple[int, str]]] = {
    "Maize": [(10, "EMERGENCE"), (45, "EARLY_VEGETATIVE"), (75, "LATE_VEGETATIVE_TASSELING"),
              (110, "GRAIN_FILL"), (150, "MATURITY"), (10_000, "HARVEST_READY")],
    "Beans": [(10, "EMERGENCE"), (35, "VEGETATIVE"), (55, "FLOWERING"),
              (85, "POD_FILL"), (10_000, "MATURITY")],
    "Kale": [(21, "ESTABLISHMENT"), (10_000, "CONTINUOUS_HARVEST")],
    "Potato": [(20, "EMERGENCE"), (50, "VEGETATIVE"), (75, "TUBER_INITIATION"),
               (110, "TUBER_BULKING"), (10_000, "MATURITY")],
    "Tomato": [(25, "ESTABLISHMENT"), (55, "VEGETATIVE_FLOWERING"),
               (100, "FRUITING"), (10_000, "HARVEST")],
    "Sorghum": [(10, "EMERGENCE"), (40, "EARLY_VEGETATIVE"), (70, "BOOTING_FLOWERING"),
                (105, "GRAIN_FILL"), (10_000, "MATURITY")],
    "Cowpeas": [(10, "EMERGENCE"), (35, "VEGETATIVE"), (55, "FLOWERING"), (10_000, "POD_FILL_MATURITY")],
    "Sweet Potato": [(30, "ESTABLISHMENT"), (90, "VINE_GROWTH"), (10_000, "TUBER_BULKING")],
    "Groundnut": [(12, "EMERGENCE"), (40, "VEGETATIVE"), (70, "PEGGING"), (10_000, "POD_FILL_MATURITY")],
}

# Which stages are susceptible to which pest (drives SPRAY decisions).
PEST_SUSCEPTIBILITY: dict[str, dict[str, set[str]]] = {
    "fall armyworm": {"Maize": {"EMERGENCE", "EARLY_VEGETATIVE", "LATE_VEGETATIVE_TASSELING"},
                      "Sorghum": {"EMERGENCE", "EARLY_VEGETATIVE"}},
    "late blight": {"Potato": {"VEGETATIVE", "TUBER_INITIATION", "TUBER_BULKING"},
                    "Tomato": {"VEGETATIVE_FLOWERING", "FRUITING"}},
    "aphids": {"Kale": {"ESTABLISHMENT", "CONTINUOUS_HARVEST"}, "Beans": {"VEGETATIVE", "FLOWERING"}},
    "bean fly": {"Beans": {"EMERGENCE", "VEGETATIVE"}},
}

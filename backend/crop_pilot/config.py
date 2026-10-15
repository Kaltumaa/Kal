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
LLM_TIMEOUT_S = float(os.environ.get("CROP_PILOT_LLM_TIMEOUT", "120"))
DISABLE_LLM = os.environ.get("CROP_PILOT_DISABLE_LLM") == "1"

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
PLANTING_RAIN_7D_MM = 25.0   # onset rule of thumb: >= 25 mm expected over 7 days
WASHOUT_RAIN_72H_MM = 50.0   # flash-washout risk
WEATHER_STALE_DAYS = 3

# --- Pest threat ------------------------------------------------------------------------
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
}

# Which stages are susceptible to which pest (drives SPRAY decisions).
PEST_SUSCEPTIBILITY: dict[str, dict[str, set[str]]] = {
    "fall armyworm": {"Maize": {"EMERGENCE", "EARLY_VEGETATIVE", "LATE_VEGETATIVE_TASSELING"}},
    "late blight": {"Potato": {"VEGETATIVE", "TUBER_INITIATION", "TUBER_BULKING"},
                    "Tomato": {"VEGETATIVE_FLOWERING", "FRUITING"}},
    "aphids": {"Kale": {"ESTABLISHMENT", "CONTINUOUS_HARVEST"}, "Beans": {"VEGETATIVE", "FLOWERING"}},
    "bean fly": {"Beans": {"EMERGENCE", "VEGETATIVE"}},
}

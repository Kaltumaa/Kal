"""Plant AI MCP server (fastmcp). Three tools:

* diagnose_crop_leaf        runs plant_ai_model.pth (EfficientNet-B0) on a leaf photo, with an image-quality check.
* check_regional_outbreak   logs a case in SQLite and flags a regional spike (this week vs the previous four weeks).
* draft_extension_advisory  prepares treatment advice for an extension officer to review. It never sends anything.

There is deliberately no tool that sends alerts: dispatch lives in agent_api.py behind a human approval.

Run standalone (stdio):   python mcp_server.py
"""
from __future__ import annotations

import base64
import binascii
import io
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastmcp import FastMCP
from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

HERE = Path(__file__).resolve().parent
MODEL_PATH = Path(os.environ.get("PLANT_AI_MODEL", HERE / "plant_ai_model.pth"))
DB_PATH = Path(os.environ.get("PLANT_AI_DB", HERE.parents[1] / "data" / "plant_ai.db"))
CONFIDENCE_MIN = float(os.environ.get("PLANT_AI_CONFIDENCE_MIN", "0.75"))
MAX_IMAGE_BYTES = 8_000_000
# Spike rule: at least SPIKE_MIN_CASES of one disease in a region in the last 7 days AND at least SPIKE_RATIO times
# the weekly average of the 4 weeks before (or no cases at all before).
SPIKE_WINDOW_DAYS, BASELINE_WEEKS, SPIKE_MIN_CASES, SPIKE_RATIO = 7, 4, 3, 2.0
BLUR_MIN_SHARPNESS, DARK_MAX_BRIGHTNESS = 60.0, 40.0   # same thresholds as the extension desk's photo check

mcp = FastMCP("plant-ai")
_classifier = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    region      TEXT NOT NULL,          -- county / sub-county / ward, normalised to lower case
    crop        TEXT,
    disease     TEXT NOT NULL,          -- model label, e.g. tomato__late_blight
    confidence  REAL,
    lat         REAL,
    lon         REAL,
    source      TEXT,                   -- model | officer | farmer_report
    reported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_region ON cases(region, disease, reported_at);

-- Outbreak alerts wait here for a named officer. Only agent_api.py changes their status; the MCP server cannot.
CREATE TABLE IF NOT EXISTS outbreak_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    region       TEXT NOT NULL,
    disease      TEXT NOT NULL,
    message      TEXT NOT NULL,
    evidence     TEXT NOT NULL,         -- JSON: diagnosis, outbreak stats, weather, advisory
    status       TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
                   CHECK (status IN ('PENDING_APPROVAL','APPROVED','REJECTED','DISPATCHED')),
    created_at   TEXT NOT NULL,
    decided_by   TEXT,
    decided_at   TEXT,
    decision_note TEXT,
    dispatched_at TEXT,
    recipients   INTEGER,
    -- nothing is approved, rejected or dispatched without a named person
    CHECK (status = 'PENDING_APPROVAL' OR (decided_by IS NOT NULL AND length(trim(decided_by)) >= 5)),
    CHECK (dispatched_at IS NULL OR status = 'DISPATCHED')
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _norm(text: str | None, limit: int = 80) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s,.\-]", "", str(text or ""))).strip().lower()[:limit]


# --- 1. diagnose -------------------------------------------------------------------------------------------------
def classifier():
    global _classifier
    if _classifier is None:
        from plant_model import LeafClassifier        # torch import is slow: load on first use
        _classifier = LeafClassifier(MODEL_PATH)
    return _classifier


def _decode(image_base64: str | None, image_path: str | None) -> bytes:
    if image_base64:
        data = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image_base64 is not valid base64") from exc
    elif image_path:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError("image_path not found")
        raw = path.read_bytes()
    else:
        raise ValueError("send image_base64 or image_path")
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image is empty or larger than 8 MB")
    return raw


def image_quality(img: Image.Image) -> dict:
    g = img.convert("L")
    g.thumbnail((640, 640))
    w, h = g.size
    if min(w, h) >= 20:
        g = g.crop((w // 10, h // 10, w - w // 10, h - h // 10))
    lap = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)
    sharp, bright = ImageStat.Stat(g.filter(lap)).var[0], ImageStat.Stat(g).mean[0]
    issues = (["blurry"] if sharp < BLUR_MIN_SHARPNESS else []) + (["dark"] if bright < DARK_MAX_BRIGHTNESS else [])
    return {"sharpness": round(sharp, 1), "brightness": round(bright, 1), "issues": issues}


@mcp.tool
def diagnose_crop_leaf(image_base64: str | None = None, image_path: str | None = None, top_k: int = 3) -> dict:
    """Classify a crop leaf photo with the trained EfficientNet-B0 (plant_ai_model.pth; PlantVillage + PlantDoc
    classes such as tomato__late_blight, corn__common_rust, potato__early_blight, *__healthy).
    Send the photo as image_base64 (JPEG/PNG, data: URLs accepted) or a local image_path.
    Returns the top predictions with confidence (0-1), an image-quality check, and `confident`: false when the top
    confidence is below 0.75 or the photo is blurry/dark. When not confident, do not suggest a treatment."""
    try:
        raw = _decode(image_base64, image_path)
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (ValueError, UnidentifiedImageError, OSError) as exc:
        return {"ok": False, "error": str(exc)[:200]}
    quality = image_quality(img)
    try:
        model = classifier()
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "image_quality": quality}
    preds = model.predict(img, top_k=max(1, min(int(top_k), 5)))
    top = preds[0]
    confident = top["confidence"] >= CONFIDENCE_MIN and not quality["issues"]
    reasons = []
    if top["confidence"] < CONFIDENCE_MIN:
        reasons.append(f"model confidence {top['confidence']:.0%} is below {CONFIDENCE_MIN:.0%}")
    if quality["issues"]:
        reasons.append(f"photo is {' and '.join(quality['issues'])}")
    return {"ok": True, "label": top["label"], "crop": top["crop"], "condition": top["condition"],
            "confidence": top["confidence"], "predictions": preds, "image_quality": quality,
            "confident": confident, "healthy": top["condition"] == "healthy",
            "needs_human_review": not confident, "uncertainty_reasons": reasons,
            "model": {"path": MODEL_PATH.name, "trained_at": model.trained_at,
                      "val_acc": model.metrics.get("val_acc"), "val_acc_field": model.metrics.get("val_acc_field")}}


# --- 2. outbreak --------------------------------------------------------------------------------------------------
@mcp.tool
def check_regional_outbreak(region: str, disease: str, crop: str | None = None, confidence: float | None = None,
                            lat: float | None = None, lon: float | None = None, record: bool = True,
                            source: str = "model") -> dict:
    """Log one diagnosed case for a region (county / sub-county / ward) in SQLite, then check for a spike: at least
    3 cases of this disease in the region in the last 7 days AND at least twice the weekly average of the 4 weeks
    before. Healthy leaves are never counted. Set record=false to only check."""
    region_n, disease_n = _norm(region), _norm(disease)
    if not region_n or not disease_n:
        return {"ok": False, "error": "region and disease are required"}
    if source not in ("model", "officer", "farmer_report"):
        return {"ok": False, "error": "source must be model, officer or farmer_report"}
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=SPIKE_WINDOW_DAYS)).isoformat()
    base_from = (now - timedelta(days=SPIKE_WINDOW_DAYS * (BASELINE_WEEKS + 1))).isoformat()
    with db() as conn:
        case_id = None
        if record and not disease_n.endswith("healthy"):
            case_id = conn.execute("INSERT INTO cases (region, crop, disease, confidence, lat, lon, source, "
                                   "reported_at) VALUES (?,?,?,?,?,?,?,?)",
                                   (region_n, _norm(crop) or None, disease_n, confidence, lat, lon, source,
                                    now_iso())).lastrowid
        recent = conn.execute("SELECT COUNT(*) FROM cases WHERE region=? AND disease=? AND reported_at >= ?",
                              (region_n, disease_n, week_ago)).fetchone()[0]
        before = conn.execute("SELECT COUNT(*) FROM cases WHERE region=? AND disease=? AND reported_at >= ? "
                              "AND reported_at < ?", (region_n, disease_n, base_from, week_ago)).fetchone()[0]
        others = [dict(r) for r in conn.execute(
            "SELECT disease, COUNT(*) AS cases FROM cases WHERE region=? AND reported_at >= ? GROUP BY disease "
            "ORDER BY cases DESC LIMIT 5", (region_n, week_ago))]
    baseline = before / BASELINE_WEEKS
    ratio = recent / baseline if baseline else None
    spike = recent >= SPIKE_MIN_CASES and (baseline == 0 or recent >= SPIKE_RATIO * baseline)
    level = "SPIKE" if spike else ("WATCH" if recent >= 2 else "NORMAL")
    return {"ok": True, "region": region_n, "disease": disease_n, "case_id": case_id, "cases_last_7d": recent,
            "baseline_weekly": round(baseline, 2), "ratio_vs_baseline": round(ratio, 2) if ratio else None,
            "spike": spike, "level": level, "region_top_diseases_7d": others,
            "rule": f">= {SPIKE_MIN_CASES} cases in {SPIKE_WINDOW_DAYS} days and >= {SPIKE_RATIO}x the weekly average "
                    f"of the previous {BASELINE_WEEKS} weeks"}


# --- 3. advisory --------------------------------------------------------------------------------------------------
SAFETY = ("Use only PCPB-registered products at the label rate, wear gloves and a mask, keep children and animals "
          "away, and respect the pre-harvest interval on the label.")
# condition -> (what to do now without chemicals, chemical option or None, prevention)
TREATMENTS: dict[str, tuple[str, str | None, str]] = {
    "late_blight": ("Remove and bury or burn infected leaves; avoid overhead watering; widen spacing for airflow.",
                    "Protectant mancozeb (FRAC M03) or copper (FRAC M01); at first signs in wet weather a systemic "
                    "metalaxyl + mancozeb (FRAC 4 + M03). Alternate FRAC groups.",
                    "Plant certified seed / resistant varieties; rotate away from potato and tomato for 2-3 seasons."),
    "early_blight": ("Remove infected lower leaves; mulch to stop soil splash; water at the base in the morning.",
                     "Mancozeb (FRAC M03), chlorothalonil (FRAC M05) or copper (FRAC M01), every 7-10 days in "
                     "wet weather.", "Rotate crops for 2-3 seasons; stake tomatoes; destroy crop residue."),
    "septoria_leaf_spot": ("Remove spotted lower leaves; mulch; avoid working in the field when leaves are wet.",
                           "Chlorothalonil (FRAC M05) or mancozeb (FRAC M03).",
                           "Rotate crops; remove volunteer tomatoes and Solanaceous weeds."),
    "leaf_mold": ("Improve ventilation (open greenhouse sides, prune lower leaves); reduce humidity.",
                  "Copper (FRAC M01) or chlorothalonil (FRAC M05).", "Use resistant varieties; avoid leaf wetness."),
    "bacterial_spot": ("Remove badly affected leaves; do not handle plants when wet; disinfect tools.",
                       "Copper-based bactericide (FRAC M01) slows spread; it does not cure infected leaves.",
                       "Use certified, disease-free seed and transplants; rotate for 2 seasons."),
    "mosaic_virus": ("No cure: uproot and destroy infected plants; wash hands and disinfect tools (milk or soap "
                     "solution) after handling.", None,
                     "Use certified seed and resistant varieties; do not smoke near plants (tobacco carries the "
                     "virus)."),
    "yellow_leaf_curl_virus": ("No cure: uproot and destroy infected plants early; control whiteflies with yellow "
                               "sticky traps and neem.", "If whiteflies are many: a registered insecticide for "
                               "whitefly, rotating IRAC groups.",
                               "Use resistant varieties and insect-proof nets for seedlings; remove weeds that host "
                               "whiteflies."),
    "spider_mites": ("Spray the undersides of leaves with strong water; use neem or insecticidal soap.",
                     "If severe: a registered miticide such as abamectin (IRAC 6); rotate modes of action.",
                     "Avoid water stress and dusty conditions; scout leaf undersides weekly."),
    "common_rust": ("Usually not worth spraying on hybrid maize; scout for spread to upper leaves.",
                    "Only if severe before tasseling: a triazole fungicide (FRAC 3).",
                    "Plant resistant hybrids; plant early in the season."),
    "northern_leaf_blight": ("Remove heavily infected lower leaves; scout weekly.",
                             "If lesions reach the ear leaf before tasseling: a triazole or strobilurin (FRAC 3 / 11).",
                             "Use resistant varieties; rotate with beans; bury or remove crop residue."),
    "gray_leaf_spot": ("Scout weekly; improve field drainage.",
                       "If severe before tasseling: a strobilurin or triazole (FRAC 11 / 3).",
                       "Rotate with legumes; manage residue; resistant hybrids."),
    "powdery_mildew": ("Remove worst-affected leaves; improve airflow; avoid excess nitrogen.",
                       "Sulphur (FRAC M02) or potassium bicarbonate; a systemic (FRAC 3) if it spreads fast.",
                       "Resistant varieties; wider spacing."),
    "scab": ("Rake and destroy fallen leaves; prune for airflow.", "Captan (FRAC M04) or a triazole (FRAC 3) from "
             "bud break in wet weather.", "Resistant apple varieties; orchard sanitation."),
    "cedar_apple_rust": ("Remove galls from nearby juniper/cedar trees where possible.",
                         "A triazole such as myclobutanil (FRAC 3) from pink bud stage.", "Resistant varieties."),
    "black_rot": ("Remove mummified fruit and infected canes; prune for airflow.",
                  "Mancozeb (FRAC M03) or captan (FRAC M04) from early shoot growth.", "Vineyard sanitation."),
}


@mcp.tool
def draft_extension_advisory(disease_label: str, confidence: float, region: str, crop: str | None = None,
                             outbreak_level: str | None = None, rain_next_24h_mm: float | None = None,
                             rain_probability_max: float | None = None, hours_until_rain: float | None = None,
                             image_issues: list[str] | None = None) -> dict:
    """Prepare treatment advice for an extension officer to review (DRAFT only: nothing is sent).
    Pass the diagnosis (disease_label like tomato__late_blight and its confidence 0-1), the region, the outbreak
    level from check_regional_outbreak, and the weather (rain in the next 24 h, max rain probability, hours until
    rain). Below 0.75 confidence or with a bad photo it refuses to suggest a treatment and asks for an officer's
    diagnosis. It also blocks spraying when rain is due within 6 hours."""
    label = _norm(disease_label, 60).replace(" ", "_")
    crop_name = (crop or label.split("__")[0]).replace("_", " ")
    condition = label.split("__")[1] if "__" in label else label
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return {"ok": False, "error": "confidence must be a number between 0 and 1"}
    issues = [i for i in (image_issues or []) if i]
    status = "DRAFT_FOR_OFFICER_REVIEW"
    warnings: list[str] = []

    if conf < CONFIDENCE_MIN or issues:
        why = (f"the model is only {conf:.0%} sure" if conf < CONFIDENCE_MIN else "") + \
              (" and " if conf < CONFIDENCE_MIN and issues else "") + \
              (f"the photo is {' and '.join(issues)}" if issues else "")
        return {"ok": True, "status": "NEEDS_OFFICER_DIAGNOSIS", "treatment": None, "disease": label,
                "confidence": conf, "region": _norm(region),
                "message": f"I am not certain about this {crop_name} leaf ({why}), so I will not suggest a "
                           "treatment. An extension officer should look at the plant before anything is sprayed.",
                "officer_note": "Manual diagnosis needed: model below 75 % confidence or unusable photo."}

    if condition == "healthy":
        return {"ok": True, "status": status, "disease": label, "confidence": conf, "region": _norm(region),
                "treatment": None, "message": f"The {crop_name} leaf looks healthy. No spraying needed; keep "
                                               "scouting weekly.", "warnings": []}

    now_steps, chemical, prevent = TREATMENTS.get(condition, (
        "Remove affected leaves and ask your extension officer to confirm the problem.", None,
        "Rotate crops and use certified seed."))
    spray_ok = True
    if hours_until_rain is not None and hours_until_rain < 6:
        spray_ok = False
        warnings.append(f"Rain is expected in about {hours_until_rain:.0f} h: do not spray now, it would wash off. "
                        "Spray when 6 dry hours are forecast.")
    elif (rain_next_24h_mm or 0) >= 10 or (rain_probability_max or 0) >= 80:
        spray_ok = False
        warnings.append("Heavy rain is likely in the next 24 h: wait for a dry spell before spraying.")
    if rain_next_24h_mm is None and rain_probability_max is None and hours_until_rain is None:
        warnings.append("No weather forecast was available: check that 6 dry hours are expected before spraying.")
    if (outbreak_level or "").upper() == "SPIKE":
        warnings.append(f"Regional spike of {condition.replace('_', ' ')} in {region}: neighbours should scout now.")

    chem_text = (chemical if spray_ok else f"After the rain passes: {chemical}") if chemical else None
    message = (f"{crop_name.title()}: likely {condition.replace('_', ' ')} ({conf:.0%} sure). Do now: {now_steps}"
               + (f" Spray option: {chem_text} {SAFETY}" if chem_text else "") + f" Prevent: {prevent}")
    return {"ok": True, "status": status, "disease": label, "confidence": conf, "region": _norm(region),
            "treatment": {"immediate": now_steps, "chemical": chem_text, "prevention": prevent,
                          "spray_now_ok": spray_ok and bool(chemical), "safety": SAFETY if chemical else None},
            "warnings": warnings, "message": message,
            "note": "Draft for an extension officer. Nothing has been sent to any farmer."}


if __name__ == "__main__":
    mcp.run()

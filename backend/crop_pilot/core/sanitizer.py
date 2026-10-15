"""Scrubbing routine for messy household records and any free text that reaches the model.

Pure functions only: no I/O. Every repair is recorded in a `data_quality` list so the officer can
see exactly what the agent changed and why.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date, datetime

from crop_pilot import config

CROP_ALIASES = {
    "maize": "Maize", "corn": "Maize", "mahindi": "Maize",
    "beans": "Beans", "bean": "Beans", "maharagwe": "Beans",
    "kale": "Kale", "sukuma": "Kale", "sukuma wiki": "Kale", "sukumawiki": "Kale",
    "potato": "Potato", "potatoes": "Potato", "viazi": "Potato", "irish potato": "Potato",
    "tomato": "Tomato", "tomatoes": "Tomato", "nyanya": "Tomato",
}

# Patterns that indicate someone is trying to instruct the model through a data field.
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+|the\s+|previous\s+|prior\s+|above\s+|system\s+)*(instructions|prompts?|rules)",
    r"disregard\s+(all\s+|the\s+|previous\s+|system\s+)*(instructions|rules)",
    r"you\s+are\s+now\b",
    r"\bsystem\s*(prompt|message)\b",
    r"^\s*(system|assistant)\s*:",
    r"<\|?\s*(im_start|im_end|system|endoftext)\s*\|?>",
    r"\b(mark|set)\b.{0,40}\b(approved|dispatched)\b",
    r"\bsend\s+(an?\s+)?(sms|ussd|message|text)\b",
    r"\bnew\s+instructions?\b",
    r"\bact\s+as\b",
    r"\bjailbreak\b",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in INJECTION_PATTERNS]
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_NOTE_CHARS = 500


def normalise_text(value: object) -> str:
    """NFKC-normalise, drop zero-width and control characters, collapse whitespace."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(_ZERO_WIDTH)
    text = _CONTROL.sub(" ", text)
    text = text.encode("utf-8", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", text).strip()


def detect_injection(value: object) -> list[str]:
    """Return the patterns that matched (empty list = clean)."""
    text = normalise_text(value)
    return [p.pattern for p in _INJECTION_RE if p.search(text)]


def scrub_free_text(value: object, max_chars: int = MAX_NOTE_CHARS) -> tuple[str, list[str]]:
    """Clean a narrative field. Returns (safe_text, matched_injection_patterns).

    If an injection is detected the text is REDACTED, never forwarded to the model.
    """
    text = normalise_text(value)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "S" or ch in "°%")
    hits = detect_injection(text)
    if hits:
        return f"[REDACTED: {len(hits)} instruction-like pattern(s) found in field notes]", hits
    return text[:max_chars], []


def normalise_crop(value: object) -> str | None:
    raw = re.sub(r"[^a-z ]", " ", normalise_text(value).lower())
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None
    if raw in CROP_ALIASES:
        return CROP_ALIASES[raw]
    for token in raw.split():
        if token in CROP_ALIASES:
            return CROP_ALIASES[token]
    match = difflib.get_close_matches(raw, CROP_ALIASES.keys(), n=1, cutoff=0.75)
    return CROP_ALIASES[match[0]] if match else None


def normalise_history(value: object) -> list[str]:
    parts = re.split(r"[>,;/|]+", normalise_text(value))
    return [c for c in (normalise_crop(p) for p in parts) if c]


def normalise_zone(value: object) -> str | None:
    zone = re.sub(r"[^A-Z]", "", normalise_text(value).upper())
    return zone or None


def parse_coordinate(value: object, lo: float, hi: float) -> float | None:
    text = normalise_text(value)
    if not text:
        return None
    # Common keying error: letter O typed instead of zero.
    text = re.sub(r"(?<=\d)[oO]|[oO](?=\d)", "0", text)
    try:
        number = float(text)
    except ValueError:
        return None
    return number if lo <= number <= hi else None


def _is_plain_float(value: object) -> bool:
    try:
        float(str(value).strip())
        return True
    except ValueError:
        return False


_DATE_FORMATS =("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y")


def parse_date(value: object) -> date | None:
    text = normalise_text(value)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10}


def parse_days(value: object) -> int | None:
    text = normalise_text(value).lower()
    if not text:
        return None
    text = re.sub(r"(?<=\d)o|o(?=\d)", "0", text)
    for word, num in _WORD_NUMBERS.items():
        text = re.sub(rf"\b{word}\b", str(num), text)
    match = re.search(r"(-?\d+)\s*(weeks?|wks?|w\b)?", text)
    if not match:
        return None
    days = int(match.group(1)) * (7 if match.group(2) else 1)
    return days


def growth_stage(crop: str | None, days: int | None) -> str:
    if days is None:
        return "PRE_PLANTING"
    if crop not in config.CROP_STAGES:
        return "UNKNOWN"
    for upper, stage in config.CROP_STAGES[crop]:
        if days <= upper:
            return stage
    return "UNKNOWN"


def scrub_plot(row: dict | None, today: date | None = None) -> dict:
    """Turn a raw `plots` row into a safe, typed record plus a data-quality report."""
    today = today or config.today()
    if row is None:
        return {"found": False, "profile_complete": False, "data_quality": ["household not found"],
                "injection_detected": False}

    quality: list[str] = []
    household_id = normalise_text(row.get("household_id"))

    zone = normalise_zone(row.get("zone_id"))
    if zone != row.get("zone_id"):
        quality.append(f"zone normalised {row.get('zone_id')!r} -> {zone!r}")

    lat = parse_coordinate(row.get("lat"), -5.0, 5.5)     # Kenya bounding box
    lon = parse_coordinate(row.get("lon"), 33.5, 42.0)
    for name, raw, parsed in (("latitude", row.get("lat"), lat), ("longitude", row.get("lon"), lon)):
        if raw in (None, ""):
            continue
        if parsed is None:
            quality.append(f"{name} {raw!r} unreadable; using zone centroid")
        elif not _is_plain_float(raw):
            quality.append(f"{name} repaired {raw!r} -> {parsed}")
    if lat is None or lon is None:
        lat = lon = None

    crop = normalise_crop(row.get("active_crop"))
    if row.get("active_crop") and crop and crop != row.get("active_crop"):
        quality.append(f"crop normalised {row.get('active_crop')!r} -> {crop!r}")
    elif row.get("active_crop") and not crop:
        quality.append(f"crop {row.get('active_crop')!r} not recognised")

    history = normalise_history(row.get("crop_history"))

    # Planting date is the more reliable signal; free-text days is the fallback.
    days: int | None = None
    planted = parse_date(row.get("planting_date"))
    if planted:
        days = (today - planted).days
        if row.get("planting_date") and str(planted) != row.get("planting_date"):
            quality.append(f"planting date parsed {row.get('planting_date')!r} -> {planted.isoformat()}")
    else:
        if row.get("planting_date"):
            quality.append(f"planting date {row.get('planting_date')!r} unreadable")
        raw_days = normalise_text(row.get("days_since_planting")).lower()
        if raw_days and "not planted" not in raw_days:
            days = parse_days(raw_days)
            if days is None:
                quality.append(f"days since planting {row.get('days_since_planting')!r} unreadable")
    if days is not None and not (0 <= days <= 365):
        quality.append(f"days since planting {days} out of range; discarded")
        days = None

    stage = growth_stage(crop, days)
    recorded_stage = normalise_text(row.get("growth_stage")).upper() or None
    if recorded_stage and recorded_stage != stage:
        quality.append(f"recorded stage {recorded_stage!r} replaced by calendar-derived {stage!r}")

    notes, hits = scrub_free_text(row.get("field_notes"))
    if hits:
        quality.append("prompt-injection pattern found in field notes; notes redacted")

    profile_complete = bool(crop) and bool(zone)
    if not profile_complete:
        quality.append("profile incomplete: needs active crop and zone before any advice")

    return {
        "found": True,
        "household_id": household_id,
        "zone_id": zone,
        "lat": lat,
        "lon": lon,
        "active_crop": crop,
        "crop_history": history,
        "planting_date": planted.isoformat() if planted else None,
        "days_since_planting": days,
        "growth_stage": stage,
        "field_notes": notes,
        "injection_detected": bool(hits),
        "injection_patterns": hits,
        "profile_complete": profile_complete,
        "data_quality": quality,
    }

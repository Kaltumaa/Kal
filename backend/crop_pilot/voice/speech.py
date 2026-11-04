"""Voice notes: the farmer speaks, a local speech-to-text model (Whisper, via faster-whisper) writes it down.

Runs on this computer; no audio leaves it. English and Kiswahili are supported by Whisper; Sheng and other local
languages are not, so they are not offered. The text is only a draft: the farmer reads and edits it before saving,
and it is scrubbed like any typed note. If faster-whisper is not installed (e.g. the free online demo), this says so
and the farmer types instead.
"""
from __future__ import annotations

import io
import os
import re
import time
from functools import lru_cache

from crop_pilot.core import sanitizer, telemetry
from crop_pilot.dispatch.sms import WORD_TO_ACTION

MODEL_SIZE = os.environ.get("CROP_PILOT_WHISPER_MODEL", "small")   # "base" is faster, "small" is better for Kiswahili
LANGUAGES = {"en": "English", "sw": "Kiswahili"}
MAX_AUDIO_BYTES = 10_000_000
# Spoken words that say which job was done (English and Kiswahili), to pre-select the action for the farmer.
SPOKEN = {"weeded": "WEEDING", "weeding": "WEEDING", "palilia": "WEEDING", "nimepalilia": "WEEDING",
          "sprayed": "SPRAYING", "spray": "SPRAYING", "nyunyiza": "SPRAYING", "nimenyunyiza": "SPRAYING",
          "planted": "PLANTING", "panda": "PLANTING", "nimepanda": "PLANTING", "fertiliser": "FERTILISER",
          "fertilizer": "FERTILISER", "mbolea": "FERTILISER", "watered": "IRRIGATION", "irrigated": "IRRIGATION",
          "mwagilia": "IRRIGATION", "harvested": "HARVEST", "vuna": "HARVEST", "nimevuna": "HARVEST",
          "seed": "VARIETY", "mbegu": "VARIETY"} | {w.lower(): a for w, a in WORD_TO_ACTION.items()}


# Farm words the model should expect, per language. Whisper uses this as context, which cuts mishearings of
# crop, pest and input names a general model rarely hears ("maze" for maize, "army worm" for armyworm).
VOCAB = {
    "en": "Farm diary, Kenya. Maize, beans, kale, sukuma wiki, potatoes, tomatoes, sorghum, cowpeas, cabbage. "
          "Weeded, sprayed, planted, top-dressed with CAN, DAP, manure. Fall armyworm, aphids, blight, bean fly.",
    "sw": "Shajara ya shamba. Mahindi, maharagwe, sukuma wiki, viazi, nyanya, mtama, kunde, kabichi. Nimepalilia, "
          "nimenyunyiza dawa, nimepanda, nimeweka mbolea, samadi. Viwavijeshi, vidukari, ukungu, mvua.",
}
VOCAB[None] = VOCAB["en"] + " " + VOCAB["sw"]
# Mishearings that are never right in a farm diary, fixed after transcription (whole words only).
FIXES = {r"\bmaze\b": "maize", r"\bmaise\b": "maize", r"\bmaizes\b": "maize", r"\bfull armor ?worm\b": "fall armyworm",
         r"\bfall army worm\b": "fall armyworm", r"\barmy worm\b": "armyworm", r"\bcana\b": "CAN",
         r"\bsukumawiki\b": "sukuma wiki", r"\btop ?dress\b": "top-dressed", r"\bkail\b": "kale"}


def tidy(text: str) -> str:
    for pattern, word in FIXES.items():
        text = re.sub(pattern, word, text, flags=re.IGNORECASE)
    return text[:1].upper() + text[1:] if text else text


class SpeechUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def _model():
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SpeechUnavailable("Voice notes need the speech model (pip install faster-whisper); type instead.") from exc
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def suggest_action(text: str) -> str | None:
    for word in sanitizer.normalise_text(text).lower().replace(",", " ").replace(".", " ").split():
        if word in SPOKEN:
            return SPOKEN[word]
    return None


def transcribe(audio: bytes, language: str | None = None) -> dict:
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("The recording is empty or too long.")
    if language not in (None, *LANGUAGES):
        raise ValueError(f"Language must be one of {list(LANGUAGES)} or automatic.")
    started = time.perf_counter()
    segments, info = _model().transcribe(io.BytesIO(audio), language=language, beam_size=5, vad_filter=True,
                                         initial_prompt=VOCAB[language], condition_on_previous_text=False,
                                         temperature=0.0)
    raw = tidy(" ".join(s.text.strip() for s in segments).strip())
    text, hits = sanitizer.scrub_free_text(raw, 300)
    latency = (time.perf_counter() - started) * 1000
    telemetry.record(f"voice-{int(time.time() * 1000)}", "whisper", f"speech_to_text:{MODEL_SIZE}",
                     {"bytes": len(audio), "language": language}, {"chars": len(text), "flagged": bool(hits)},
                     latency_ms=latency, actor="farmer")
    return {"text": "" if hits else text, "language": info.language, "flagged": bool(hits),
            "suggested_action": suggest_action(text), "model": f"whisper-{MODEL_SIZE}"}

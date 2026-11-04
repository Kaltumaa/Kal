"""Optional cloud second opinion on a photo: DeepLeaf's Agronomist. Off unless DEEPLEAF_API_KEY is set.

We call DeepLeaf's server API directly (no SDK needed; their JS SDK is for browsers): OpenAI-compatible
    POST https://api.deepleaf.org/v1/agronomist/chat/completions   (servers + paths in their /v1/openapi.json)
    Authorization: Bearer feed_the_world_<64 hex>   (Auth-issued organisation key with the `agronomist` scope)
    x-deepleaf-farmer-id: <id>                      (which farmer the organisation is speaking for)
    {"model": "agronomist", "messages": [{"role": "user", "content": [text part, image_url data-URL part]}]}
The organisation key stays on this server (DeepLeaf: keys never go to a browser). DeepLeaf keeps a memory per farmer
id. The reply is text, so we ask for a note to the officer in English and, after a "KISWAHILI:" line, a short draft
the officer can edit into a voice call.

The reply is untrusted model output about an untrusted photo. It is scrubbed, shown to the officer only, and never
reaches a farmer unless the officer edits or accepts it and signs. It never changes a Plant/Spray/Hold verdict.
Privacy: the photo is re-encoded first (this drops EXIF, including GPS), and the farmer id sent is a salted hash of
the household id: never a name or a phone number.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import time

import httpx
from PIL import Image, UnidentifiedImageError

from crop_pilot import config
from crop_pilot.core import sanitizer, telemetry

PROVIDER = "deepleaf-agronomist"
PROMPT = (
    "You are helping a Kenyan agricultural extension officer in Dagoretti South, Nairobi, review a photo a "
    "smallholder farmer sent{crop}. In English, for the officer: name the most likely pest, disease, deficiency or "
    "'no problem', the signs you can see, how sure you are (low, medium or high), and what the officer should check "
    "on a field visit. Do not name a pesticide product or a dose; the officer decides that. "
    "Then, on a new line starting with 'KISWAHILI:', write two or three short, polite sentences in simple Kiswahili "
    "for an elderly farmer who will hear them on a phone call: what the problem may be, and that their extension "
    "officer will confirm it."
)
SW_MARK = re.compile(r"\**\bkiswahili\b\s*\**\s*:\s*\**\s*", re.IGNORECASE)

_test_client = None          # tests inject a fake client here; nothing else touches it


class HttpClient:
    """DeepLeaf's OpenAI-compatible chat endpoint, same shape as the SDK's chat(farmer_id, message, image_url)."""

    def __init__(self, api_key: str, base_url: str, post=None):
        self.api_key, self.base_url, self.post = api_key, base_url.rstrip("/"), post or httpx.post

    def chat(self, farmer_id: str, message: str, image_url: str | None = None) -> str:
        content = [{"type": "text", "text": message}]
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        r = self.post(f"{self.base_url}/chat/completions", timeout=config.DEEPLEAF_TIMEOUT_S,
                      headers={"Authorization": f"Bearer {self.api_key}", "x-deepleaf-farmer-id": farmer_id,
                               "Content-Type": "application/json"},
                      json={"model": "agronomist", "messages": [{"role": "user", "content": content}]})
        if r.status_code >= 400:          # never echo the response body: it could quote the request headers
            hint = {401: " (key refused: it must be an Auth-issued organisation key, feed_the_world_..., with the "
                          "agronomist scope)", 403: " (key lacks permission for this organisation)",
                    422: " (request format not accepted)"}.get(r.status_code, "")
            raise RuntimeError(f"DeepLeaf answered HTTP {r.status_code}{hint}")
        msg = (r.json().get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content")
        if isinstance(text, list):        # content parts
            text = " ".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("DeepLeaf returned no text")
        return text


def _client():
    if _test_client is not None:
        return _test_client
    return HttpClient(config.DEEPLEAF_API_KEY, config.DEEPLEAF_BASE_URL)


def status() -> dict:
    if _test_client is not None:
        return {"enabled": True, "reason": "test client"}
    if not config.DEEPLEAF_API_KEY:
        return {"enabled": False, "reason": "DEEPLEAF_API_KEY is not set"}
    return {"enabled": True, "reason": f"key set · {config.DEEPLEAF_BASE_URL}"}


def pseudonym(household_id: str | None) -> str:
    digest = hashlib.sha256(f"{config.DEEPLEAF_ID_SALT}:{household_id or 'unknown'}".encode()).hexdigest()
    return f"mkh:{digest[:20]}"


def _clean_image(raw: bytes) -> str:
    """Re-encode as a plain JPEG (no EXIF/GPS), at most 1600 px, as a data URL."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def split_reply(text: str) -> tuple[str, str]:
    parts = SW_MARK.split(text or "", maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def second_opinion(raw: bytes, household_id: str | None, crop: str | None) -> dict | None:
    """DeepLeaf's reading of the photo for the officer, or None when DeepLeaf is not configured."""
    if not status()["enabled"]:
        return None
    started = time.perf_counter()
    out = {"provider": PROVIDER, "status": "ok", "officer_draft": "", "voice_draft_sw": "", "error": None,
           "injection_flag": False}
    try:
        reply = _client().chat(pseudonym(household_id), PROMPT.format(crop=f" of their {crop.lower()}" if crop else ""),
                               image_url=_clean_image(raw))
        text = reply if isinstance(reply, str) else str(getattr(reply, "text", None) or getattr(reply, "content", reply))
        officer, sw = split_reply(text)
        officer, hits1 = sanitizer.scrub_free_text(officer, 1500)
        sw, hits2 = sanitizer.scrub_free_text(sw, 500)
        if hits1 or hits2:
            out |= {"status": "rejected", "injection_flag": True,
                    "error": "DeepLeaf's reply contained instruction-like text and was not kept."}
        else:
            out |= {"officer_draft": officer, "voice_draft_sw": sw}
    except (UnidentifiedImageError, OSError) as exc:
        out |= {"status": "error", "error": f"Photo could not be prepared: {str(exc)[:120]}"}
    except Exception as exc:          # network, auth, quota, SDK changes: the local scan still stands
        out |= {"status": "error", "error": f"DeepLeaf unavailable: {type(exc).__name__}: {str(exc)[:160]}"}
    latency = (time.perf_counter() - started) * 1000
    telemetry.record(f"deepleaf-{int(time.time() * 1000)}", "deepleaf", "agronomist.chat",
                     {"farmer": pseudonym(household_id), "crop": crop, "bytes": len(raw)},
                     {k: out[k] for k in ("status", "error", "injection_flag")}, latency_ms=latency,
                     status="ok" if out["status"] == "ok" else "error")
    return out | {"latency_ms": round(latency)}

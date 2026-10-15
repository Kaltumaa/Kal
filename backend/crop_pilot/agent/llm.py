"""Minimal client for a LOCAL Ollama server. No tokens leave the machine."""
from __future__ import annotations

import time

import httpx

from crop_pilot import config


class LLMUnavailable(RuntimeError):
    pass


async def is_available() -> bool:
    if config.DISABLE_LLM:
        return False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{config.OLLAMA_HOST}/api/tags")
            names = {m.get("name") for m in r.json().get("models", [])}
            return r.status_code == 200 and config.OLLAMA_MODEL in names
    except (httpx.HTTPError, ValueError):
        return False


async def chat(messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False,
               temperature: float = 0.3) -> dict:
    """Return {"message": {...}, "tokens": int, "latency_ms": float}."""
    if config.DISABLE_LLM:
        raise LLMUnavailable("LLM disabled by CROP_PILOT_DISABLE_LLM")
    payload: dict = {"model": config.OLLAMA_MODEL, "messages": messages, "stream": False,
                     "options": {"temperature": temperature, "num_ctx": 8192}}
    if tools:
        payload["tools"] = tools
    if json_mode:
        payload["format"] = "json"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT_S) as client:
            r = await client.post(f"{config.OLLAMA_HOST}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
    return {
        "message": data.get("message", {}),
        "tokens": int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0)),
        "latency_ms": (time.perf_counter() - started) * 1000,
    }

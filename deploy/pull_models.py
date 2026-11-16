"""Pull the agent and photo models into the Ollama container if they are missing, retrying on a bad connection.

Runs in the background at container start. The app works without the models (fixed rules, no photo suggestion),
so a failure here is logged and never stops TALO.
"""
from __future__ import annotations

import json
import os
import time

import httpx

HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
MODELS = [os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"), os.environ.get("CROP_PILOT_VISION_MODEL", "moondream")]


def installed() -> set[str]:
    names = {m["name"] for m in httpx.get(f"{HOST}/api/tags", timeout=10).json().get("models", [])}
    return names | {n.removesuffix(":latest") for n in names}


def pull(model: str) -> None:
    with httpx.stream("POST", f"{HOST}/api/pull", json={"model": model}, timeout=None) as r:
        r.raise_for_status()
        last = ""
        for line in r.iter_lines():
            status = json.loads(line).get("status", "") if line else ""
            if "error" in line:
                raise RuntimeError(line[:200])
            if status != last and "pulling" not in status:
                print(f"[models] {model}: {status}", flush=True)
                last = status


def main() -> None:
    for _ in range(60):                                   # wait up to 5 min for Ollama to start
        try:
            installed()
            break
        except httpx.HTTPError:
            time.sleep(5)
    for model in MODELS:
        for attempt in range(1, 11):
            try:
                if model in installed():
                    print(f"[models] {model} ready", flush=True)
                    break
                print(f"[models] pulling {model} (attempt {attempt})", flush=True)
                pull(model)
            except Exception as exc:  # noqa: BLE001 - keep trying; the app runs on rules meanwhile
                print(f"[models] {model}: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(min(60, 5 * attempt))
        else:
            print(f"[models] gave up on {model}; TALO keeps running on the fixed rules", flush=True)


if __name__ == "__main__":
    main()

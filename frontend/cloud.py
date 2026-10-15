"""Free-hosting demo only (Streamlit Community Cloud).

The free host runs one Streamlit process and has no room for the local AI models. So when the app is running there,
this starts the same FastAPI backend as a separate process, builds the synthetic database, and turns
the LLM off. The agent then drafts with its fixed rules (its normal fallback). The frontend still talks to the backend
only over HTTP. Locally (`make run`) none of this runs: the backend is its own process.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]


def hosted() -> bool:
    # Community Cloud checks the repo out under /mount/src/.
    return os.environ.get("MKULIMA_EMBED_BACKEND") == "1" or ROOT.as_posix().startswith("/mount/src/")


@st.cache_resource(show_spinner="Starting the demo backend…")
def _start_backend() -> bool:
    env = dict(os.environ, CROP_PILOT_DISABLE_LLM="1", PYTHONPATH=str(ROOT / "backend"))
    env.setdefault("CROP_PILOT_TODAY", "2026-10-15")
    if not (ROOT / "data" / "database.db").exists():
        subprocess.run([sys.executable, "-m", "crop_pilot.database.init_db", "--reset"], cwd=ROOT, env=env, check=True)
    # A separate process, exactly like `make run`: the frontend never imports backend code.
    subprocess.Popen([sys.executable, "-m", "uvicorn", "crop_pilot.api.main:app", "--host", "127.0.0.1",
                      "--port", "8000", "--log-level", "warning"], cwd=ROOT, env=env)
    for _ in range(120):
        try:
            if requests.get("http://127.0.0.1:8000/health", timeout=2).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def ensure_backend() -> None:
    if hosted():
        _start_backend()

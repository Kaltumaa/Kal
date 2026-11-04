import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CROP_PILOT_TODAY", "2026-10-15")
os.environ["VOICE_AUTO_SIMULATE"] = "0"     # never let a test start the carrier thread against a running server

import pytest  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    from crop_pilot import config
    from crop_pilot.database.init_db import init_db
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db(path, reset=True)
    return path


@pytest.fixture(autouse=True)
def _offline_voice_draft(monkeypatch):
    """Photo tests must not wait on the local Qwen: the voice draft falls back to its template unless a test stubs it."""
    import httpx
    from crop_pilot.fieldscan import voice_draft

    def offline(prompt):
        raise httpx.ConnectError("tests run offline")
    monkeypatch.setattr(voice_draft, "_ask", offline)

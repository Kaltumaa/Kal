import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CROP_PILOT_TODAY", "2026-10-15")
os.environ["VOICE_AUTO_SIMULATE"] = "0"     # never let a test start the carrier thread against a running server
os.environ["CROP_PILOT_NO_DOTENV"] = "1"     # never load the developer's real keys from .env
os.environ["CROP_PILOT_LIVE_WEATHER"] = "0"  # no network: weather tests inject fake providers
for _key in ("VISUAL_CROSSING_API_KEY", "MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE",
             "MPESA_PASSKEY", "STRIPE_SECRET_KEY", "FLW_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "FLW_WEBHOOK_HASH",
             "MPESA_CALLBACK_TOKEN", "JWT_SECRET", "AT_USERNAME", "AT_API_KEY", "WHATSAPP_TOKEN",
             "DEEPLEAF_API_KEY"):
    os.environ.pop(_key, None)               # payments run on their simulators in tests

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


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: run against the real sign-in rules (no signed-in officer stub)")


@pytest.fixture(autouse=True)
def _signed_in_officer(request):
    """Most API tests act as a signed-in extension officer (Wanjiru Kamau). Tests marked real_auth use real tokens."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    from fastapi import Request

    from crop_pilot.api import access, main

    def stub(req: Request) -> None:
        req.state.user = {"id": 0, "role": "extension_officer", "full_name": "Wanjiru Kamau", "household_id": None,
                          "active": 1}
    main.app.dependency_overrides[access.guard] = stub
    yield
    main.app.dependency_overrides.pop(access.guard, None)

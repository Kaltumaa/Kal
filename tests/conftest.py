import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("CROP_PILOT_TODAY", "2026-10-15")

import pytest  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    from crop_pilot import config
    from crop_pilot.database.init_db import init_db
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    init_db(path, reset=True)
    return path

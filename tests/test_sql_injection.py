"""SQL injection: every query is parameterised; attack the API and prove the database is untouched."""
import sqlite3

from fastapi.testclient import TestClient

PAYLOADS = ["HH-DS-001' OR '1'='1", "x'; DROP TABLE plots;--", "1; DELETE FROM pest_alerts", "\" OR \"\"=\"",
            "HH-DS-003'--", "%' UNION SELECT * FROM tool_calls --"]


def _counts(db):
    conn = sqlite3.connect(db)
    out = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]          # fixed table names, test only
           for t in ("plots", "pest_alerts", "pending_advisories", "dispatch_outbox", "tool_calls")}
    out["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    return out


def test_injection_payloads_change_nothing(temp_db, tmp_path, monkeypatch):
    from crop_pilot import config
    from crop_pilot.api.main import app
    monkeypatch.setattr(config, "CHECKPOINT_DB_PATH", tmp_path / "ck.db")
    before = _counts(temp_db)
    with TestClient(app) as c:
        for p in PAYLOADS:
            assert c.get(f"/households/{p}/profile").status_code == 404           # treated as a value, not SQL
            c.get("/telemetry", params={"run_id": p})
            c.get("/forum", params={"topic": p})
            c.get(f"/farms/{p}/actions")
            c.post(f"/farms/{p}/actions", json={"action": "WEEDING", "action_date": "2026-10-14", "role": "farmer"})
            c.post("/forum", json={"author": "Test User", "topic": "General", "body": p})
            assert c.get("/advisories", params={"status": p}).status_code == 422  # rejected by validation
            c.post(f"/advisories/1/approve", json={"officer_name": p, "citation": p})
    after = _counts(temp_db)
    assert after["integrity"] == "ok"
    assert {k: v for k, v in after.items() if k != "tool_calls"} == {k: v for k, v in before.items() if k != "tool_calls"}

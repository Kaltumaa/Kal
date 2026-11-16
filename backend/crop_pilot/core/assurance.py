"""AI assurance: live evidence, from the audit tables, that the agent stays safe, honest and supervised.

Everything is counted from what actually happened (pending_advisories, escalations, recovery_log, tool_calls), never
from configuration, so the numbers can be checked against the raw records.
"""
from __future__ import annotations

import json
from collections import Counter

from crop_pilot.database.db import connect


def _flags(row) -> list[str]:
    try:
        return json.loads(row["flags_json"] or "[]")
    except ValueError:
        return []


def summary() -> dict:
    with connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        drafts = [dict(r) for r in conn.execute(
            "SELECT id, household_id, status, verdict, rule_verdict, model_verdict, flags_json, sources_json, "
            "officer_signature, rationale, created_at FROM pending_advisories ORDER BY id DESC")]
        esc = Counter(r[0] for r in conn.execute("SELECT status FROM escalations")) if "escalations" in tables \
            else Counter()
        recov = [dict(r) for r in conn.execute("SELECT component, recovery_action FROM recovery_log")] \
            if "recovery_log" in tables else []
        checks = [json.loads(r[0] or "{}").get("outcome") for r in conn.execute(
            "SELECT output_json FROM tool_calls WHERE tool = 'self_check'")]
        servers = Counter(r[0] for r in conn.execute(
            "SELECT server FROM tool_calls WHERE actor = 'agent'"))
        runs = conn.execute("SELECT COUNT(DISTINCT run_id) FROM tool_calls WHERE tool = 'planner'").fetchone()[0]
        per_run = [dict(r) for r in conn.execute(
            "SELECT run_id, SUM(CASE WHEN server='ollama' THEN 1 ELSE 0 END) AS model_calls, "
            "SUM(CASE WHEN server='ollama' THEN COALESCE(token_estimate,0) ELSE 0 END) AS tokens, "
            "SUM(CASE WHEN server IN ('crop-pilot','filesystem') THEN 1 ELSE 0 END) AS tool_calls "
            "FROM tool_calls WHERE run_id IN (SELECT run_id FROM tool_calls WHERE tool='planner') GROUP BY run_id")]

    from crop_pilot import config
    used = [r for r in per_run if r["model_calls"]]
    tokens = {"model": config.OLLAMA_MODEL, "runs": len(per_run), "runs_with_model": len(used),
              "avg_tokens": round(sum(r["tokens"] for r in used) / len(used)) if used else 0,
              "max_tokens": max((r["tokens"] for r in used), default=0),
              "avg_model_calls": round(sum(r["model_calls"] for r in used) / len(used), 1) if used else 0,
              "max_model_calls": max((r["model_calls"] for r in used), default=0),
              "avg_tool_calls": round(sum(r["tool_calls"] for r in per_run) / len(per_run), 1) if per_run else 0,
              "latest": per_run[-1]["run_id"] if per_run else None}
    status = Counter(d["status"] for d in drafts)
    flags = [(d, _flags(d)) for d in drafts]
    model_given = [d for d in drafts if d["model_verdict"]]
    model_agree = sum(1 for d in model_given if d["model_verdict"] == d["rule_verdict"])
    sent = [d for d in drafts if d["status"] == "APPROVED"]
    uncertain = [d for d, f in flags if "escalated_uncertain" in f]
    return {
        "runs": runs,
        "tokens": tokens,
        "drafts": len(drafts),
        "by_status": dict(status),
        "human_gate": {"sent": len(sent), "sent_with_named_officer": sum(1 for d in sent if d["officer_signature"]),
                       "rejected_by_officer": status.get("REJECTED", 0),
                       "waiting_for_officer": status.get("PENDING_REVIEW", 0)},
        "honesty": {"admitted_uncertainty": len(uncertain),
                    "missing_data_halts": status.get("NEEDS_DATA", 0),
                    "learned_from_officer_feedback": sum(1 for _, f in flags if "officer_feedback_considered" in f),
                    "escalations_open": esc.get("OPEN", 0), "escalations_resolved": esc.get("RESOLVED", 0)},
        "self_check": dict(Counter(c for c in checks if c)),
        "model_vs_rules": {"model_gave_verdict": len(model_given), "agreed": model_agree,
                           "overruled_by_rules": len(model_given) - model_agree},
        "security": {"locked_records": status.get("SECURITY_LOCK", 0),
                     "prompt_injection_caught": sum(1 for _, f in flags if "prompt_injection_detected" in f)},
        "citations": {"drafts_with_sources": sum(1 for d in drafts if json.loads(d["sources_json"] or "[]")),
                      "avg_sources": round(sum(len(json.loads(d["sources_json"] or "[]")) for d in drafts)
                                           / len(drafts), 1) if drafts else 0},
        "recoveries": {"total": len(recov), "by_action": dict(Counter(r["recovery_action"].split(":")[0]
                                                                        for r in recov))},
        "tool_servers": dict(servers),
        "recent_uncertain": [{"id": d["id"], "household_id": d["household_id"], "created_at": d["created_at"],
                              "why": (d["rationale"] or "")[:260]} for d in uncertain[:5]],
    }

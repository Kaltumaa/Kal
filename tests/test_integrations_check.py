"""The integration checker reports LIVE / SIMULATED / FAILED honestly and never stops at one failure."""
from crop_pilot import integrations_check as ic


def test_unkeyed_services_report_simulated_and_failures_do_not_stop_the_rest(monkeypatch):
    def boom():
        raise RuntimeError("refused")
    results = [ic._probe("A", "x", False, "A_KEY", lambda: "never"),
               ic._probe("B", "y", True, "", boom),
               ic._probe("C", "z", True, "", lambda: "answered")]
    assert [r["state"] for r in results] == ["SIMULATED", "FAILED", "LIVE"]
    assert "A_KEY" in results[0]["detail"] and "refused" in results[1]["detail"]
    text = ic.report(results)
    assert "**1 of 3 systems answered for real**" in text and "no money moved" in text


def test_keyed_checks_skip_the_network_without_keys():
    for check in (ic.visual_crossing, ic.africas_talking, ic.whatsapp, ic.mpesa, ic.card, ic.deepleaf):
        assert check()["state"] == "SIMULATED"

import copy
import json

from delivery.chaos_evals import MANIFEST, check_outcome, validate_chaos_report
from delivery.scenario_report import digest


def outcome():
    return {
        "metrics": [
            {
                "affected_orders": 1,
                "orders_saved": 1,
                "orders_lost": 0,
                "late_deliveries": 0,
                "unresolved_orders": 0,
                "time_to_recover_seconds": 900,
                "extra_token_cost_usd": 0,
                "failed_replans": 0,
            }
        ],
        "contacts": [{"order_id": "one", "refund_eur": 0}],
        "replans": [{"state": "done"} for _ in range(3)],
    }


def test_chaos_gate_checks_metrics_and_replay_instead_of_saved_headlines():
    manifest = json.loads(MANIFEST.read_text())
    report = {
        "kind": "chaos-evals",
        "mode": "scripted-offline",
        "seed": manifest["seed"],
        "fixture_hash": digest(manifest),
        "passed": True,
        "seeded_runs": [{"orders": ["order"], "chaos": {"events": ["rain"]}}] * 2,
        "results": [
            {"case": kind, "repetition": rep, "outcome": outcome()}
            for kind in manifest["cases"]
            for rep in (1, 2)
        ],
    }
    assert validate_chaos_report(report, manifest)
    changed = copy.deepcopy(report)
    changed["results"][0]["outcome"]["metrics"][0]["orders_lost"] = 1
    assert not validate_chaos_report(changed, manifest)
    changed = copy.deepcopy(report)
    changed["results"][0]["outcome"]["metrics"][0]["time_to_recover_seconds"] = 901
    assert not validate_chaos_report(changed, manifest)
    bad = outcome()
    bad["contacts"][0]["refund_eur"] = 5
    assert not check_outcome(bad, manifest["criteria"])
    bad = outcome()
    bad["metrics"][0]["time_to_recover_seconds"] = None
    assert not check_outcome(bad, manifest["criteria"])

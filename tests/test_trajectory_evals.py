from pathlib import Path

import pytest

from delivery.golden_evals import evaluate_golden, promote
from delivery.trajectory_evals import normalize_trace, score_trajectory


def call(name="read_order", args=None, **extra):
    return {"name": name, "args": args or {}, "allowed_tools": [name], **extra}


def test_duplicate_tools_arguments_and_order_are_measured():
    trace = {"calls": [call(), call(), call("finish_decision", {"summary": "wrong"})]}
    reference = [{"name": "read_order", "args": {}},
                 {"name": "finish_decision", "args": {"summary": "right"}}]
    result = score_trajectory(trace, reference)
    assert result["tool_precision"] == pytest.approx(2 / 3)
    assert result["tool_recall"] == 1
    assert result["argument_recall"] == .5
    assert result["step_count"] == 3
    assert result["argument_diffs"][0]["diffs"][0]["path"] == "$.summary"
    reversed_result = score_trajectory({"calls": list(reversed(reference))}, reference)
    assert reversed_result["ordered_match"] == .5


def test_trace_uses_only_response_calls_and_deduplicates_request_history():
    fn = {"id": "c1", "name": "read_order", "args": {}}
    history = {"contents": [{"parts": [{"function_call": fn}]},
                            {"parts": [{"function_response": {
                                "id": "c1", "name": "read_order", "response": {"ok": True}}}]}]}
    rows = [{"step": 1, "response_body": {"parts": [{"function_call": fn}]},
             "request_body": {}, "latency_ms": 12},
            {"step": 2, "response_body": {"parts": []}, "request_body": history,
             "latency_ms": None},
            {"step": 3, "response_body": None, "request_body": history}]
    trace = normalize_trace(rows)
    assert len(trace["calls"]) == 1
    assert trace["calls"][0]["result"] == {"ok": True}
    assert trace["incomplete_steps"] == 1
    assert trace["latency_ms"] is None


def test_recovery_requires_an_observed_successful_retry():
    failed = call("finish_decision", {"summary": "x"}, result={"error": "summary_length"})
    trace = {"calls": [failed, call("finish_decision", {"summary": "fixed"})]}
    assert score_trajectory(trace, [])["error_recovery"] == 0
    trace["calls"][-1]["result"] = {"ok": True}
    assert score_trajectory(trace, [])["error_recovery"] == 1


def test_terminal_receipts_capture_recovery_from_an_invented_finish():
    rows = [{"step": i, "request_body": {}, "response_body": {"parts": [
        {"function_call": {"name": name, "args": {"summary": "OK"}}}]}}
        for i, name in enumerate(["finish_finish_decision", "finish_decision"], 1)]
    receipts = [
        {"tool": "restaurant.contract_rejected", "result": {
            "ok": False, "code": "unknown_tool", "rejected_tool": "finish_finish_decision"}},
        {"tool": "restaurant.finish", "result": {"ok": True}},
    ]
    score = score_trajectory(normalize_trace(rows, receipts), [])
    assert score["error_count"] == 1 and score["error_recovery"] == 1


def test_golden_one_is_the_recorded_invented_finish():
    rows = evaluate_golden(Path(__file__).resolve().parents[1] / "data/evals/golden")
    assert rows and all(row["passed"] for row in rows)
    assert rows[0]["id"] == "001-cost-invented-finish"
    assert rows[0]["score"]["tool_recall"] == 0


def test_promotions_are_versioned_and_exclude_raw_request(tmp_path):
    trace = {"calls": [call("finish_decision", {"summary": "OK"}, result={"private": "data"})]}
    kwargs = dict(root=tmp_path, case_id="case-1", description="Reviewed", source="local",
                  expected_categories=[])
    ref = [{"name": "finish_decision", "args": {"summary": "OK"}}]
    first = promote(trace, ref, **kwargs)
    second = promote(trace, ref, **kwargs)
    assert first.parent.name == "v1" and second.parent.name == "v2"
    assert "private" not in first.read_text()
    assert len(evaluate_golden(tmp_path)) == 1

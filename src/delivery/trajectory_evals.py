"""Score operator-visible migration-019 ADK traces, never private model reasoning."""

from collections import Counter
from typing import Any

from delivery.db import connect
from delivery.eval_checks import code_checks
from delivery.scenario_report import digest


def read_trace(url: str, event_id: int) -> dict[str, Any]:
    """Read exactly one event with the operator identity; no agent table grants."""
    if event_id < 1:
        raise ValueError("A positive event_id is required")
    with connect(url) as conn:
        calls = conn.execute(
            "SELECT step,request_body,response_body,latency_ms,state "
            "FROM restaurant_model_calls WHERE event_id=%s ORDER BY step", (event_id,),
        ).fetchall()
        receipts = conn.execute(
            "SELECT tool,result FROM restaurant_tool_receipts WHERE event_id=%s ORDER BY step",
            (event_id,),
        ).fetchall()
    if not calls:
        raise ValueError("No model trace for this event")
    return normalize_trace(calls, receipts)


def normalize_trace(
    rows: list[dict[str, Any]], receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Responses contain new calls; requests contain accumulated tool responses.

    Never count the request's repeated function-call history as new tool use.
    Request positions are stable for this uncompressed per-event runner.
    """
    calls: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    latencies = []
    for row in sorted(rows, key=lambda r: r["step"]):
        request = row.get("request_body") or {}
        declarations = [
            d["name"] for tool in request.get("config", {}).get("tools", [])
            for d in tool.get("function_declarations", tool.get("functionDeclarations", []))
        ]
        for ci, content in enumerate(request.get("contents", [])):
            for pi, part in enumerate(content.get("parts", [])):
                response = part.get("function_response", part.get("functionResponse"))
                if response:
                    key = response.get("id") or f"position:{ci}:{pi}"
                    results[key] = response
        for part in (row.get("response_body") or {}).get("parts", []):
            call = part.get("function_call", part.get("functionCall"))
            if call:
                calls.append({
                    "name": call.get("name"), "args": call.get("args") or {},
                    "id": call.get("id"), "model_step": row["step"],
                    "allowed_tools": declarations,
                })
        latencies.append(row.get("latency_ms"))
    # IDs are preferred. Missing IDs are matched by name in occurrence order.
    unused = list(results.values())
    for call in calls:
        match = next((r for r in unused if call["id"] and r.get("id") == call["id"]), None)
        if match is None and not call["id"]:
            match = next((r for r in unused if r.get("name") == call["name"]), None)
        if match is not None:
            call["result"] = match.get("response", {})
            unused.remove(match)
        call.pop("id")
    # The terminal tool skips summarization, so its response may never appear in
    # a later model request. Migration 019's durable tool receipts close this gap.
    names = {"restaurant.order": "read_order", "restaurant.recipe": "read_recipe",
             "restaurant.pantry": "read_pantry", "restaurant.suppliers": "find_suppliers",
             "memory.read": "recall_order_memory", "restaurant.finish": "finish_decision",
             "restaurant.request_supply": "request_missing_ingredients",
             "restaurant.confirm": "confirm_order", "restaurant.receive": "receive_ingredient",
             "restaurant.cook": "prepare_meal", "restaurant.offer": "offer_substitution",
             "restaurant.decline": "decline_order"}
    consumed: set[int] = set()
    for receipt in receipts or []:
        result = receipt["result"]
        name = (result.get("rejected_tool") if receipt["tool"] == "restaurant.contract_rejected"
                else names.get(receipt["tool"]))
        index = next((i for i, call in enumerate(calls)
                      if i not in consumed and call["name"] == name), None)
        if index is not None:
            calls[index]["result"] = result if isinstance(result, dict) else {"ok": True}
            consumed.add(index)
    return {
        "calls": calls, "model_steps": len(rows),
        "latency_ms": sum(latencies) if all(v is not None for v in latencies) else None,
        "incomplete_steps": sum(r.get("response_body") is None for r in rows),
    }


def _diff(expected: Any, actual: Any, path: str = "$") -> list[dict[str, Any]]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences = []
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                differences.append({"path": f"{path}.{key}", "expected": expected.get(key),
                                    "actual": actual.get(key), "missing": key not in actual})
            else:
                differences.extend(_diff(expected[key], actual[key], f"{path}.{key}"))
        return differences
    return [] if type(expected) is type(actual) and expected == actual else [
        {"path": path, "expected": expected, "actual": actual}
    ]


def _error(call: dict[str, Any]) -> bool:
    result = call.get("result", {})
    return bool(result.get("error") or result.get("error_code") or result.get("ok") is False
                or result.get("status") in {"error", "rejected", "tool_contract"})


def score_trajectory(trace: dict[str, Any], reference: list[dict[str, Any]]) -> dict[str, Any]:
    calls = trace["calls"]
    actual_counts = Counter(c["name"] for c in calls)
    expected_counts = Counter(c["name"] for c in reference)
    matched = sum((actual_counts & expected_counts).values())
    # Match exact arguments first so duplicate calls cannot steal a later exact match.
    unused = list(range(len(calls)))
    differences = []
    exact = 0
    for index, ref in enumerate(reference):
        candidates = [i for i in unused if calls[i]["name"] == ref["name"]]
        selected = next((i for i in candidates if not _diff(ref["args"], calls[i]["args"])),
                        candidates[0] if candidates else None)
        if selected is not None:
            unused.remove(selected)
            diff = _diff(ref["args"], calls[selected]["args"])
            exact += not diff
            if diff:
                differences.append({"reference_step": index, "actual_step": selected,
                                    "tool": ref["name"], "diffs": diff})
        else:
            differences.append({"reference_step": index, "tool": ref["name"], "missing": True})
    # LCS preserves ordering and multiplicity, unlike set overlap.
    previous = [0] * (len(reference) + 1)
    for call in calls:
        current = [0]
        for j, ref in enumerate(reference, 1):
            same = digest({k: call[k] for k in ("name", "args")}) == digest(ref)
            current.append(previous[j - 1] + 1 if same else max(previous[j], current[-1]))
        previous = current
    errors = [i for i, call in enumerate(calls) if _error(call)]
    recovered = sum(any(
        (later["name"] == calls[i]["name"] or
         (calls[i].get("result", {}).get("code") == "unknown_tool"
          and later["name"] == "finish_decision"))
        and "result" in later and not _error(later)
        for later in calls[i + 1:]
    ) for i in errors)
    return {
        "tool_precision": matched / len(calls) if calls else 1.0,
        "tool_recall": matched / len(reference) if reference else 1.0,
        "argument_precision": exact / len(calls) if calls else 1.0,
        "argument_recall": exact / len(reference) if reference else 1.0,
        "ordered_match": previous[-1] / max(len(calls), len(reference))
        if calls or reference else 1.0,
        "argument_diffs": differences, "extra_steps": unused,
        "step_count": len(calls), "reference_step_count": len(reference),
        "model_steps": trace.get("model_steps"),
        "incomplete_steps": trace.get("incomplete_steps", 0),
        "error_count": len(errors), "recovered_errors": recovered,
        "error_recovery": recovered / len(errors) if errors else None,
        "code_failures": code_checks(calls=calls),
    }

"""Local operator evidence, never an agent capability or permission grant."""

import json
from decimal import Decimal
from typing import Any

from delivery.adk_contracts import VertexProfile
from delivery.db import connect


def usage_cost(usage: dict[str, Any] | None, profile: VertexProfile) -> str | None:
    """Usage-derived USD at the frozen tariff. Invoice credits/tax remain unknown."""
    if not usage or not usage.get("known"):
        return None
    fields = (
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "cached_content_token_count",
    )
    if any(type(usage.get(k, 0)) is not int or usage.get(k, 0) < 0 for k in fields):
        return None
    if "prompt_token_count" not in usage:
        return None
    prompt = usage["prompt_token_count"]
    cached = usage.get("cached_content_token_count", 0)
    if cached > prompt or (cached and profile.cached_input_usd_per_million is None):
        return None
    output = usage.get("candidates_token_count", 0) + usage.get("thoughts_token_count", 0)
    total = (
        Decimal(prompt - cached) * Decimal(str(profile.input_usd_per_million))
        + Decimal(cached) * Decimal(str(profile.cached_input_usd_per_million or 0))
        + Decimal(output) * Decimal(str(profile.output_usd_per_million))
    ) / Decimal(1000000)
    return str(total.quantize(Decimal("0.00000001")))


def run_evidence(run: str, profile: VertexProfile) -> dict[str, Any]:
    with connect() as conn:
        turns = conn.execute(
            "SELECT event_id,store,state,result,memory,error_code FROM restaurant_turns "
            "WHERE run_id=%s ORDER BY event_id",
            (run,),
        ).fetchall()
        calls = conn.execute(
            "SELECT m.* FROM restaurant_model_calls m JOIN restaurant_turns t USING(event_id) "
            "WHERE t.run_id=%s ORDER BY event_id,step",
            (run,),
        ).fetchall()
        tools = conn.execute(
            "SELECT p.* FROM restaurant_tool_receipts p JOIN restaurant_turns t USING(event_id) "
            "WHERE t.run_id=%s ORDER BY p.step",
            (run,),
        ).fetchall()
        search = conn.execute(
            "SELECT event_id,query,model,detail,duration_ms,reserved_calls,reserved_input_tokens "
            "FROM supply_search_audits WHERE run_id=%s ORDER BY id",
            (run,),
        ).fetchall()
        jev_calls = conn.execute(
            "SELECT id,event_id,model,status,reserved_input_tokens,actual_input_tokens,"
            "actual_output_tokens,error FROM supply_search_calls WHERE run_id=%s ORDER BY id",
            (run,),
        ).fetchall()
    for call in calls:
        call["usage_cost_usd"] = usage_cost(call["usage"], profile)
    known = sum(Decimal(c["usage_cost_usd"] or "0") for c in calls)
    unknown = [c for c in calls if c["usage_cost_usd"] is None]
    evidence = {
        "turns": turns,
        "calls": calls,
        "tools": tools,
        "searches": search,
        "jev_calls": jev_calls,
        "cost": {
            "basis": "provider token usage × frozen public USD tariff; invoice not reconciled",
            "known_vertex_usd": str(known),
            "unknown_vertex_calls": len(unknown),
            "vertex_reserved_usd": str(sum(c["reserved_usd"] for c in calls)),
            "invoice_usd": None,
            "jev_known_usd": str(
                sum(
                    Decimal(c["actual_input_tokens"] or 0) * Decimal("0.042") / 1000000
                    for c in jev_calls
                )
            ),
            "unknown_jev_calls": sum(c["actual_input_tokens"] is None for c in jev_calls),
        },
    }
    return json.loads(json.dumps(evidence, default=str))

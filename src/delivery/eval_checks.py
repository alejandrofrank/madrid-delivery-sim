"""Deterministic rejection categories. These always run before a semantic judge."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

TOOL_FIELDS = {
    "read_order": set(), "read_pantry": set(), "read_recipe": set(),
    "find_suppliers": set(), "recall_order_memory": set(),
    "search_ingredients": {"query"}, "request_missing_ingredients": {"supplier"},
    "confirm_order": set(), "receive_ingredient": set(), "prepare_meal": set(),
    "offer_substitution": {"substitute"}, "decline_order": {"reason"},
    "finish_decision": {"summary"},
}


def code_checks(
    *, calls: list[dict[str, Any]] | None = None, allowed_tools: list[str] | None = None,
    response: Any = None, response_schema: type[BaseModel] | None = None,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for index, call in enumerate(calls or []):
        name, args = call.get("name"), call.get("args")
        allowed = call.get("allowed_tools", allowed_tools or [])
        if name not in allowed:
            failures.append({"category": "invented_tool", "step": index, "tool": name})
        if (name not in TOOL_FIELDS or not isinstance(args, dict)
                or set(args) != TOOL_FIELDS.get(name)
                or any(type(v) is not str for v in args.values())):
            # Unknown names have their own category, but malformed arguments still count.
            if name in TOOL_FIELDS or not isinstance(args, dict):
                failures.append({"category": "schema", "step": index, "tool": name})
        if isinstance(args, dict) and isinstance(args.get("summary"), str):
            if not 1 <= len(args["summary"]) <= 500:
                failures.append({"category": "length", "step": index, "field": "summary"})
    if response_schema is not None:
        try:
            if isinstance(response, str):
                response_schema.model_validate_json(response, strict=True)
            else:
                response_schema.model_validate(response, strict=True)
        except ValidationError as exc:
            categories = {
                "length" if e["type"] in {"string_too_long", "string_too_short"} else "schema"
                for e in exc.errors()
            }
            failures.extend({"category": c, "field": "response"} for c in sorted(categories))
    return failures


def checked_judge(
    response: Any, schema: type[BaseModel], judge: Callable[[Any], Any],
    *, calls: list[dict[str, Any]] | None = None, allowed_tools: list[str] | None = None,
) -> dict[str, Any]:
    failures = code_checks(
        response=response, response_schema=schema, calls=calls, allowed_tools=allowed_tools
    )
    return {"code_failures": failures, "judgment": None if failures else judge(response)}

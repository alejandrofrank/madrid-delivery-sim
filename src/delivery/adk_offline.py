"""A scripted ADK model double for reproducible, zero-network contract tests.

This is deliberately not an LLM or a quality evaluation of SOUL understanding.
It exercises Google's real Runner/function-calling loop using the two published
fixture instructions. Production policy code never selects a sourcing strategy.
"""

import json
from collections.abc import AsyncGenerator
from typing import Any, Literal

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from delivery.customer_service import OFFLINE_MODEL, Advice


class OfflineRestaurantModel(BaseLlm):
    model: str = "bakiano-offline-fixture-v1"

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        if stream:
            raise ValueError("Offline fixture uses nonstreaming turns")
        results: dict[str, Any] = {}
        for content in llm_request.contents:
            for part in content.parts or []:
                if part.function_response:
                    response = part.function_response
                    if response.name is None:
                        raise ValueError("A tool response must name its capability")
                    body = response.response or {}
                    results[response.name] = body.get("result", body)
        if "finish_decision" in results:
            yield self.response(text="The scoped decision is saved for validation and commit.")
            return
        actions = {
            "request_missing_ingredients",
            "confirm_order",
            "receive_ingredient",
            "prepare_meal",
            "offer_substitution",
            "decline_order",
        }
        if actions & results.keys():
            yield self.response(
                calls=[
                    (
                        "finish_decision",
                        {
                            "summary": "Compared scoped pantry and supplier quotes."
                        },
                    )
                ]
            )
            return
        if "read_order" not in results:
            reads = [
                name
                for name in (
                    "read_order",
                    "read_recipe",
                    "read_pantry",
                    "find_suppliers",
                    "recall_order_memory",
                )
                if name in llm_request.tools_dict
            ]
            if "read_order" not in reads:
                raise ValueError("Offline fixture requires the order capability")
            yield self.response(calls=[(name, {}) for name in reads])
            return
        order = results["read_order"]
        topic = order["event"]
        call: tuple[str, dict[str, Any]]
        if topic in {"household.call", "restaurant.approval"}:
            recipe = results.get("read_recipe", {})
            pantry = {row["ingredient"]: row for row in results.get("read_pantry", [])}
            shortage = topic == "restaurant.approval" or any(
                pantry.get(item["id"], {}).get("on_hand", 0)
                - pantry.get(item["id"], {}).get("reserved", 0)
                < item["quantity"] * order["quantity"]
                for item in recipe.get("ingredients", [])
            )
            suppliers = results.get("find_suppliers", [])
            if shortage and suppliers:
                instructions = llm_request.config.system_instruction
                if isinstance(instructions, types.Content):
                    text = " ".join(part.text or "" for part in instructions.parts or [])
                else:
                    text = str(instructions)
                normalized = " ".join(text.lower().split())
                key = (
                    ("procurement_fee_cents", "estimated_seconds")
                    if ("prioritize the lowest quoted procurement fee" in normalized)
                    else ("estimated_seconds", "procurement_fee_cents")
                )
                selected = min(suppliers, key=lambda row: (row[key[0]], row[key[1]], row["id"]))
                call = ("request_missing_ingredients", {"supplier": selected["id"]})
            elif shortage:
                call = ("decline_order", {"reason": "No open supplier is available."})
            else:
                call = ("confirm_order", {})
        elif topic == "ingredient.arrived":
            call = ("receive_ingredient", {})
        elif topic == "restaurant.cook":
            call = ("prepare_meal", {})
        elif topic == "ingredient.shortage" and order.get("safe_alternative"):
            call = ("offer_substitution", {"substitute": order["safe_alternative"]})
        else:
            call = ("decline_order", {"reason": "No safe available ingredient alternative."})
        yield self.response(calls=[call])

    @staticmethod
    def response(
        *,
        calls: list[tuple[str, dict[str, Any]]] | None = None,
        text: str | None = None,
    ) -> LlmResponse:
        parts = [
            types.Part(function_call=types.FunctionCall(name=name, args=args))
            for name, args in calls or []
        ]
        if text:
            parts.append(types.Part(text=text))
        return LlmResponse(
            content=types.Content(role="model", parts=parts),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=0, candidates_token_count=0
            ),
        )


class OfflineCustomerModel(BaseLlm):
    """Scripted classification fixture, not an LLM or a quality evaluation."""

    model: str = OFFLINE_MODEL

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if stream:
            raise ValueError("Offline fixture uses nonstreaming turns")
        if llm_request.tools_dict:
            raise PermissionError("Customer classification cannot invoke tools")
        prompt = next(
            part.text
            for content in llm_request.contents
            if content.role == "user"
            for part in content.parts or []
            if part.text
        )
        body = json.loads(prompt)
        text = body["untrusted_complaint"].lower()
        category: Literal["status", "delay", "refund", "escalate"] = "escalate"
        if not any(word in text for word in ("ignore", "instruction", "policy", "execute")):
            if "refund" in text:
                category = "refund"
            elif any(word in text for word in ("late", "delay")):
                category = "delay"
            elif any(word in text for word in ("status", "where")):
                category = "status"
        advice = Advice(
            category=category,
            reply="Your delivery concern is recorded for review. No refund has been authorized.",
        )
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=advice.model_dump_json())]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=0, candidates_token_count=0
            ),
            model_version=OFFLINE_MODEL,
        )


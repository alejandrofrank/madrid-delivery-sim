"""In-memory tool fixtures for Google's evaluator; production SQL tests remain separate."""

from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext

from delivery.adk_contracts import effective_instructions, restaurant_template
from delivery.adk_offline import OfflineCustomerModel, OfflineRestaurantModel
from delivery.adk_restaurant import RestaurantPlan
from delivery.customer_service import SYSTEM, Advice
from delivery.eval_checks import code_checks


def read_order(tool_context: ToolContext) -> dict[str, Any]:
    """Read this fixture's scoped order."""
    return dict(tool_context.state["fixture"]["order"])


def read_recipe(tool_context: ToolContext) -> dict[str, Any]:
    """Read the fixture recipe."""
    return dict(tool_context.state["fixture"]["recipe"])


def read_pantry(tool_context: ToolContext) -> list[dict[str, Any]]:
    """Read fixture stock."""
    return list(tool_context.state["fixture"]["pantry"])


def find_suppliers(tool_context: ToolContext) -> list[dict[str, Any]]:
    """Read public supplier quotes."""
    return list(tool_context.state["fixture"]["suppliers"])


def recall_order_memory() -> list[Any]:
    """No cross-order memory exists in this fixture."""
    return []


def _stage(context: ToolContext, action: str, **args: str) -> dict[str, Any]:
    if context.state.get("action"):
        raise ValueError("Stage exactly one action")
    context.state["action"] = {"action": action, **args}
    return {"ok": True}


def request_missing_ingredients(supplier: str, tool_context: ToolContext) -> dict[str, Any]:
    """Stage sourcing from a quoted supplier."""
    if supplier not in {s["id"] for s in tool_context.state["fixture"]["suppliers"]}:
        raise ValueError("Unknown supplier")
    return _stage(tool_context, "source", supplier=supplier)


def confirm_order(tool_context: ToolContext) -> dict[str, Any]:
    """Stage order confirmation."""
    return _stage(tool_context, "confirm")


def receive_ingredient(tool_context: ToolContext) -> dict[str, Any]:
    """Stage ingredient arrival."""
    return _stage(tool_context, "receive")


def prepare_meal(tool_context: ToolContext) -> dict[str, Any]:
    """Stage cooking."""
    return _stage(tool_context, "cook")


def offer_substitution(substitute: str, tool_context: ToolContext) -> dict[str, Any]:
    """Stage an alternative for consent."""
    return _stage(tool_context, "offer", substitute=substitute)


def decline_order(reason: str, tool_context: ToolContext) -> dict[str, Any]:
    """Stage a bounded refusal."""
    return _stage(tool_context, "decline", reason=reason)


def finish_decision(summary: str, tool_context: ToolContext) -> dict[str, Any]:
    """Validate the production plan schema, including the 500-character limit."""
    plan = RestaurantPlan(**tool_context.state["action"], summary=summary)
    tool_context.state["plan"] = plan.model_dump()
    return {"ok": True}


def restaurant_agent() -> LlmAgent:
    def instruction(context: Any) -> str:
        brain, soul = restaurant_template(context.state.get("soul", "cost"))
        return effective_instructions(brain, soul)

    return LlmAgent(
        name="restaurant",
        model=OfflineRestaurantModel(),
        instruction=instruction,
        tools=[
            read_order,
            read_recipe,
            read_pantry,
            find_suppliers,
            recall_order_memory,
            request_missing_ingredients,
            confirm_order,
            receive_ingredient,
            prepare_meal,
            offer_substitution,
            decline_order,
            finish_decision,
        ],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def customer_agent() -> LlmAgent:
    def check(callback_context: CallbackContext, llm_response: LlmResponse) -> None:
        del callback_context
        parts = llm_response.content.parts if llm_response.content else []
        calls = [p.function_call.model_dump() for p in parts or [] if p.function_call]
        text = "".join(p.text or "" for p in parts or [] if not p.thought)
        if code_checks(calls=calls, response=text, response_schema=Advice):
            raise ValueError("Customer response failed deterministic checks")

    return LlmAgent(
        name="customer_service",
        model=OfflineCustomerModel(),
        instruction=SYSTEM,
        output_schema=Advice,
        after_model_callback=check,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def chaos_dispatcher() -> LlmAgent:
    from delivery.chaos_agents import OfflineRecoveryModel, RecoveryTurn

    return RecoveryTurn("dispatcher").build(OfflineRecoveryModel())


def chaos_restaurant() -> LlmAgent:
    from delivery.chaos_agents import OfflineRecoveryModel, RecoveryTurn

    return RecoveryTurn("restaurant-kitchen").build(OfflineRecoveryModel())


def chaos_customer() -> LlmAgent:
    from delivery.chaos_agents import OfflineRecoveryModel, RecoveryTurn

    return RecoveryTurn("customer_service").build(OfflineRecoveryModel())


class NativeRecoveryEvalAgent(BaseAgent):
    """ADK evaluates cases concurrently; each invocation owns its scoped tool state."""

    role: str

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from delivery.chaos_agents import OfflineRecoveryModel, RecoveryTurn

        agent = RecoveryTurn(self.role).build(OfflineRecoveryModel())
        async for event in agent.run_async(ctx):
            yield event

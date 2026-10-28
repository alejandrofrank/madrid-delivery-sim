"""Google ADK reasoning over scoped tools; model I/O never holds a SQL connection.

Offline is the default. Vertex requires an explicit approved deployment profile
and durable monetary admission; there is no automatic provider fallback.
"""

import asyncio
import hashlib
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.run_config import RunConfig
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from delivery.adk_contracts import effective_instructions
from delivery.db import connect
from delivery.queue import Event

if TYPE_CHECKING:
    from delivery.agent_runtime import LocalAgent


class RestaurantPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action: Literal["source", "confirm", "receive", "cook", "offer", "decline"]
    supplier: str | None = Field(default=None, min_length=1, max_length=64)
    substitute: str | None = Field(default=None, min_length=1, max_length=80)
    reason: str | None = Field(default=None, min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=500)


class RestaurantTurn:
    """One event/identity-bound capability pack, without a live DB connection."""

    def __init__(
        self,
        agent: "LocalAgent",
        event: Event,
        nonce: str,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        if agent.role.name != "restaurant" or agent.role.policy != "adk" or not agent.role.brain:
            raise PermissionError("A frozen ADK restaurant definition is required")
        self.agent, self.event, self.nonce = agent, event, nonce
        self.brain = agent.role.brain
        self.fault = fault or (lambda stage: None)
        self.action: dict[str, Any] | None = None
        self.plan: RestaurantPlan | None = None
        self.pending_step: int | None = None

    def sql(self, function: str, *args: Any) -> Any:
        # Function names are literals in this module, never model arguments.
        parameters = (self.event.id, self.event.token, self.event.attempts, self.nonce, *args)
        placeholders = ",".join(["%s"] * len(parameters))
        with connect(self.agent.dsn) as conn:
            row = conn.execute(
                f"SELECT public.{function}({placeholders}) AS data", parameters
            ).fetchone()
            assert row
            return row["data"]

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if self.plan is not None:
            raise PermissionError("Decision already finished")
        if name not in self.brain.tools:
            raise PermissionError("Capability is not enabled by the frozen template")
        return self.sql("restaurant_tool", name, Jsonb(arguments or {}))

    def read_order(self) -> dict[str, Any]:
        """Read the current order, incoming event, deadline and safe alternative."""
        return dict(self.invoke("restaurant.order"))

    def read_pantry(self) -> list[dict[str, Any]]:
        """Read only this restaurant's physical stock and reservations."""
        return list(self.invoke("restaurant.pantry"))

    def read_recipe(self) -> dict[str, Any]:
        """Read the frozen recipe and canonical ingredient quantities for this meal."""
        return dict(self.invoke("restaurant.recipe"))

    def find_suppliers(self) -> list[dict[str, Any]]:
        """Find open markets' public fee and estimated lead-time quotes, without private stock."""
        return list(self.invoke("restaurant.suppliers"))

    def recall_order_memory(self) -> list[dict[str, Any]]:
        """Recall only current, unexpired typed restaurant facts for this order."""
        return list(self.invoke("memory.read"))

    def stage(self, name: str, action: str, **arguments: Any) -> dict[str, Any]:
        if self.action is not None:
            raise PermissionError("Stage exactly one business action per event")
        result = self.invoke(name, arguments)
        self.action = {"action": action, **arguments}
        return dict(result)

    def request_missing_ingredients(self, supplier: str) -> dict[str, Any]:
        """Stage sourcing from an open market; SQL calculates shortages and queues requests."""
        if not 1 <= len(supplier) <= 64:
            raise ValueError("Invalid supplier reference")
        return self.stage("restaurant.request_supply", "source", supplier=supplier)

    def confirm_order(self) -> dict[str, Any]:
        """Stage acceptance using physical pantry stock; fails if sourcing is needed."""
        return self.stage("restaurant.confirm", "confirm")

    def receive_ingredient(self) -> dict[str, Any]:
        """Stage receipt of the ingredient named by the current arrival event."""
        return self.stage("restaurant.receive", "receive")

    def prepare_meal(self) -> dict[str, Any]:
        """Stage cooking at its due event, using arrived and consented ingredients."""
        return self.stage("restaurant.cook", "cook")

    def offer_substitution(self, substitute: str) -> dict[str, Any]:
        """Stage a safe alternative offer; a queued household reply must approve it."""
        if not 1 <= len(substitute) <= 80:
            raise ValueError("Invalid alternative")
        return self.stage("restaurant.offer", "offer", substitute=substitute)

    def decline_order(self, reason: str) -> dict[str, Any]:
        """Stage an order decline and release reservations, with a bounded factual reason."""
        if not 1 <= len(reason) <= 240:
            raise ValueError("Invalid reason")
        return self.stage("restaurant.decline", "decline", reason=reason)

    def finish_decision(self, summary: str) -> dict[str, Any]:
        """Finish the staged decision with a concise explanation; nothing is committed yet."""
        if self.action is None:
            raise ValueError("Stage an action before finishing")
        plan = RestaurantPlan(**self.action, summary=summary)
        result = self.invoke("restaurant.finish", {"summary": summary})
        self.plan = plan
        return dict(result)

    def before_model(self, callback_context: CallbackContext, llm_request: LlmRequest) -> None:
        del callback_context
        if self.pending_step is not None:
            raise PermissionError("An unfinished model call cannot be retried")
        body = json.dumps(
            {
                "contents": [
                    c.model_dump(mode="json", exclude_none=True) for c in llm_request.contents
                ],
                "config": llm_request.config.model_dump(mode="json", exclude_none=True),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        self.pending_step = int(
            self.sql("restaurant_model_admit", len(body), hashlib.sha256(body).hexdigest())
        )
        self.fault("before_adk_model")

    def after_model(self, callback_context: CallbackContext, llm_response: LlmResponse) -> None:
        del callback_context
        if llm_response.partial:
            return
        if self.pending_step is None:
            raise PermissionError("Model receipt has no admitted dispatch")
        self.fault("after_adk_model")
        usage = llm_response.usage_metadata
        receipt: dict[str, Any] = {
            "known": usage is not None,
            "model_version": llm_response.model_version,
        }
        if usage is not None:
            receipt.update(usage.model_dump(mode="json", exclude_none=True))
        self.sql("restaurant_model_complete", self.pending_step, Jsonb(receipt))
        self.pending_step = None

    def build(self, model: BaseLlm) -> LlmAgent:
        from delivery.adk_models import validate_model

        validate_model(self.brain, model)
        registry: dict[str, Callable[..., Any]] = {
            "restaurant.order": self.read_order,
            "restaurant.pantry": self.read_pantry,
            "restaurant.recipe": self.read_recipe,
            "restaurant.suppliers": self.find_suppliers,
            "memory.read": self.recall_order_memory,
            "restaurant.request_supply": self.request_missing_ingredients,
            "restaurant.confirm": self.confirm_order,
            "restaurant.receive": self.receive_ingredient,
            "restaurant.cook": self.prepare_meal,
            "restaurant.offer": self.offer_substitution,
            "restaurant.decline": self.decline_order,
            "restaurant.finish": self.finish_decision,
        }
        return LlmAgent(
            name="restaurant",
            model=model,
            instruction=lambda _: effective_instructions(self.brain, self.agent.role.soul),
            tools=[tool for capability, tool in registry.items() if capability in self.brain.tools],
            before_model_callback=self.before_model,
            after_model_callback=self.after_model,
            before_tool_callback=self.before_tool,
            generate_content_config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=self.brain.output_tokens,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

    def before_tool(self, tool: Any, args: dict[str, Any], tool_context: Any) -> None:
        del tool_context
        fields = {
            "read_order": set(),
            "read_pantry": set(),
            "read_recipe": set(),
            "find_suppliers": set(),
            "recall_order_memory": set(),
            "request_missing_ingredients": {"supplier"},
            "confirm_order": set(),
            "receive_ingredient": set(),
            "prepare_meal": set(),
            "offer_substitution": {"substitute"},
            "decline_order": {"reason"},
            "finish_decision": {"summary"},
        }
        if (
            tool.name not in fields
            or set(args) != fields[tool.name]
            or any(type(value) is not str for value in args.values())
        ):
            raise PermissionError("Tool arguments cannot alter scope or schema")

    async def run(self, model: BaseLlm) -> RestaurantPlan:
        service = InMemorySessionService()
        session = await service.create_session(
            app_name="bakiano_restaurant", user_id=self.agent.scope.agent_id
        )
        runner = Runner(
            app_name="bakiano_restaurant", agent=self.build(model), session_service=service
        )
        try:
            async for _ in runner.run_async(
                user_id=self.agent.scope.agent_id,
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=json.dumps(
                                {
                                    "event_id": self.event.id,
                                    "task": "Inspect this order through scoped tools.",
                                }
                            )
                        )
                    ],
                ),
                run_config=RunConfig(max_llm_calls=self.brain.model_calls_per_event),
            ):
                pass
        finally:
            await runner.close()
        if self.plan is None:
            raise ValueError("Model did not finish a staged decision")
        return self.plan


def ensure_restaurant_result(
    agent: "LocalAgent",
    event: Event,
    *,
    model: BaseLlm | None = None,
    fault: Callable[[str], None] | None = None,
) -> bool:
    with connect(agent.dsn) as conn:
        row = conn.execute(
            "SELECT public.restaurant_turn_begin(%s,%s,%s) AS data",
            (event.id, event.token, event.attempts),
        ).fetchone()
        assert row
        receipt = row["data"]
    if receipt["state"] == "succeeded":
        return True
    if receipt["state"] in {"failed", "unknown", "applied"}:
        raise RuntimeError("RestaurantTurnUnavailable")
    if not receipt["dispatch"]:
        return False
    from delivery.adk_models import create_restaurant_model

    turn = RestaurantTurn(agent, event, receipt["nonce"], fault)
    turn.fault("after_adk_begin")
    try:

        async def run() -> RestaurantPlan:
            return await asyncio.wait_for(
                turn.run(model or create_restaurant_model(turn.brain)), turn.brain.timeout_seconds
            )

        plan = asyncio.run(run())
        turn.fault("before_adk_save")
        turn.sql("restaurant_turn_save", Jsonb(plan.model_dump()), None)
        turn.fault("after_adk_save")
        return True
    except Exception as exc:
        turn.sql("restaurant_turn_save", None, type(exc).__name__)
        raise

"""Google ADK reasoning over scoped tools; model I/O never holds a SQL connection.

Offline is the default. Vertex requires an explicit approved deployment profile
and durable monetary admission; there is no automatic provider fallback.
"""

import asyncio
import hashlib
import json
import time
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
from opentelemetry.trace import Span, Status, StatusCode
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from delivery.adk_contracts import effective_instructions
from delivery.db import connect
from delivery.queue import Event
from delivery.telemetry import (
    mark_error,
    record_model_usage,
    start_span,
    trace_span,
    traced_event,
    traced_tool,
)

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
        self.model_started: float | None = None
        self.declared_tool_names: frozenset[str] = frozenset()
        self.model_span: Span | None = None

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
        with trace_span(
            "agent.capability",
            attributes={"delivery.agent": "restaurant", "delivery.capability": name},
        ):
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

    def recall_order_memory(self, query: str = "") -> Any:
        """Recall current facts for this order; an optional query ranks semantic profiles."""
        from delivery.memory_profiles import project_memory

        profile = self.agent.role.memory
        facts = list(self.invoke("memory.read"))
        if profile is not None and profile.mode == "semantic":
            from delivery.semantic_memory import backend, rank_facts

            with connect(self.agent.dsn) as conn:
                ids, audit = rank_facts(
                    facts, query or f"restaurant {self.event.topic}",
                    {"run": self.agent.scope.run, "store": self.agent.scope.store,
                     "role": "restaurant", "context_type": "order",
                     "context_id": facts[0]["context_id"] if facts else "",
                     "subject": facts[0]["subject"] if facts else ""},
                    backend(conn, self.event),
                )
            # This SQL boundary rechecks the turn nonce and performs a fresh charged
            # recall after network I/O. Its receipt becomes the final ADK memory audit.
            facts = list(self.sql("restaurant_semantic_recall", Jsonb(ids), Jsonb(audit)))
        return project_memory(profile, facts)

    def search_ingredients(self, query: str) -> dict[str, Any]:
        """Classify ingredient matches in this restaurant's index; never reserve stock.

        The operator selects local or Jev review and freezes a separate call/token
        budget. Only ingredient labels and units go to Jev, never order memory.
        """
        from delivery.supply_search_service import search_for_agent

        if self.plan is not None or "supply.search" not in self.brain.tools:
            raise PermissionError("Search capability unavailable")
        recipe = self.read_recipe()
        if query not in {item["id"] for item in recipe["ingredients"]}:
            raise PermissionError("Search can disclose only a canonical current-recipe ingredient")
        with connect(self.agent.dsn) as conn:
            row = conn.execute(
                "SELECT public.supply_search_settings(%s,%s,%s) AS data",
                (self.event.id, self.event.token, self.event.attempts),
            ).fetchone()
            assert row
            mode = row["data"]["provider"]
        return search_for_agent(self.agent, self.event, query, mode)

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
        """Finish the staged decision; nothing is committed yet.

        Args:
            summary: Factual explanation of 1 to 500 characters, including spaces.
                Compare quoted values concisely. If rejected, rewrite this text
                without staging another action. Do not truncate a previous answer.
        """
        if self.action is None:
            raise ValueError("Stage an action before finishing")
        if not 1 <= len(summary) <= 500:
            return dict(self.sql("restaurant_contract_reject", "finish_decision", "summary_length"))
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
        self.sql("restaurant_model_trace", self.pending_step, Jsonb(json.loads(body)), None, None)
        self.model_started = time.monotonic()
        self.model_span = start_span(
            "agent.model",
            {
                "delivery.agent": "restaurant",
                "gen_ai.system": self.brain.provider,
                "gen_ai.request.model": self.brain.vertex.model if self.brain.vertex else "offline",
                "delivery.model_step": self.pending_step,
            },
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
        if self.model_span is not None:
            profile = self.brain.vertex
            record_model_usage(
                self.model_span,
                usage,
                profile.input_usd_per_million if profile else 0.0,
                profile.output_usd_per_million if profile else 0.0,
            )
            self.model_span.set_attribute("delivery.success", not bool(llm_response.error_code))
            if llm_response.error_code:
                self.model_span.set_attribute("error.type", "ModelResponseError")
                self.model_span.set_status(Status(StatusCode.ERROR))
            self.model_span.end()
            self.model_span = None
        self.sql(
            "restaurant_model_trace",
            self.pending_step,
            None,
            Jsonb(
                llm_response.content.model_dump(mode="json", exclude_none=True)
                if llm_response.content
                else {}
            ),
            max(0, round((time.monotonic() - (self.model_started or time.monotonic())) * 1000)),
        )
        self.sql("restaurant_model_complete", self.pending_step, Jsonb(receipt))
        self.pending_step = None
        self.model_started = None

    def build(self, model: BaseLlm) -> LlmAgent:
        from delivery.adk_models import validate_model

        validate_model(self.brain, model)
        registry: dict[str, Callable[..., Any]] = {
            "restaurant.order": self.read_order,
            "restaurant.pantry": self.read_pantry,
            "restaurant.recipe": self.read_recipe,
            "restaurant.suppliers": self.find_suppliers,
            "memory.read": self.recall_order_memory,
            "supply.search": self.search_ingredients,
            "restaurant.request_supply": self.request_missing_ingredients,
            "restaurant.confirm": self.confirm_order,
            "restaurant.receive": self.receive_ingredient,
            "restaurant.cook": self.prepare_meal,
            "restaurant.offer": self.offer_substitution,
            "restaurant.decline": self.decline_order,
            "restaurant.finish": self.finish_decision,
        }
        tools = [tool for capability, tool in registry.items() if capability in self.brain.tools]
        self.declared_tool_names = frozenset(tool.__name__ for tool in tools)
        return LlmAgent(
            name="restaurant",
            model=model,
            instruction=lambda _: effective_instructions(self.brain, self.agent.role.soul),
            tools=[traced_tool("restaurant")(tool) for tool in tools],
            before_model_callback=self.before_model,
            after_model_callback=self.after_model,
            before_tool_callback=self.before_tool,
            after_tool_callback=self.after_tool,
            generate_content_config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=self.brain.output_tokens,
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode=types.FunctionCallingConfigMode.VALIDATED,
                        allowed_function_names=sorted(self.declared_tool_names),
                    )
                ),
                thinking_config=(
                    types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
                    if self.brain.vertex and self.brain.vertex.model.startswith("gemini-3")
                    else types.ThinkingConfig(thinking_budget=0)
                ),
            ),
        )

    def before_tool(
        self, tool: Any, args: dict[str, Any], tool_context: Any
    ) -> dict[str, Any] | None:
        try:
            return self._before_tool(tool, args, tool_context)
        except Exception:
            # Validation rejects before the normal tool wrapper can run.
            with trace_span(
                "agent.tool",
                attributes={"delivery.agent": "restaurant", "delivery.tool": tool.name},
            ):
                raise

    def _before_tool(
        self, tool: Any, args: dict[str, Any], tool_context: Any
    ) -> dict[str, Any] | None:
        del tool_context
        fields = {
            "read_order": set(),
            "read_pantry": set(),
            "read_recipe": set(),
            "find_suppliers": set(),
            "recall_order_memory": set(),
            "search_ingredients": {"query"},
            "request_missing_ingredients": {"supplier"},
            "confirm_order": set(),
            "receive_ingredient": set(),
            "prepare_meal": set(),
            "offer_substitution": {"substitute"},
            "decline_order": {"reason"},
            "finish_decision": {"summary"},
        }
        if self.plan is not None:
            raise PermissionError("Decision already finished")
        if tool.name in fields and tool.name not in self.declared_tool_names:
            raise PermissionError("Tool is not enabled by the frozen template")
        # Do not alias or execute an invented name. Its completed model response
        # may receive one bounded correction; scope/argument violations stay fatal.
        if tool.name not in fields:
            if set(args) - {"summary"} or any(type(value) is not str for value in args.values()):
                raise PermissionError("Unknown tool cannot carry scope or arbitrary arguments")
            with trace_span(
                "agent.tool",
                attributes={
                    "delivery.agent": "restaurant",
                    "delivery.tool": tool.name,
                    "delivery.success": False,
                    "error.type": "UnknownTool",
                },
            ) as span:
                span.set_status(Status(StatusCode.ERROR))
                return dict(self.sql("restaurant_contract_reject", tool.name, "unknown_tool"))
        if set(args) != fields[tool.name] or any(type(value) is not str for value in args.values()):
            raise PermissionError("Tool arguments cannot alter scope or schema")
        return None

    def after_tool(
        self, tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
    ) -> None:
        del args, tool_response
        if tool.name == "finish_decision" and self.plan is not None:
            # The saved factual plan is the response. Do not pay for an extra
            # summarization turn after the terminal tool has sealed it.
            tool_context.actions.skip_summarization = True

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


@traced_event("agent.restaurant")
def ensure_restaurant_result(
    agent: "LocalAgent",
    event: Event,
    *,
    model: BaseLlm | None = None,
    fault: Callable[[str], None] | None = None,
    router_reviewer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
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
            async def decide() -> RestaurantPlan:
                if turn.brain.routing:
                    from delivery.jev_routing import route_turn

                    if route_turn(turn, router_reviewer):
                        assert turn.plan
                        return turn.plan
                return await turn.run(model or create_restaurant_model(turn.brain))

            return await asyncio.wait_for(decide(), turn.brain.timeout_seconds)

        plan = asyncio.run(run())
        turn.fault("before_adk_save")
        turn.sql("restaurant_turn_save", Jsonb(plan.model_dump()), None)
        turn.fault("after_adk_save")
        return True
    except Exception as exc:
        if turn.model_span is not None:
            mark_error(turn.model_span, exc)
        turn.sql("restaurant_turn_save", None, type(exc).__name__)
        raise
    finally:
        if turn.model_span is not None:
            turn.model_span.end()
            turn.model_span = None

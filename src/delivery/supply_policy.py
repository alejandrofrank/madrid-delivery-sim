"""Deterministic local supply decisions through a lease-bound SQL command."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from delivery.agent_runtime import ScopedTools
from delivery.queue import Event
from delivery.typed_memory import outcome_fact


class SupplyRef(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    order: str = Field(min_length=1, max_length=200)


class SupplyPolicy:
    def decide(self, event: Event, tools: ScopedTools) -> dict[str, Any]:
        order = SupplyRef.model_validate(event.payload).order
        context = tools.invoke("supply.read", order=order)
        memory = tools.invoke("memory.read")
        result = tools.invoke("supply.command")
        # Broad replay projections stay in the operator ledger. Supplier memories
        # cannot learn household identity, preferences, recipes or pantry stock.
        tools.invoke(
            "memory.write",
            **outcome_fact(
                tools.role.name, event.topic, result, context, event.payload.get("request")
            ),
        )
        return {
            **result,
            "rule": "local deterministic supply transition; SQL owns stock, consent and recipients",
            "policy": "rules_only",
            "model_calls": 0,
            "observed_state": {
                "requests": len(context.get("requests", [])),
                "stock_rows": len(context.get("stock", [])),
            },
            "memory_hits": len(memory),
            "tools": tools.calls,
            "scope": {"run": tools.scope.run, "namespace": tools.scope.store},
            "role_hash": tools.scope.definition_hash,
        }

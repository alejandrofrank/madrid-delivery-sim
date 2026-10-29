"""Immutable, local inventory role data bounded by server-owned authority."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from delivery.adk_contracts import RESTAURANT_TOOLS, RestaurantBrain
from delivery.memory_profiles import MemoryProfile

INVENTORY_ACCEPTS = frozenset(
    {"basket.requested", "shipment.delayed", "shipment.received", "reservation.expire"}
)
INVENTORY_EMITS = frozenset({"inventory.decided", "shipment.received", "basket.reserved"})
INVENTORY_TOOLS = frozenset(
    {
        "inventory.read",
        "inventory.reserve",
        "inventory.release",
        "inventory.delay",
        "inventory.receive",
        "memory.read",
        "memory.write",
        "queue.publish",
    }
)


AUTHORITY = {
    "inventory": {"accepts": INVENTORY_ACCEPTS, "emits": INVENTORY_EMITS, "tools": INVENTORY_TOOLS},
    "fulfillment": {
        "accepts": frozenset({"basket.reserved"}),
        "emits": frozenset({"basket.ready"}),
        "tools": frozenset(
            {"fulfillment.read", "fulfillment.pick", "memory.read", "memory.write", "queue.publish"}
        ),
    },
    "dispatcher": {
        "accepts": frozenset(
            {
                "basket.ready",
                "delivery.arrived",
                "dispatch.retry",
                "recovery.reviewed",
                "courier.accepted",
            }
        ),
        "emits": frozenset(
            {
                "delivery.assigned",
                "delivery.completed",
                "courier.briefed",
                "recovery.requested",
                "dispatch.retry",
                "dispatch.noted",
            }
        ),
        "tools": frozenset(
            {
                "dispatch.read",
                "dispatch.assign",
                "dispatch.complete",
                "dispatch.recover",
                "dispatch.defer",
                "memory.read",
                "memory.write",
                "queue.publish",
            }
        ),
    },
}

AUTHORITY["courier"] = {
    "accepts": frozenset({"courier.briefed"}),
    "emits": frozenset({"courier.accepted"}),
    "tools": frozenset(
        {"courier.read", "courier.accept", "memory.read", "memory.write", "queue.publish"}
    ),
}
AUTHORITY["judge"] = {
    "accepts": frozenset({"delivery.failed"}),
    "emits": frozenset({"recovery.reviewed"}),
    "tools": frozenset(
        {"judge.read", "judge.review", "memory.read", "memory.write", "queue.publish"}
    ),
}

# Supply-chain agents share the same runtime. Their command publishes a fixed,
# transactional outbox; a prompt cannot choose arbitrary recipients or tools.
SUPPLY_ACCEPTS = {
    "household": {"household.intent", "household.offer", "household.status", "meal.delivery"},
    "restaurant": {
        "household.call",
        "ingredient.shortage",
        "ingredient.arrived",
        "restaurant.approval",
        "restaurant.cook",
    },
    "market": {"market.request", "market.transfer"},
}
SUPPLY_EMITS = {
    "household": {"household.call", "restaurant.approval", "meal.delivery"},
    "restaurant": {
        "market.request",
        "household.offer",
        "household.status",
        "restaurant.cook",
        "basket.ready",
        "meal.delivery",
    },
    "market": {"market.request", "market.transfer", "ingredient.shortage", "ingredient.arrived"},
}
for _supply_role, _topics in SUPPLY_ACCEPTS.items():
    AUTHORITY[_supply_role] = {
        "accepts": frozenset(_topics),
        "emits": frozenset(SUPPLY_EMITS[_supply_role]),
        "tools": frozenset(
            {"supply.read", "supply.command", "supply.search", "memory.read", "memory.write"}
        ),
    }

AUTHORITY["restaurant"]["tools"] |= RESTAURANT_TOOLS


class RoleLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    events_per_run: int = Field(default=100, ge=1, le=1000, strict=True)
    tool_calls_per_event: int = Field(default=8, ge=1, le=16, strict=True)
    tool_calls_per_run: int = Field(default=400, ge=1, le=2000, strict=True)
    memory_entries: int = Field(default=32, ge=1, le=100, strict=True)
    memory_bytes: int = Field(default=16384, ge=1, le=65536, strict=True)
    model_calls: int = Field(default=0, ge=0, le=100, strict=True)
    model_tokens: int = Field(default=0, ge=0, le=51200, strict=True)
    model_usd: Literal[0] = 0


class _RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    role: Literal[
        "inventory",
        "fulfillment",
        "dispatcher",
        "courier",
        "judge",
        "household",
        "restaurant",
        "market",
    ]
    version: str = Field(min_length=1, max_length=64)
    policy: Literal["deterministic", "gcp_ai", "adk"]
    brain: RestaurantBrain | None = None
    memory: MemoryProfile | None = None
    soul_file: Literal["SOUL.md"]
    accepts: tuple[str, ...]
    emits: tuple[str, ...]
    tools: tuple[str, ...]
    limits: RoleLimits = Field(default_factory=RoleLimits)

    @model_validator(mode="after")
    def model_authority(self) -> "_RoleConfig":
        if self.policy == "adk":
            if self.role != "restaurant" or self.brain is None:
                raise ValueError("ADK requires a restaurant template")
            if set(self.tools) != set(self.brain.tools) or "supply.command" in self.tools:
                raise ValueError("ADK tools must match the frozen granular template")
        elif self.brain is not None:
            raise ValueError("A reasoning template requires ADK policy")
        if self.policy == "gcp_ai":
            if self.role != "judge" or not self.limits.model_calls or not self.limits.model_tokens:
                raise ValueError("Only the bounded recovery judge may use GCP AI")
        elif self.limits.model_calls or self.limits.model_tokens:
            raise ValueError("Deterministic roles cannot reserve model budgets")
        return self

    @field_validator("accepts", "emits", "tools")
    @classmethod
    def enforce_authority(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        assert info.field_name is not None
        authority = AUTHORITY[str(info.data["role"])][info.field_name]
        if len(value) != len(set(value)) or not set(value).issubset(authority):
            raise ValueError(f"{info.field_name} exceeds server authority or contains duplicates")
        return value


class RoleSpec(_RoleConfig):
    """Run snapshot: SOUL is descriptive text and never grants authority."""

    soul: str

    @property
    def name(self) -> str:
        return self.role

    @property
    def digest(self) -> str:
        definition = self.model_dump(mode="json")
        if self.brain is None:
            definition.pop("brain")  # Preserve hashes of previously frozen definitions.
        if self.memory is None:
            definition.pop("memory")
        payload = json.dumps(definition, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_inventory_role(root: Path = Path("config/agents/inventory")) -> RoleSpec:
    """Load only role.json and the fixed SOUL.md file; validate before reading SOUL."""
    config = _RoleConfig.model_validate_json((root / "role.json").read_text(encoding="utf-8"))
    soul_path = root / "SOUL.md"
    if soul_path.resolve().parent != root.resolve():
        raise ValueError("SOUL.md must remain inside the role directory")
    return RoleSpec(**config.model_dump(), soul=soul_path.read_text(encoding="utf-8"))


def load_role(name: str) -> RoleSpec:
    if name not in AUTHORITY and name != "judge-gcp":
        raise ValueError("Unknown role")
    role = load_inventory_role(Path("config/agents") / name)
    if role.name != ("judge" if name == "judge-gcp" else name):
        raise ValueError("Role directory does not match role identity")
    return role

"""Frozen local supply definitions and bounded, household-specific meal demand.

Text and timings are editable business data. Entity kinds and server-owned tools
remain the authority boundary; descriptive agent text cannot grant capabilities.
"""

import hashlib
import json
import random
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from delivery.adk_contracts import RestaurantBrain
from delivery.agent_specs import RoleLimits
from delivery.city import fake_city
from delivery.meal_snapshot import IngredientId, RecipeId, load_meal_snapshot
from delivery.urban_city import urban_city

MAX_CALLS = 64
AgentRole = Literal["household", "restaurant", "market"]
AGENT_ROLES = frozenset({"household", "restaurant", "market"})
AGENT_TOOLS = frozenset(
    {"supply.read", "supply.command", "supply.search", "memory.read", "memory.write"}
)
CANONICAL_INGREDIENT_UNITS: Mapping[str, str] = MappingProxyType(
    {
        "flour": "g",
        "tomato": "g",
        "mozzarella": "g",
        "chicken": "g",
        "flatbread": "piece",
        "lettuce": "g",
        "beef": "g",
        "burger-bun": "piece",
        "potato": "g",
        "salmon": "g",
        "rice": "g",
        "nori": "piece",
        "carrot": "g",
        "onion": "g",
        "water": "ml",
        "cucumber": "g",
        "olive-oil": "ml",
    }
)


class FrozenDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Hours(FrozenDefinition):
    """Half-open local hours; an end before start continues into the next day."""

    start: int = Field(default=0, ge=0, le=23, strict=True)
    end: int = Field(default=24, ge=0, le=24, strict=True)

    @model_validator(mode="after")
    def nonempty_window(self) -> "Hours":
        if self.start == self.end:
            raise ValueError("Hours must describe a nonempty window; use 0..24 for all day")
        return self

    def contains(self, hour: float) -> bool:
        hour %= 24
        return (
            self.start <= hour < self.end
            if self.start < self.end
            else (hour >= self.start or hour < self.end)
        )


class SearchSettings(FrozenDefinition):
    provider: Literal["local", "jev"] = "local"
    calls_limit: int = Field(default=0, ge=0, le=8, strict=True)
    input_tokens_limit: int = Field(default=0, ge=0, le=51200, strict=True)

    @model_validator(mode="after")
    def paid_opt_in(self) -> "SearchSettings":
        if self.provider == "jev" and (not self.calls_limit or not self.input_tokens_limit):
            raise ValueError("Jev requires explicit positive call and token budgets")
        return self


class AgentDefinition(FrozenDefinition):
    display_name: str = Field(min_length=1, max_length=80)
    soul: str = Field(min_length=1, max_length=8192)
    brain: RestaurantBrain | None = None
    latency_seconds: int = Field(default=5, ge=0, le=120, strict=True)
    search: SearchSettings = Field(default_factory=SearchSettings)
    limits: RoleLimits = Field(
        default_factory=lambda: RoleLimits(
            events_per_run=500,
            tool_calls_per_run=2000,
            tool_calls_per_event=5,
            memory_entries=64,
        )
    )

    @model_validator(mode="after")
    def local_budgets(self) -> "AgentDefinition":
        if self.limits.model_calls or self.limits.model_tokens:
            raise ValueError("Local supply agents cannot reserve model calls or model tokens")
        return self


def default_agents() -> Mapping[AgentRole, AgentDefinition]:
    return MappingProxyType(
        {
            "household": AgentDefinition(
                display_name="Household meal caller",
                soul=(
                    "Call an open restaurant for one meal during this household's order hours. "
                    "Describe ingredient exclusions and approve substitutions only when allowed. "
                    "A meal is complete only after cooking and home delivery."
                ),
            ),
            "restaurant": AgentDefinition(
                display_name="Restaurant kitchen",
                soul=(
                    "Confirm the requested recipe. Check physical ingredients, ask the nearest "
                    "open market for shortages, then another market if needed. "
                    "Use substitutions only after household approval; never cook from a forecast."
                ),
            ),
            "market": AgentDefinition(
                display_name="Market stock keeper",
                soul=(
                    "Answer ingredient requests using canonical units and physical stock. "
                    "Reserve stock atomically and transfer only confirmed quantities. "
                    "Report shortages without inventing availability."
                ),
            ),
        }
    )


class EntityDefinition(FrozenDefinition):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    kind: AgentRole
    node: int = Field(ge=0, le=1023, strict=True)
    procurement_fee_cents: int = Field(default=100, ge=0, le=100000, strict=True)
    recipe_ids: tuple[RecipeId, ...] = Field(default=(), max_length=7)
    opening_hours: Hours = Field(default_factory=Hours)
    order_hours: tuple[Hours, ...] = Field(
        default_factory=lambda: (Hours(start=12, end=14), Hours(start=19, end=21)),
        max_length=4,
    )
    allow_substitutions: bool = Field(default=True, strict=True)
    excluded_ingredients: tuple[IngredientId, ...] = Field(default=(), max_length=17)
    agent: AgentDefinition | None = None
    opening_stock: Mapping[IngredientId, Annotated[int, Field(strict=True, ge=0, le=100000)]] = (
        Field(default_factory=lambda: MappingProxyType({}))
    )

    @field_validator("opening_stock")
    @classmethod
    def bounded_opening_stock(cls, value: Mapping[IngredientId, int]) -> Mapping[IngredientId, int]:
        if any(
            type(quantity) is not int or not 0 <= quantity <= 100000 for quantity in value.values()
        ):
            raise ValueError("Opening quantities must be whole canonical units within 0..100000")
        return MappingProxyType(dict(value))

    @field_serializer("opening_stock")
    def serialize_opening_stock(self, value: Mapping[IngredientId, int]) -> dict[str, int]:
        return {str(key): quantity for key, quantity in value.items()}

    @model_validator(mode="after")
    def entity_boundaries(self) -> "EntityDefinition":
        if len(set(self.recipe_ids)) != len(self.recipe_ids):
            raise ValueError("Recipe IDs must be unique per entity")
        if len(set(self.excluded_ingredients)) != len(self.excluded_ingredients):
            raise ValueError("Excluded ingredients must be unique")
        if len(set(self.order_hours)) != len(self.order_hours):
            raise ValueError("Order windows must be unique")
        if self.kind == "restaurant" and not self.recipe_ids:
            raise ValueError("Restaurants must serve at least one canonical meal")
        if self.kind == "market" and self.recipe_ids:
            raise ValueError("Markets provide ingredients rather than prepared meals")
        if self.kind == "household" and self.opening_stock:
            raise ValueError("Households order meals rather than hold business inventory")
        return self


def recipes() -> list[dict[str, Any]]:
    """Return a fresh validated business snapshot, without mutable shared objects."""
    result = [recipe.model_dump(mode="json") for recipe in load_meal_snapshot().recipes]
    if any(
        item["unit"] != CANONICAL_INGREDIENT_UNITS[item["id"]]
        for recipe in result
        for item in recipe["ingredients"]
    ):
        raise ValueError("Meal ingredients must use their canonical units")
    return result


def ingredient_units() -> dict[str, str]:
    return dict(CANONICAL_INGREDIENT_UNITS)


def default_entities() -> tuple[EntityDefinition, ...]:
    city = urban_city(fake_city(42, size=32))
    meals = recipes()
    meal_ids = tuple(recipe["id"] for recipe in meals)
    stores = {store["id"]: store for store in city["stores"]}
    households = tuple(
        EntityDefinition(
            id=customer["id"],
            name=customer["name"],
            kind="household",
            node=customer["home_node"],
            recipe_ids=meal_ids,
        )
        for customer in city["customers"]
    )
    restaurant_stores = (
        "store-2",
        "store-3",
        "store-4",
        "store-6",
        "store-7",
        "store-8",
        "store-9",
    )
    restaurants = tuple(
        EntityDefinition(
            id=f"restaurant-{recipe['id']}",
            name=f"{recipe['name']} Kitchen",
            kind="restaurant",
            node=stores[store_id]["node"],
            recipe_ids=(recipe["id"],),
            opening_hours=Hours(start=11, end=23),
            order_hours=(),
        )
        for recipe, store_id in zip(meals, restaurant_stores, strict=True)
    )
    markets = tuple(
        EntityDefinition(
            id=market_id,
            name=f"{label} Ingredient Market",
            kind="market",
            node=stores[store_id]["node"],
            opening_hours=Hours(start=8, end=23),
            order_hours=(),
        )
        for market_id, label, store_id in (
            ("market-a", "North", "store-1"),
            ("market-b", "Central", "store-5"),
            ("market-c", "South", "store-10"),
        )
    )
    return households + restaurants + markets


class SupplyConfig(FrozenDefinition):
    seed: int = Field(default=42, ge=0, le=2**31 - 1, strict=True)
    duration_minutes: int = Field(default=120, ge=15, le=1440, strict=True)
    start_hour: int = Field(default=11, ge=0, le=23, strict=True)
    playback_seconds: int = Field(default=60, ge=0, le=120, strict=True)
    calls_per_household: int = Field(default=1, ge=0, le=3, strict=True)
    communication_latency_seconds: int = Field(default=5, ge=0, le=120, strict=True)
    supplier_delay_seconds: int = Field(default=60, ge=0, le=1800, strict=True)
    restaurant_stock_servings: int = Field(default=0, ge=0, le=10, strict=True)
    market_stock_servings: int = Field(default=3, ge=0, le=20, strict=True)
    fleet_couriers: int = Field(default=6, ge=1, le=16, strict=True)
    entities: tuple[EntityDefinition, ...] = Field(
        default_factory=default_entities, min_length=3, max_length=160
    )
    agents: Mapping[AgentRole, AgentDefinition] = Field(default_factory=default_agents)

    @field_validator("agents")
    @classmethod
    def fixed_agent_roles(
        cls, value: Mapping[AgentRole, AgentDefinition]
    ) -> Mapping[AgentRole, AgentDefinition]:
        if set(value) != AGENT_ROLES:
            raise ValueError("Configure exactly household, restaurant and market agents")
        return MappingProxyType(dict(value))

    @field_serializer("agents")
    def serialize_agents(self, value: Mapping[AgentRole, AgentDefinition]) -> dict[str, Any]:
        return {role: definition.model_dump(mode="json") for role, definition in value.items()}

    @model_validator(mode="after")
    def unique_entities(self) -> "SupplyConfig":
        if len({entity.id for entity in self.entities}) != len(self.entities):
            raise ValueError("Entity IDs must be unique")
        if {entity.kind for entity in self.entities} != AGENT_ROLES:
            raise ValueError("Include at least one household, restaurant and market")
        for role, agent in self.agents.items():
            if agent.brain is not None and role != "restaurant":
                raise ValueError("Only restaurant definitions support the ADK template")
        for entity in self.entities:
            if entity.agent and entity.agent.brain is not None and entity.kind != "restaurant":
                raise ValueError("ADK template requires a restaurant entity")
        return self

    @property
    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_supply_config() -> SupplyConfig:
    return SupplyConfig()


def default_config() -> SupplyConfig:
    return default_supply_config()


def _intervals(hours: Hours, start: int, end: int) -> list[tuple[int, int]]:
    intervals = []
    for day in range(start // 86400 - 1, end // 86400 + 1):
        low = day * 86400 + hours.start * 3600
        high = day * 86400 + hours.end * 3600
        if hours.end < hours.start:
            high += 86400
        left, right = max(start, low), min(end, high)
        if left < right:
            intervals.append((left, right))
    return intervals


def _merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for low, high in sorted(intervals):
        if result and low <= result[-1][1]:
            result[-1] = (result[-1][0], max(high, result[-1][1]))
        else:
            result.append((low, high))
    return result


def demand_schedule(config: SupplyConfig) -> list[dict[str, Any]]:
    """Seed independent calls per household, then cap the chronological queue.

    Times are simulated seconds since start_hour. Calls occur only in a household
    order window while a restaurant serving its requested meal is open. Entity
    enumeration does not affect an existing household's random sequence.
    """
    if not config.calls_per_household:
        return []
    start = config.start_hour * 3600
    end = start + config.duration_minutes * 60
    meal_data = {recipe["id"]: recipe for recipe in recipes()}
    restaurants = sorted(
        (entity for entity in config.entities if entity.kind == "restaurant"),
        key=lambda entity: entity.id,
    )
    result: list[dict[str, Any]] = []
    for household in sorted(
        (entity for entity in config.entities if entity.kind == "household"),
        key=lambda entity: entity.id,
    ):
        preferred = set(household.recipe_ids or meal_data)
        candidates = [
            restaurant for restaurant in restaurants if preferred & set(restaurant.recipe_ids)
        ]
        windows = _merge(
            [
                (max(order_low, home_low, shop_low), min(order_high, home_high, shop_high))
                for order_hours in household.order_hours
                for order_low, order_high in _intervals(order_hours, start, end)
                for home_low, home_high in _intervals(household.opening_hours, start, end)
                for restaurant in candidates
                for shop_low, shop_high in _intervals(restaurant.opening_hours, start, end)
                if max(order_low, home_low, shop_low) < min(order_high, home_high, shop_high)
            ]
        )
        total_seconds = sum(high - low for low, high in windows)
        if not total_seconds:
            continue
        for ordinal in range(config.calls_per_household):
            entropy = hashlib.sha256(f"{config.seed}:{household.id}:{ordinal}".encode()).digest()
            rng = random.Random(int.from_bytes(entropy, "big"))
            offset = rng.randrange(total_seconds)
            instant = start
            for low, high in windows:
                if offset < high - low:
                    instant = low + offset
                    break
                offset -= high - low
            open_restaurants = [
                restaurant
                for restaurant in candidates
                if restaurant.opening_hours.contains(instant / 3600)
            ]
            available_meals = sorted(
                preferred
                & {meal for restaurant in open_restaurants for meal in restaurant.recipe_ids}
            )
            meal = rng.choice(available_meals)
            serving = [
                restaurant for restaurant in open_restaurants if meal in restaurant.recipe_ids
            ]
            restaurant = rng.choice(serving)
            arrival = instant - start
            transcript = (
                f"Hello, this is {household.name}. I would like one {meal_data[meal]['name']} "
                "for home delivery. "
                + (
                    "I approve safe ingredient substitutions."
                    if household.allow_substitutions
                    else "Please do not substitute ingredients."
                )
            )
            if household.excluded_ingredients:
                transcript += f" Exclude: {', '.join(household.excluded_ingredients)}."
            result.append(
                {
                    "order_id": "meal-"
                    + hashlib.sha256(
                        f"{config.seed}:{household.id}:{ordinal}".encode()
                    ).hexdigest()[:20],
                    "household": household.id,
                    "household_id": household.id,
                    "restaurant": restaurant.id,
                    "restaurant_id": restaurant.id,
                    "meal": meal,
                    "recipe_id": meal,
                    "quantity": 1,
                    "arrival_sim": arrival,
                    "deadline_sim": arrival + 7200,
                    "customer_node": household.node,
                    "transcript": transcript,
                    "allow_substitutions": household.allow_substitutions,
                    "excluded_ingredients": list(household.excluded_ingredients),
                }
            )
    return sorted(result, key=lambda row: (row["arrival_sim"], row["order_id"]))[:MAX_CALLS]

"""Frozen editable definitions, canonical business facts and bounded local calls."""

import json
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from delivery.city import fake_city
from delivery.meal_snapshot import load_meal_snapshot
from delivery.supply_models import (
    AGENT_TOOLS,
    CANONICAL_INGREDIENT_UNITS,
    MAX_CALLS,
    AgentDefinition,
    EntityDefinition,
    Hours,
    SupplyConfig,
    default_config,
    default_supply_config,
    demand_schedule,
    ingredient_units,
    recipes,
)
from delivery.urban_city import urban_city


def config_with(**changes):
    return SupplyConfig.model_validate({**default_config().model_dump(mode="json"), **changes})


def small_entities(*, hours=None, recipe_ids=("pizza",), exclusions=()):
    return [
        EntityDefinition(
            id="home-a",
            name="Household A",
            kind="household",
            node=500,
            recipe_ids=("pizza",),
            order_hours=(hours or Hours(start=12, end=14),),
            excluded_ingredients=exclusions,
        ).model_dump(mode="json"),
        EntityDefinition(
            id="restaurant-a",
            name="Kitchen A",
            kind="restaurant",
            node=100,
            recipe_ids=recipe_ids,
            opening_hours=hours or Hours(start=12, end=14),
        ).model_dump(mode="json"),
        EntityDefinition(
            id="market-a",
            name="Market A",
            kind="market",
            node=99,
        ).model_dump(mode="json"),
    ]


def test_defaults_reuse_real_synthetic_residences_and_separate_shop_anchors():
    config = default_supply_config()
    assert config == default_config()
    assert (config.seed, config.start_hour, config.duration_minutes, config.playback_seconds) == (
        42,
        11,
        120,
        60,
    )
    assert (config.calls_per_household, config.communication_latency_seconds) == (1, 5)
    assert (
        config.supplier_delay_seconds,
        config.restaurant_stock_servings,
        config.market_stock_servings,
    ) == (60, 0, 3)
    city = urban_city(fake_city(42, size=32))
    households = [entity for entity in config.entities if entity.kind == "household"]
    restaurants = [entity for entity in config.entities if entity.kind == "restaurant"]
    markets = [entity for entity in config.entities if entity.kind == "market"]
    assert len(households) == 128 and len(restaurants) == 7 and len(markets) == 3
    assert [(entity.id, entity.node) for entity in households] == [
        (customer["id"], customer["home_node"]) for customer in city["customers"]
    ]
    assert {meal for entity in restaurants for meal in entity.recipe_ids} == {
        recipe.id for recipe in load_meal_snapshot().recipes
    }
    stores = {store["id"]: store["node"] for store in city["stores"]}
    assert {entity.id: entity.node for entity in markets} == {
        "market-a": stores["store-1"],
        "market-b": stores["store-5"],
        "market-c": stores["store-10"],
    }
    assert len({entity.node for entity in restaurants + markets}) == 10


def test_freeze_is_recursive_and_digest_is_canonical_after_json_round_trip():
    config = default_config()
    before = config.digest
    assert len(before) == 64
    assert isinstance(config.agents, MappingProxyType)
    with pytest.raises(ValidationError):
        config.seed = 43
    with pytest.raises(TypeError):
        config.agents["market"] = config.agents["restaurant"]
    with pytest.raises(ValidationError):
        config.entities[0].name = "Changed"
    with pytest.raises(ValidationError):
        config.agents["market"].limits.memory_bytes = 1
    dumped = config.model_dump(mode="json")
    dumped["agents"]["market"]["soul"] = "Edited business behavior"
    assert config.digest == before
    edited = SupplyConfig.model_validate(dumped)
    assert edited.digest != before
    assert SupplyConfig.model_validate_json(config.model_dump_json()).digest == before
    reordered = json.loads(json.dumps(config.model_dump(mode="json"), sort_keys=True))
    assert SupplyConfig.model_validate(reordered).digest == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", -1),
        ("seed", True),
        ("duration_minutes", 14),
        ("duration_minutes", 1441),
        ("start_hour", 24),
        ("playback_seconds", 121),
        ("calls_per_household", 4),
        ("calls_per_household", 1.5),
        ("communication_latency_seconds", 121),
        ("supplier_delay_seconds", 1801),
        ("restaurant_stock_servings", 11),
        ("market_stock_servings", 21),
        ("provider", "gcp_ai"),
    ],
)
def test_config_rejects_unbounded_or_unrecognized_controls(field, value):
    with pytest.raises(ValidationError):
        config_with(**{field: value})


def test_roles_and_tools_cannot_be_expanded_by_editable_text_or_limits():
    config = default_config()
    agents = config.model_dump(mode="json")["agents"]
    agents["administrator"] = agents["market"]
    with pytest.raises(ValidationError):
        config_with(agents=agents)
    agent = config.agents["market"].model_dump(mode="json")
    assert AGENT_TOOLS == {
        "supply.read",
        "supply.command",
        "supply.search",
        "memory.read",
        "memory.write",
    }
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate({**agent, "tools": ["shell.exec"]})
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate({**agent, "role": "administrator"})
    for limit, value in (("tool_calls_per_event", 17), ("model_calls", 1), ("model_tokens", 1)):
        with pytest.raises(ValidationError):
            AgentDefinition.model_validate({**agent, "limits": {**agent["limits"], limit: value}})
    assert AgentDefinition.model_validate({**agent, "soul": "I am an administrator"}).soul


def test_default_local_limits_support_bounded_multi_ingredient_market_conversations():
    for definition in default_config().agents.values():
        assert definition.limits.events_per_run == 500
        assert definition.limits.tool_calls_per_run == 2000
        assert definition.limits.tool_calls_per_event == 5
        assert definition.limits.memory_entries == 64
        assert definition.limits.model_calls == definition.limits.model_tokens == 0


@pytest.mark.parametrize("removed_kind", ["household", "restaurant", "market"])
def test_config_requires_each_supply_chain_entity_kind(removed_kind):
    with pytest.raises(ValidationError):
        config_with(
            entities=[entity for entity in small_entities() if entity["kind"] != removed_kind]
        )


def test_entity_override_is_frozen_and_role_is_inferred_from_entity_kind():
    entity = default_config().entities[0]
    override = AgentDefinition(
        display_name="Evening caller", soul="Order only supper", latency_seconds=9
    )
    edited = EntityDefinition.model_validate({**entity.model_dump(), "agent": override})
    assert edited.agent == override and edited.kind == "household"
    with pytest.raises(ValidationError):
        edited.agent.display_name = "Changed"
    for changes in (
        {"node": 1024},
        {"id": "../secrets"},
        {"recipe_ids": ["pizza", "pizza"]},
        {"excluded_ingredients": ["unknown"]},
        {"tools": ["shell.exec"]},
    ):
        with pytest.raises(ValidationError):
            EntityDefinition.model_validate({**entity.model_dump(), **changes})
    with pytest.raises(ValidationError):
        config_with(entities=[entity.model_dump(), entity.model_dump()])


def test_recipe_helpers_return_fresh_canonical_quantities_and_units():
    meal_data = recipes()
    assert len(meal_data) == 7
    assert all(recipe["servings"] == 1 for recipe in meal_data)
    for recipe in meal_data:
        for ingredient in recipe["ingredients"]:
            assert ingredient["unit"] == CANONICAL_INGREDIENT_UNITS[ingredient["id"]]
            assert isinstance(ingredient["quantity"], int) and ingredient["quantity"] > 0
    meal_data[0]["ingredients"][0]["quantity"] = -1
    assert recipes()[0]["ingredients"][0]["quantity"] > 0
    units = ingredient_units()
    units["flour"] = "ml"
    assert ingredient_units()["flour"] == "g"
    with pytest.raises(TypeError):
        CANONICAL_INGREDIENT_UNITS["flour"] = "ml"


def test_seeded_demand_is_bounded_matches_menus_and_contains_human_call_transcripts():
    config = default_config()
    schedule = demand_schedule(config)
    assert schedule == demand_schedule(config)
    assert len(schedule) == MAX_CALLS
    assert len({call["order_id"] for call in schedule}) == MAX_CALLS
    assert schedule == sorted(schedule, key=lambda row: (row["arrival_sim"], row["order_id"]))
    assert schedule != demand_schedule(config_with(seed=43))
    entities = {entity.id: entity for entity in config.entities}
    for call in schedule:
        home = entities[call["household"]]
        kitchen = entities[call["restaurant"]]
        hour = config.start_hour + call["arrival_sim"] / 3600
        assert 0 <= call["arrival_sim"] < config.duration_minutes * 60
        assert call["quantity"] == 1 and call["deadline_sim"] == call["arrival_sim"] + 7200
        assert call["household_id"] == home.id and call["restaurant_id"] == kitchen.id
        assert call["recipe_id"] == call["meal"] and call["meal"] in kitchen.recipe_ids
        assert call["customer_node"] == home.node
        assert any(window.contains(hour) for window in home.order_hours)
        assert kitchen.opening_hours.contains(hour)
        assert home.name in call["transcript"] and "home delivery" in call["transcript"]


def test_household_random_sequence_does_not_depend_on_entity_enumeration_or_other_households():
    base = config_with(entities=small_entities(), calls_per_household=3)
    schedule = demand_schedule(base)
    assert len(schedule) == 3
    extra_home = {**base.entities[0].model_dump(mode="json"), "id": "other-home", "node": 501}
    expanded = config_with(
        entities=[extra_home] + list(reversed(base.model_dump(mode="json")["entities"])),
        calls_per_household=3,
    )
    assert [call for call in demand_schedule(expanded) if call["household"] == "home-a"] == schedule


def test_empty_demand_and_incompatible_or_closed_menus_are_valid():
    assert demand_schedule(config_with(calls_per_household=0)) == []
    assert demand_schedule(config_with(entities=small_entities(recipe_ids=("sushi",)))) == []
    assert demand_schedule(config_with(entities=small_entities(), start_hour=2)) == []
    entities = small_entities()
    entities[0]["order_hours"] = []
    assert demand_schedule(config_with(entities=entities)) == []


def test_overnight_windows_and_daily_duration_are_clipped_to_simulation():
    hours = Hours(start=23, end=2)
    assert hours.contains(23) and hours.contains(0) and not hours.contains(2)
    config = config_with(
        entities=small_entities(hours=hours),
        start_hour=22,
        duration_minutes=1440,
        calls_per_household=3,
    )
    schedule = demand_schedule(config)
    assert len(schedule) == 3
    assert all(3600 <= call["arrival_sim"] < 4 * 3600 for call in schedule)
    with pytest.raises(ValidationError):
        Hours(start=12, end=12)


def test_transcripts_include_explicit_household_ingredient_exclusions():
    config = config_with(entities=small_entities(exclusions=("mozzarella",)))
    call = demand_schedule(config)[0]
    assert call["excluded_ingredients"] == ["mozzarella"]
    assert "Exclude: mozzarella" in call["transcript"]


def test_opening_stock_is_strict_canonical_immutable_and_changes_digest():
    base = default_config()
    market = next(e for e in base.entities if e.kind == "market")
    data = market.model_dump(mode="json")
    edited = EntityDefinition.model_validate({**data, "opening_stock": {"flour": 250}})
    assert edited.opening_stock["flour"] == 250
    with pytest.raises(TypeError):
        edited.opening_stock["flour"] = 0
    assert edited.model_dump(mode="json")["opening_stock"] == {"flour": 250}
    for stock in ({"flour": True}, {"flour": 1.5}, {"flour": -1}, {"unknown": 1}):
        with pytest.raises(ValidationError):
            EntityDefinition.model_validate({**data, "opening_stock": stock})
    household = next(e for e in base.entities if e.kind == "household")
    with pytest.raises(ValidationError):
        EntityDefinition.model_validate(
            {**household.model_dump(mode="json"), "opening_stock": {"flour": 1}}
        )


def test_paid_search_needs_explicit_bounded_per_agent_opt_in():
    agent = default_config().agents["market"].model_dump(mode="json")
    assert agent["search"] == {"provider": "local", "calls_limit": 0, "input_tokens_limit": 0}
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate({**agent, "search": {"provider": "jev"}})
    enabled = AgentDefinition.model_validate(
        {**agent, "search": {"provider": "jev", "calls_limit": 2, "input_tokens_limit": 12000}}
    )
    assert enabled.search.calls_limit == 2
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate(
            {**agent, "search": {"provider": "jev", "calls_limit": 9, "input_tokens_limit": 12000}}
        )

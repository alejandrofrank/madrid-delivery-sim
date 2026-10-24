"""Small synthetic meal/stock boundary for model-visible business facts."""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RecipeId = Literal["pizza", "kebab", "hamburgers", "steak-frites", "sushi", "soups", "salads"]
RECIPE_IDS = {"pizza", "kebab", "hamburgers", "steak-frites", "sushi", "soups", "salads"}
IngredientId = Literal[
    "flour",
    "tomato",
    "mozzarella",
    "chicken",
    "flatbread",
    "lettuce",
    "beef",
    "burger-bun",
    "potato",
    "salmon",
    "rice",
    "nori",
    "carrot",
    "onion",
    "water",
    "cucumber",
    "olive-oil",
]
Unit = Literal["g", "ml", "piece"]
PositiveQuantity = Annotated[int, Field(strict=True, gt=0, le=10000)]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Ingredient(StrictRecord):
    id: IngredientId
    quantity: PositiveQuantity
    unit: Unit


class Recipe(StrictRecord):
    id: RecipeId
    name: str = Field(min_length=1, max_length=40)
    servings: Literal[1]
    ingredients: list[Ingredient] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_ingredients(self) -> "Recipe":
        if len({item.id for item in self.ingredients}) != len(self.ingredients):
            raise ValueError("Recipe ingredients must be unique")
        return self


class Stock(StrictRecord):
    id: IngredientId
    available: int = Field(ge=0, le=100000, strict=True)
    unit: Unit


class Supermarket(StrictRecord):
    id: Literal["market-a", "market-b", "market-c"]
    stock: list[Stock] = Field(min_length=1, max_length=17)

    @model_validator(mode="after")
    def unique_stock(self) -> "Supermarket":
        if len({item.id for item in self.stock}) != len(self.stock):
            raise ValueError("Stock ingredients must be unique")
        return self


class MealSnapshot(StrictRecord):
    version: Literal["synthetic-meals-v1"]
    synthetic: Literal[True]
    recipes: list[Recipe] = Field(min_length=1, max_length=7)
    supermarkets: list[Supermarket] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def consistent_stock(self) -> "MealSnapshot":
        if len({r.id for r in self.recipes}) != len(self.recipes):
            raise ValueError("Recipe IDs must be unique")
        if len({s.id for s in self.supermarkets}) != 3:
            raise ValueError("Three distinct synthetic supermarkets required")
        units: dict[str, str] = {}
        for recipe in self.recipes:
            for item in recipe.ingredients:
                if item.id in units and units[item.id] != item.unit:
                    raise ValueError("Ingredient units must be consistent")
                units[item.id] = item.unit
        for market in self.supermarkets:
            for stock_item in market.stock:
                if stock_item.id not in units or units[stock_item.id] != stock_item.unit:
                    raise ValueError("Stock must match recipe ingredients and units")
        if len(self.model_dump_json().encode("utf-8")) > 8192:
            raise ValueError("Meal snapshot exceeds 8192-byte business-data budget")
        return self


def load_meal_snapshot(path: Path | None = None) -> MealSnapshot:
    path = path or Path(__file__).resolve().parents[2] / "data/meal-snapshot.json"
    raw = path.read_bytes()
    if len(raw) > 8192:
        raise ValueError("Meal snapshot exceeds 8192-byte business-data budget")
    snapshot = MealSnapshot.model_validate(json.loads(raw))
    if {recipe.id for recipe in snapshot.recipes} != RECIPE_IDS:
        raise ValueError("Snapshot must contain exactly the seven allowlisted meals")
    return snapshot


def snapshot_for_recipe(recipe_id: str) -> MealSnapshot:
    if recipe_id not in RECIPE_IDS:
        raise ValueError("Unknown recipe ID")
    snapshot = load_meal_snapshot()
    recipe = next(recipe for recipe in snapshot.recipes if recipe.id == recipe_id)
    ingredient_ids = {item.id for item in recipe.ingredients}
    return MealSnapshot(
        version=snapshot.version,
        synthetic=True,
        recipes=[recipe],
        supermarkets=[
            Supermarket(id=market.id, stock=[s for s in market.stock if s.id in ingredient_ids])
            for market in snapshot.supermarkets
        ],
    )


def ingredient_shortages(recipe_id: str, supermarket_id: str) -> dict[str, int]:
    """Integer shortfall for one serving; absent stock is unavailable."""
    snapshot = snapshot_for_recipe(recipe_id)
    market = next((m for m in snapshot.supermarkets if m.id == supermarket_id), None)
    if market is None:
        raise ValueError("Unknown supermarket ID")
    stock = {item.id: item.available for item in market.stock}
    return {
        item.id: item.quantity - stock.get(item.id, 0)
        for item in snapshot.recipes[0].ingredients
        if item.quantity > stock.get(item.id, 0)
    }

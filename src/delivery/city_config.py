"""Validated, frozen local experiment settings and seeded demand, never agent authority."""

import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from delivery.city import fake_city


class StoreSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^store-([1-9]|1[0-2])$")
    name: str = Field(min_length=1, max_length=60)
    enabled: bool = True
    stock_units: int = Field(default=3, ge=0, le=20, strict=True)
    couriers: int = Field(default=0, ge=0, le=3, strict=True)
    demand_weight: float = Field(default=1, ge=0, le=3, allow_inf_nan=False)


def default_stores() -> tuple[StoreSettings, ...]:
    return tuple(
        StoreSettings(
            id=s["id"],
            name=s["name"],
            couriers=1 if s["id"] in {"store-1", "store-5", "store-10"} else 0,
        )
        for s in fake_city(size=32)["stores"]
    )


class CitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seed: int = Field(default=42, ge=0, le=2**31 - 1, strict=True)
    duration_minutes: int = Field(default=30, ge=15, le=120, strict=True)
    playback_seconds: int = Field(default=30, ge=0, le=120, strict=True)
    orders_per_hour: float = Field(default=12, ge=0, le=24, allow_inf_nan=False)
    traffic_multiplier: float = Field(default=1.5, ge=0.5, le=3, allow_inf_nan=False)
    dropout_rate: float = Field(default=0.15, ge=0, le=1, allow_inf_nan=False)
    stores: tuple[StoreSettings, ...] = Field(default_factory=default_stores)

    @model_validator(mode="after")
    def boundaries(self) -> "CitySettings":
        if {s.id for s in self.stores} != {f"store-{i}" for i in range(1, 13)} or len(
            self.stores
        ) != 12:
            raise ValueError("Configure each of the 12 city establishments exactly once")
        if not any(s.enabled for s in self.stores):
            raise ValueError("Enable at least one establishment")
        if sum(s.couriers for s in self.stores if s.enabled) > 16:
            raise ValueError("Local experiments support at most 16 couriers")
        return self


def demand_schedule(config: CitySettings, stock: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rng = random.Random(config.seed)
    stores = [
        s
        for s in config.stores
        if s.enabled and s.demand_weight > 0 and any(row["store"] == s.id for row in stock)
    ]
    if config.orders_per_hour == 0 or not stores:
        return []
    result: list[dict[str, Any]] = []
    instant = rng.expovariate(config.orders_per_hour / 3600)
    while instant < config.duration_minutes * 60 and len(result) < 24:
        store = rng.choices(stores, weights=[s.demand_weight for s in stores], k=1)[0]
        products = sorted(row["sku"] for row in stock if row["store"] == store.id)
        result.append(
            {
                "basket": f"order-{len(result) + 1:03d}",
                "store": store.id,
                "sku": rng.choice(products),
                "quantity": 1,
                "arrival_sim": int(instant),
                "customer_node": rng.randrange(1024),
                "deadline_sim": int(instant) + 7200,
            }
        )
        instant += rng.expovariate(config.orders_per_hour / 3600)
    return result


def dropout_schedule(config: CitySettings, fleet: list[dict[str, Any]]) -> dict[str, int]:
    if config.dropout_rate == 0:
        return {}
    rng = random.Random(config.seed + 9107)
    return {
        c["id"]: int(rng.expovariate(config.dropout_rate / 3600))
        for c in sorted(fleet, key=lambda row: row["id"])
    }

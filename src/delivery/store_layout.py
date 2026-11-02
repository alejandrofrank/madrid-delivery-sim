"""Small deterministic dark-store layouts in metres, independent of any renderer."""

from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StoreLayoutConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    aisles: int = Field(default=4, ge=2, le=8)
    bays: int = Field(default=8, ge=2, le=12)
    levels: int = Field(default=3, ge=1, le=4)
    picker_count: int = Field(default=2, ge=1, le=8)
    picker_kind: Literal["robot", "staff"] = "robot"
    speed_mps: float = Field(default=1, ge=0.2, le=2)
    pick_seconds: int = Field(default=10, ge=1, le=120)
    pack_seconds: int = Field(default=20, ge=1, le=300)


class StoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = True
    layout: StoreLayoutConfig = Field(default_factory=StoreLayoutConfig)
    opening_units: int = Field(default=24, ge=1, le=1000)
    products_per_order: int = Field(default=3, ge=1, le=8)
    # IDs are selected from real Madrid pickup locations when omitted.
    stores: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def unique_stores(self) -> "StoreConfig":
        if len(set(self.stores)) != len(self.stores):
            raise ValueError("Store IDs must be unique")
        return self


def node(x: int, z: int) -> str:
    return f"{x}:{z}"


def generate_layout(config: StoreLayoutConfig, products: list[dict[str, Any]]) -> dict[str, Any]:
    """Two pick faces per SKU, stable under input ordering and stock changes.

    Shelves occupy solid cells. Both cross aisles remain clear, and the cold
    zone is the last rack. Quantities come from the inventory ledger separately.
    """
    if not products or len({p["sku"] for p in products}) != len(products):
        raise ValueError("Unique nonempty product identities required")
    width, depth = config.aisles * 3 + 3, config.bays * 2 + 4
    shelves = []
    for aisle in range(config.aisles):
        for bay in range(config.bays):
            for side in (-1, 1):
                for level in range(config.levels):
                    shelves.append(
                        {
                            "id": f"a{aisle + 1}-b{bay + 1}-s{side + 1}-l{level + 1}",
                            "aisle": f"aisle-{aisle + 1}",
                            "bay": bay + 1,
                            "level": level + 1,
                            "x": aisle * 3 + 2,
                            "z": bay * 2 + 2,
                            "y": 0.45 + level * 0.6,
                            "side": side,
                            "access": node(aisle * 3 + 2 + side, bay * 2 + 2),
                            "zone": "cold" if aisle == config.aisles - 1 else "ambient",
                        }
                    )
    products = sorted(products, key=lambda p: p["sku"])
    available = {zone: [s for s in shelves if s["zone"] == zone] for zone in ("ambient", "cold")}
    assigned = []
    for product in products:
        zone = "cold" if product.get("cold", False) else "ambient"
        candidates = available[zone]
        if len(candidates) < 2:
            raise ValueError(f"Insufficient {zone} shelf capacity for catalogue")
        # Opposite ends provide real alternatives when an aisle is obstructed.
        for slot in (candidates.pop(0), candidates.pop(-1)):
            assigned.append(
                {
                    **slot,
                    "sku": product["sku"],
                    "name": product["name"],
                    "category": product.get("category", "packaged"),
                }
            )
    occupied = {(a * 3 + 2, z) for a in range(config.aisles) for z in range(2, config.bays * 2 + 1)}
    nodes = {
        node(x, z): [x, z] for x in range(width) for z in range(depth) if (x, z) not in occupied
    }
    return {
        "version": 1,
        "units": "metres",
        "width": width,
        "depth": depth,
        "config": config.model_dump(),
        "slots": assigned,
        "nodes": nodes,
        "aisles": [
            {"id": f"aisle-{a + 1}", "x": a * 3 + 1, "z": depth // 2} for a in range(config.aisles)
        ],
        "packing": {"x": 1, "z": depth - 2, "node": node(1, depth - 2)},
        "dock": {"x": width - 2, "z": depth - 2, "node": node(width - 2, depth - 2)},
        "cold_zone": {"x": (config.aisles - 1) * 3, "z": 1, "width": 4, "depth": depth - 4},
    }


def stock_to_shelves(layout: dict[str, Any], stock: dict[str, int]) -> list[dict[str, Any]]:
    """Lossless mapping; a listing or expected truck never implies physical stock."""
    known = {s["sku"] for s in layout["slots"]}
    if set(stock) != known or any(type(q) is not int or q < 0 for q in stock.values()):
        raise ValueError("Stock must contain every mapped SKU with nonnegative whole units")
    rows: list[dict[str, Any]] = []
    for sku in sorted(stock):
        slots = sorted((s for s in layout["slots"] if s["sku"] == sku), key=lambda s: s["id"])
        quantity, extra = divmod(stock[sku], len(slots))
        rows.extend({**s, "quantity": quantity + (i < extra)} for i, s in enumerate(slots))
    return rows


def aisle_path(
    layout: dict[str, Any], start: str, end: str, blocked: frozenset[str] = frozenset()
) -> list[str] | None:
    """Deterministic shortest walking path, never through racks or blocked cells."""
    nodes = layout["nodes"]
    if start not in nodes or end not in nodes or end in blocked:
        return None
    pending = deque([start])
    parent: dict[str, str | None] = {start: None}
    while pending:
        current = pending.popleft()
        if current == end:
            result = []
            cursor: str | None = end
            while cursor is not None:
                result.append(cursor)
                cursor = parent[cursor]
            return result[::-1]
        x, z = nodes[current]
        for nxt in sorted((node(x - 1, z), node(x + 1, z), node(x, z - 1), node(x, z + 1))):
            if nxt in nodes and nxt not in blocked and nxt not in parent:
                parent[nxt] = current
                pending.append(nxt)
    return None


def plan_pick(
    layout: dict[str, Any],
    start: str,
    remaining: dict[str, int],
    shelves: list[dict[str, Any]],
    blocked: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Fulfillment's deterministic policy: reachable ambient goods, then cold goods.

    Choose using observed shelf quantities and actual path length. No branch
    mentions a disruption name. Missing stock or paths produce a bounded wait.
    """
    choices = []
    slot_by_id = {s["id"]: s for s in layout["slots"]}
    for shelf in shelves:
        if remaining.get(shelf["sku"], 0) <= 0 or shelf["quantity"] <= 0:
            continue
        slot = slot_by_id[shelf["slot"]]
        path = aisle_path(layout, start, slot["access"], blocked)
        if path:
            choices.append((slot["zone"] == "cold", len(path), shelf["slot"], path, shelf))
    if not choices:
        return {"action": "wait", "reason": "No reachable shelf with the remaining stock"}
    _, _, slot_id, path, shelf = min(choices)
    return {
        "action": "pick",
        "slot": slot_id,
        "sku": shelf["sku"],
        "path": path,
        "quantity": min(remaining[shelf["sku"]], shelf["quantity"]),
        "reason": "Shortest reachable pick face; cold goods last",
    }

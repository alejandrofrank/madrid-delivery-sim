"""Small fictional city in local metre coordinates, unrelated to real geography."""

import random
from typing import Any

from delivery.catalogue import digest


def fake_city(seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed)
    nodes = [{"id": y * 4 + x, "x": x * 500, "y": y * 500} for y in range(4) for x in range(4)]
    edges = []
    for node in nodes:
        for target in nodes:
            if abs(node["x"] - target["x"]) + abs(node["y"] - target["y"]) == 500:
                edges.append(
                    {
                        "from": node["id"],
                        "to": target["id"],
                        "distance_m": 500,
                        "travel_seconds": rng.randint(50, 90),
                        "modes": ["bike", "moto", "car", "van"],
                    }
                )
    stores = [
        {
            "id": f"store-{i + 1}",
            "name": name,
            "node": node,
            "kind": "supermarket" if i < 3 else "retail",
        }
        for i, (name, node) in enumerate(
            [
                ("North Market", 0),
                ("Bridge Market", 6),
                ("South Market", 15),
                ("Home Goods", 3),
                ("Electronics", 12),
            ]
        )
    ]
    city = {
        "schema_version": 1,
        "seed": seed,
        "coordinate_system": "fictional metres",
        "nodes": nodes,
        "edges": edges,
        "stores": stores,
        "facilities": [
            {"kind": "depot", "node": 5},
            {"kind": "supplier", "node": 10},
            {"kind": "fuel", "node": 9},
            {"kind": "charger", "node": 7},
        ],
    }
    return {**city, "sha256": digest(city)}

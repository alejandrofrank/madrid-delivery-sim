"""Fictional grid city in local metre coordinates, unrelated to real geography."""

import random
from typing import Any

from delivery.catalogue import digest


def fake_city(seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed)
    width, height, spacing_m = 10, 10, 500
    nodes = [
        {"id": y * width + x, "x": x * spacing_m, "y": y * spacing_m}
        for y in range(height)
        for x in range(width)
    ]
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
                ("North Market", 2),
                ("Bridge Market", 45),
                ("South Market", 97),
                ("Home Goods", 19),
                ("Electronics", 80),
            ]
        )
    ]
    city = {
        "schema_version": 2,
        "width": width,
        "height": height,
        "spacing_m": spacing_m,
        "seed": seed,
        "coordinate_system": "fictional metres",
        "nodes": nodes,
        "edges": edges,
        "stores": stores,
        "facilities": [
            {"kind": "depot", "node": 22},
            {"kind": "supplier", "node": 77},
            {"kind": "fuel", "node": 51},
            {"kind": "charger", "node": 38},
        ],
    }
    return {**city, "sha256": digest(city)}

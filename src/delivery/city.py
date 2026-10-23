"""Fictional grid city in local metre coordinates, unrelated to real geography."""

import random
from typing import Any

from delivery.catalogue import digest


def fake_city(seed: int = 42, size: int = 10) -> dict[str, Any]:
    """Build a connected grid in linear time; the default retains the legacy fixture."""
    if size not in (10, 32):
        raise ValueError("Fictional city size must be 10 or 32")
    rng = random.Random(seed)
    width, height, spacing_m = size, size, 500
    nodes = [
        {"id": y * width + x, "x": x * spacing_m, "y": y * spacing_m}
        for y in range(height)
        for x in range(width)
    ]
    edges = []
    for node in nodes:
        x, y = node["id"] % width, node["id"] // width
        # Sorted IDs preserve the legacy random draw order without scanning all nodes.
        adjacent = sorted(
            ny * width + nx
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if 0 <= nx < width and 0 <= ny < height
        )
        for target_id in adjacent:
            edges.append(
                {
                    "from": node["id"],
                    "to": target_id,
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
    if size == 32:
        stores = [
            {"id": f"store-{i + 1}", "name": name, "node": y * width + x, "kind": kind}
            for i, (name, x, y, kind) in enumerate(
                [
                    ("North Market", 3, 3, "supermarket"),
                    ("Bridge Market", 15, 8, "supermarket"),
                    ("South Market", 28, 28, "supermarket"),
                    ("West Market", 3, 19, "supermarket"),
                    ("Central Market", 17, 18, "supermarket"),
                    ("East Market", 28, 12, "supermarket"),
                    ("Home Goods", 8, 5, "retail"),
                    ("Electronics", 24, 23, "retail"),
                    ("Everyday Supplies", 9, 27, "retail"),
                    ("North Hygiene Shop", 24, 4, "pharmacy"),
                    ("Central Hygiene Shop", 10, 16, "pharmacy"),
                    ("South Hygiene Shop", 20, 29, "pharmacy"),
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
    if size == 32:
        city["facilities"] = [
            {"kind": "depot", "node": 16 * width + 16},
            {"kind": "supplier", "node": 30 * width + 2},
            {"kind": "fuel", "node": 15 * width + 28},
            {"kind": "charger", "node": 5 * width + 15},
        ]
    return {**city, "sha256": digest(city)}

"""Deterministic fictional urban detail layered onto the large grid fixture."""

import random
from copy import deepcopy
from typing import Any

from delivery.catalogue import digest


def urban_city(city: dict[str, Any]) -> dict[str, Any]:
    """Preserve physical anchors while adding directed streets and residences."""
    if city.get("width") != 32 or city.get("height") != 32:
        raise ValueError("Urban detail requires the 32 by 32 city")
    result = deepcopy(city)
    width = 32
    spacing = int(city["spacing_m"])
    rng = random.Random(city["seed"])
    edges = []
    for edge in result["edges"]:
        source, target = edge["from"], edge["to"]
        sx, sy = source % width, source // width
        tx, ty = target % width, target // width
        horizontal = sy == ty
        index = sy if horizontal else sx
        perimeter = index in (0, width - 1)
        forward = tx > sx if horizontal else ty < sy
        allowed = perimeter or forward == (index % 2 == 0)
        if not allowed:
            continue
        edge["road_name"] = (
            f"{['Aster', 'Birch', 'Cedar', 'Dahlia'][index % 4]} "
            f"{'Avenue' if horizontal else 'Street'} {index + 1:02d}"
        )
        edge["road_kind"] = "avenue" if perimeter or index % 4 == 0 else "street"
        edge["direction"] = "bidirectional" if perimeter else "one_way"
        edges.append(edge)
    result["edges"] = edges
    result["neighborhoods"] = [
        {
            "id": f"neighborhood-{row * 3 + column + 1}",
            "name": (
                f"{['North', 'Central', 'South'][row]} {['Gardens', 'Commons', 'Quarter'][column]}"
            ),
            "x": column * 5000,
            "y": row * 5000,
            "width": 5500 if column == 2 else 5000,
            "height": 5500 if row == 2 else 5000,
        }
        for row in range(3)
        for column in range(3)
    ]
    anchors = {item["node"] for item in result["stores"] + result["facilities"]}
    # Southeast building offsets leave both intersecting roads clear. Last row and
    # column have no southeast block, so residences use interior block corners.
    candidates = [
        y * width + x for y in range(31) for x in range(31) if y * width + x not in anchors
    ]
    rng.shuffle(candidates)
    buildings = []
    customers = []
    for index, node in enumerate(candidates[:168]):
        residential = index < 128
        kind = (
            ("apartment" if index % 3 == 0 else "home")
            if residential
            else ("park" if index < 144 else "office")
        )
        road = (
            f"{['Aster', 'Birch', 'Cedar', 'Dahlia'][(node // width) % 4]} "
            f"Avenue {node // width + 1:02d}"
        )
        address = f"{index + 1} {road}"
        building_id = f"building-{index + 1:03d}"
        extent = 130 if kind == "apartment" else 100
        buildings.append(
            {
                "id": building_id,
                "kind": kind,
                "node": node,
                "x": node % width * spacing + rng.randint(80, 200),
                "y": node // width * spacing + rng.randint(80, 200),
                "width": extent,
                "height": extent,
                "address": address,
            }
        )
        if residential:
            customers.append(
                {
                    "id": f"customer-{index + 1:03d}",
                    "name": f"Aster Household {index + 1:03d}",
                    "home_id": building_id,
                    "home_node": node,
                    "address": address,
                }
            )
    result["buildings"] = buildings
    result["customers"] = customers
    result.pop("sha256", None)
    result["sha256"] = digest(result)
    return result

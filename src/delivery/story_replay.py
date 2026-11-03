"""Build a small, static, factual view of a reviewed city recording.

The output is presentation-independent: integer map coordinates, recorded route
times and snapshots, plus source-linked outcomes. No model, network or live run.
"""

import gzip
import json
import math
from pathlib import Path
from typing import Any

from delivery.replay import Recordings

SCHEMA_VERSION = 1
MAP_UNITS = 8192
ROAD_TOLERANCE = 3
MAX_JSON_BYTES = 900_000
MAX_GZIP_BYTES = 220_000
MOVING_STATUSES = ("to_pickup", "delivering", "repositioning")
STATUSES = ("idle", "to_pickup", "delivering", "repositioning", "offline", "off_shift")


def encode_story_replay(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                       sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def check_size(raw: bytes) -> None:
    if len(raw) > MAX_JSON_BYTES or len(gzip.compress(raw, mtime=0)) > MAX_GZIP_BYTES:
        raise ValueError("Story recording exceeds its static download budget")



def simplify_road(vertices: list[tuple[int, ...]]) -> tuple[tuple[int, ...], ...]:
    """Remove visually redundant road vertices, preserving corners and endpoints."""
    keep = {0, len(vertices) - 1}
    segments = [(0, len(vertices) - 1)]
    while segments:
        first, last = segments.pop()
        a, b = vertices[first], vertices[last]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_squared = dx * dx + dy * dy
        furthest, distance_squared = first, 0.0
        for index in range(first + 1, last):
            p = vertices[index]
            fraction = (max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy)
                                    / length_squared)) if length_squared else 0.0)
            distance = (p[0] - a[0] - fraction * dx) ** 2 + (p[1] - a[1] - fraction * dy) ** 2
            if distance > distance_squared:
                furthest, distance_squared = index, distance
        if distance_squared > ROAD_TOLERANCE ** 2:
            keep.add(furthest)
            segments.extend(((first, furthest), (furthest, last)))
    return tuple(vertices[index] for index in sorted(keep))


def build_story_replay(directory: Path, run: str | None = None) -> dict[str, Any]:
    recordings = Recordings(directory)
    shift = recordings.shift(run)
    frames = shift["frames"]
    final = frames[-1]
    run_id = final["run"]["id"]
    locations = sorted(shift["world"]["locations"], key=lambda item: item["id"])
    lines = [feature["geometry"]["coordinates"] for feature in shift["roads"]["features"]
             if feature["geometry"]["type"] == "LineString"]
    coordinates = [point[:2] for line in lines for point in line]
    coordinates.extend([item["lon"], item["lat"]] for item in locations)
    for frame in frames:
        for courier in frame["couriers"]:
            coordinates.append([courier["lon"], courier["lat"]])
            route = courier.get("route") or courier.get("reposition_route")
            if route:
                coordinates.extend(point[:2] for point in route["points"])
    if not coordinates or not all(math.isfinite(n) for point in coordinates for n in point):
        raise ValueError("Recording needs finite map coordinates")
    west, south = (min(point[i] for point in coordinates) for i in (0, 1))
    east, north = (max(point[i] for point in coordinates) for i in (0, 1))
    if east <= west or north <= south:
        raise ValueError("Recording needs a two-dimensional map extent")

    def point(lon: float, lat: float) -> list[int]:
        return [round((lon - west) / (east - west) * MAP_UNITS),
                round((north - lat) / (north - south) * MAP_UNITS)]

    # Undirected streets are often present twice. Retain all street geometry,
    # simplifying redundant bends by at most three map units (under four metres
    # for the shipped Madrid extent). Courier routes are not simplified.
    roads: set[tuple[tuple[int, ...], ...]] = set()
    for line in lines:
        vertices: list[tuple[int, ...]] = []
        for lon, lat in line:
            vertex = tuple(point(lon, lat))
            if not vertices or vertex != vertices[-1]:
                vertices.append(vertex)
        if len(vertices) > 1:
            simplified = simplify_road(vertices)
            roads.add(min(simplified, tuple(reversed(simplified))))

    courier_ids = sorted(courier["id"] for courier in final["couriers"])
    courier_index = {identifier: index for index, identifier in enumerate(courier_ids)}
    couriers_by_id = {courier["id"]: courier for courier in final["couriers"]}
    routes: list[list[list[int | float]]] = []
    route_index: dict[str, int] = {}
    snapshots: list[dict[str, Any]] = []
    for frame in frames:
        couriers = {courier["id"]: courier for courier in frame["couriers"]}
        if set(couriers) != set(courier_ids):
            raise ValueError("Story recording requires a stable courier roster")
        states = []
        for identifier in courier_ids:
            courier = couriers[identifier]
            status = courier["status"]
            if status not in STATUSES:
                raise ValueError(f"Unsupported recorded courier status: {status}")
            route = courier.get("route") or courier.get("reposition_route")
            reference = -1
            if route and status in MOVING_STATUSES:
                # Keep waiting vertices and sub-second timings. Removing either
                # would invent motion while a courier waits at a kitchen.
                path = [[*point(lon, lat), round(time, 3)] for lon, lat, time in route["points"]]
                times = [vertex[2] for vertex in path]
                if not times or times != sorted(times):
                    raise ValueError("Recorded route times must be nondecreasing")
                key = json.dumps(path, separators=(",", ":"), allow_nan=False)
                if key not in route_index:
                    route_index[key] = len(routes)
                    routes.append(path)
                reference = route_index[key]
            states.append([*point(courier["lon"], courier["lat"]),
                           STATUSES.index(status), reference])
        snapshots.append({"time": frame["run"]["sim_time"], "couriers": states})

    sites = [{key: item[key] for key in ("id", "kind", "name", "district")} |
             {"point": point(item["lon"], item["lat"])}
             for item in locations if item["kind"] in {"store", "hub"}]
    site_index = {site["id"]: index for index, site in enumerate(sites)}
    # Store names are not unique in Madrid. Use the recorded pickup decision's
    # actual store ID, never a name match or nearest-site guess.
    pickups: dict[str, dict[str, Any]] = {}
    orders: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for order in frame["orders"]:
            orders[order["id"]] = order
        for decision in frame.get("decisions", []):
            if decision["action"] == "picked_up":
                pickups[decision["order_id"]] = decision
    order_rows = []
    for order in sorted(orders.values(), key=lambda row: (row["created_sim"], row["id"])):
        pickup = pickups.get(order["id"])
        site = site_index.get(pickup["detail"].get("store")) if pickup else None
        order_rows.append({
            "created": order["created_sim"], "delivered": order.get("delivered_sim"),
            "due": order["due_sim"], "site": site,
            "picked_up": pickup["sim_time"] if pickup else None,
            "courier": courier_index.get(order.get("courier")),
            "destination": point(order["lon"], order["lat"]),
        })

    metrics = final["metrics"]
    chaos = final["chaos"]
    by_event = {row["id"]: row for row in chaos["metrics"]}
    disruptions = []
    for event in sorted(chaos["events"], key=lambda row: (row["start_sim"], row["id"])):
        recovery = by_event.get(event["id"], {})
        recovered = (event["state"] == "ended"
                     and recovery.get("time_to_recover_seconds") is not None
                     and recovery.get("unresolved_orders") == 0
                     and recovery.get("orders_lost") == 0)
        disruptions.append({
            **{key: event.get(key) for key in ("id", "kind", "district", "start_sim", "end_sim")},
            "recovered": recovered, "metrics": recovery,
        })

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            **recordings.sources[run_id], "run": run_id, "seed": shift["seed"],
            "kind": shift["source"], "title": shift["title"],
            "created_at": final["run"]["created_at"], "paid_model_calls": shift["paid_calls"],
            "description": "Recorded offline simulation; not live model activity.",
        },
        "clock": {"duration": final["run"]["duration"], "playback_seconds": 60},
        "map": {
            "bounds": [west, south, east, north], "units": MAP_UNITS,
            "coordinate_order": "x eastward, y southward",
            "road_tolerance_units": ROAD_TOLERANCE,
            "aspect_ratio": (east - west) * math.cos(math.radians((north + south) / 2))
                            / (north - south),
            "attribution": {"label": "© OpenStreetMap contributors",
                            "url": "https://www.openstreetmap.org/copyright"},
            "roads": sorted(roads), "sites": sites,
        },
        "couriers": [
            {"id": identifier, "mode": couriers_by_id[identifier]["mode"],
             "fleet": couriers_by_id[identifier]["fleet_name"]}
            for identifier in courier_ids
        ],
        "statuses": STATUSES, "routes": routes, "frames": snapshots, "orders": order_rows,
        "disruptions": disruptions,
        "outcomes": {
            "orders": metrics["orders"], "delivered": metrics["delivered"],
            "on_time": metrics["on_time"], "on_time_percent": metrics["on_time_pct"],
            "resolved_disruptions": sum(event["recovered"] for event in disruptions),
            "disruptions": len(disruptions),
            "cost_per_delivery_eur": metrics["cost_per_delivery_eur"],
            "cost_basis": metrics["cost_basis"],
            "cost_description": "Estimated fleet operating cost",
            "cohort_note": "An order can be affected by several disruptions; do not add cohorts.",
        },
    }
    check_size(encode_story_replay(payload))
    return payload

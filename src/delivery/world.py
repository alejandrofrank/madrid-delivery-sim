"""Real OSM graph ingestion, deterministic seed data, and road-constrained routing."""

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import osmnx as ox
from psycopg.types.json import Jsonb

from delivery.db import Connection
from delivery.telemetry import trace_fields

DATA = Path("data")
BBOX = (-3.730, 40.375, -3.640, 40.455)  # west, south, east, north
HUBS = [
    ("chamberi", "Chamberí", 40.4365, -3.7038),
    ("retiro", "Retiro", 40.4085, -3.6764),
    ("vallecas", "Puente de Vallecas", 40.3915, -3.6657),
]
SPEED_MPS = {"bike": 4.5, "moto": 7.0, "van": 5.5}
ENERGY_PER_KM = {"bike": 1.5, "moto": 0.7, "van": 0.4}
COST_PER_KM = {"bike": 0.12, "moto": 0.28, "van": 0.55}
MOTOR_ONLY = {"motorway", "motorway_link", "trunk", "trunk_link"}


def download() -> None:
    DATA.mkdir(exist_ok=True)
    ox.settings.cache_folder = str(DATA / "cache")
    ox.settings.requests_timeout = 120
    graph = ox.graph_from_bbox(BBOX, network_type="drive", retain_all=False)
    # Shared M1 fleet graph: directed drivable streets, excluding motor-only roads.
    # Bikes obey the same one-way rules. Mode-specific access is a later extension.
    remove = []
    for u, v, k, d in graph.edges(keys=True, data=True):
        roads = d.get("highway", [])
        if isinstance(roads, str):
            roads = [roads]
        if MOTOR_ONLY.intersection(roads):
            remove.append((u, v, k))
    graph.remove_edges_from(remove)
    graph = graph.subgraph(max(nx.strongly_connected_components(graph), key=len)).copy()
    ox.save_graphml(graph, DATA / "madrid.graphml.gz")
    features = ox.features_from_bbox(BBOX, {"shop": "supermarket", "amenity": "restaurant"})
    stores: list[dict[str, Any]] = []
    for idx, row in features.iterrows():
        if not isinstance(row.get("name"), str):
            continue
        point = row.geometry.representative_point()
        stores.append(
            {"osm_id": f"{idx[0]}/{idx[1]}", "name": row["name"], "lat": point.y, "lon": point.x}
        )
    stores.sort(key=lambda s: s["osm_id"])
    (DATA / "stores.json").write_text(json.dumps(stores, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "source": "OpenStreetMap contributors via OSMnx / Overpass",
        "license": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "source_url": "https://www.openstreetmap.org/copyright",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "bbox_wsen": BBOX,
        "network": "drive, motor-only edges removed, largest strongly connected component",
        "nodes": len(graph),
        "edges": graph.number_of_edges(),
        "stores": len(stores),
        "sha256": hashlib.sha256((DATA / "madrid.graphml.gz").read_bytes()).hexdigest(),
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


class World:
    def __init__(self, graph: nx.MultiDiGraph | None = None) -> None:
        if graph is None:
            path = DATA / "madrid.graphml.gz"
            if not path.exists():
                raise FileNotFoundError(
                    "OSM graph missing. Run python -m delivery.world --download"
                )
            graph = ox.load_graphml(path)
        self.graph = graph
        self.nodes = sorted(graph.nodes)
        self.xy = np.array([[graph.nodes[n]["x"], graph.nodes[n]["y"]] for n in self.nodes])
        self.simple: nx.DiGraph = nx.DiGraph()
        for u, v, d in graph.edges(data=True):
            if not self.simple.has_edge(u, v) or d["length"] < self.simple[u][v]["length"]:
                self.simple.add_edge(u, v, **d)
        self.path = lru_cache(maxsize=8192)(self._path)

    def nearest(self, lon: float, lat: float) -> int:
        delta = (self.xy - [lon, lat]) * [math.cos(math.radians(lat)), 1]
        return int(self.nodes[int(np.argmin(np.sum(delta * delta, axis=1)))])

    def coord(self, node: int) -> list[float]:
        return [float(self.graph.nodes[node]["x"]), float(self.graph.nodes[node]["y"])]

    def _path(self, start: int, end: int) -> tuple[list[list[float]], float]:
        nodes = nx.shortest_path(self.simple, start, end, weight="length")
        coords = [self.coord(start)]
        distance = 0.0
        for u, v in zip(nodes, nodes[1:], strict=False):
            edge = self.simple[u][v]
            distance += float(edge["length"])
            geom = edge.get("geometry")
            points = [list(p) for p in geom.coords] if geom else [self.coord(u), self.coord(v)]
            if math.dist(points[0], self.coord(u)) > math.dist(points[-1], self.coord(u)):
                points.reverse()
            coords.extend(points[1:])
        return coords, distance

    def route(
        self, start: int, store: int, customer: int, mode: str, sim_time: int, ready_sim: int
    ) -> dict[str, Any]:
        pickup, pickup_m = self.path(start, store)
        delivery, delivery_m = self.path(store, customer)
        speed = SPEED_MPS[mode]
        arrival = pickup_m / speed
        pickup_at = max(arrival, ready_sim - sim_time) + 60
        end_at = pickup_at + delivery_m / speed + 45
        # Timestamps follow polyline geometry, scaled to OSM edge lengths.
        points: list[list[float]] = []
        for coords, offset, duration in (
            (pickup, 0, arrival),
            (delivery, pickup_at, delivery_m / speed),
        ):
            lengths = [0.0]
            for a, b in zip(coords, coords[1:], strict=False):
                lengths.append(
                    lengths[-1] + math.hypot((a[0] - b[0]) * 85000, (a[1] - b[1]) * 111000)
                )
            total = lengths[-1] or 1
            points.extend(
                [
                    [p[0], p[1], sim_time + offset + duration * d / total]
                    for p, d in zip(coords, lengths, strict=True)
                ]
            )
        points.append([*self.coord(customer), sim_time + end_at])
        return {
            "points": points,
            "distance_m": pickup_m + delivery_m,
            "pickup_at": sim_time + pickup_at,
            "end_at": sim_time + math.ceil(end_at),
            "destination": customer,
            "start_node": start,
            "pickup_node": store,
            "start_at": sim_time,
            "pickup_arrival_at": sim_time + arrival,
            "delivery_arrival_at": sim_time + end_at - 45,
            "pickup_distance_m": pickup_m,
            "delivery_distance_m": delivery_m,
            "pickup_travel_seconds": arrival,
            "pickup_wait_seconds": max(0, ready_sim - sim_time - arrival),
        }

    def relocation(self, start: int, destination: int, mode: str, sim: int) -> dict[str, Any]:
        """A real empty trip; reuse the same directed road geometry and speed."""
        route = self.route(start, destination, destination, mode, sim, sim)
        route["points"] = [p for p in route["points"] if p[2] <= route["pickup_arrival_at"]]
        route["end_at"] = sim + math.ceil(route["pickup_travel_seconds"])
        route["points"].append([*self.coord(destination), route["end_at"]])
        route["pickup_at"] = route["end_at"]
        route["delivery_arrival_at"] = route["end_at"]
        return route

    def roads(self) -> dict[str, Any]:
        features = []
        seen: set[tuple[int, int]] = set()
        for u, v, d in self.graph.edges(data=True):
            pair = tuple(sorted((u, v)))
            if pair in seen:
                continue
            seen.add(pair)
            geometry = d.get("geometry")
            coords = list(geometry.coords) if geometry else [self.coord(u), self.coord(v)]
            features.append(
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )
        return {"type": "FeatureCollection", "features": features}


def position(route: dict[str, Any], sim_time: float) -> list[float]:
    points = route["points"]
    if sim_time <= points[0][2]:
        return list(points[0][:2])
    for a, b in zip(points, points[1:], strict=False):
        if sim_time <= b[2]:
            fraction = min(1.0, max(0.0, (sim_time - a[2]) / max(0.0001, b[2] - a[2])))
            return [a[i] + fraction * (b[i] - a[i]) for i in (0, 1)]
    return list(points[-1][:2])


def route_progress(route: dict[str, Any], sim: float) -> tuple[float, float]:
    """Cumulative actual metres (all, empty), including partial trips and waits."""

    def fraction(start: float, end: float) -> float:
        return min(1.0, max(0.0, (sim - start) / max(0.0001, end - start)))

    if "pickup_distance_m" not in route:  # historical routes had one combined ledger
        return route["distance_m"] * fraction(route["points"][0][2], route["end_at"]), 0
    empty = route["pickup_distance_m"] * fraction(route["start_at"], route["pickup_arrival_at"])
    loaded = route["delivery_distance_m"] * fraction(
        route["pickup_at"], route["delivery_arrival_at"]
    )
    return empty + loaded, empty


def seed_locations(conn: Connection, world: World) -> None:
    """Static shared city, idempotent; no fabricated shops or graph fallback."""
    stores = json.loads((DATA / "stores.json").read_text(encoding="utf-8"))
    locations = []
    selected: set[str] = set()
    for hub_id, district, lat, lon in HUBS:
        hub_node = world.nearest(lon, lat)
        locations.append((hub_id, "hub", f"{district} hub", district, hub_node, None))
        ranked = sorted(stores, key=lambda s: math.hypot(s["lon"] - lon, s["lat"] - lat))
        for store in [s for s in ranked if s["osm_id"] not in selected][:8]:
            selected.add(store["osm_id"])
            locations.append(
                (
                    f"store-{store['osm_id']}",
                    "store",
                    store["name"],
                    district,
                    world.nearest(store["lon"], store["lat"]),
                    store["osm_id"],
                )
            )
        nearby = sorted(world.nodes, key=lambda n: math.dist(world.coord(n), [lon, lat]))
        # Stable, distinct synthetic customers on actual street nodes in each district.
        for i, node in enumerate(nearby[20:620:10]):
            locations.append(
                (
                    f"customer-{hub_id}-{i:03d}",
                    "customer",
                    f"{district} customer {i + 1}",
                    district,
                    node,
                    None,
                )
            )
    for loc_id, kind, name, district, node, osm_id in locations:
        x, y = world.coord(node)
        conn.execute(
            """INSERT INTO locations(id,kind,name,district,node,point,osm_id)
               VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s)
               ON CONFLICT(id) DO NOTHING""",
            (loc_id, kind, name, district, node, x, y, osm_id),
        )


def trace(
    conn: Connection,
    run: str,
    sim: int,
    agent: str,
    action: str,
    detail: dict[str, Any],
    order: str | None = None,
    courier: str | None = None,
    event: int | None = None,
) -> None:
    if telemetry := trace_fields():
        detail = {**detail, "telemetry": telemetry}
    conn.execute(
        """INSERT INTO decisions(run_id,sim_time,agent,action,detail,order_id,courier_id,event_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (run, sim, agent, action, Jsonb(detail), order, courier, event),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", required=True)
    parser.parse_args()
    download()

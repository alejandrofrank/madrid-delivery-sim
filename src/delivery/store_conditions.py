"""Physical constraints projected from active store disruptions."""

from typing import Any

from delivery.db import Connection

STORE_KINDS = ("blocked_aisle", "shelf_out_of_stock", "robot_breakdown", "late_restock_truck")


def conditions(conn: Connection, run: str, store: str, layout: dict[str, Any]) -> dict[str, Any]:
    events = list(
        conn.execute(
            "SELECT id,kind,resource,end_sim FROM chaos_events WHERE run_id=%s "
            "AND target=%s AND state='active' AND kind=ANY(%s) ORDER BY id",
            (run, store, list(STORE_KINDS)),
        )
    )
    blocked: set[str] = set()
    broken: set[str] = set()
    unavailable: set[str] = set()
    for event in events:
        resource = event["resource"]
        if event["kind"] == "blocked_aisle":
            aisle = next(a for a in layout["aisles"] if a["id"] == resource)
            blocked.add(f"{aisle['x']}:{aisle['z']}")
        elif event["kind"] == "robot_breakdown":
            broken.add(resource)
        elif event["kind"] == "shelf_out_of_stock":
            unavailable.add(resource)
    return {
        "events": events,
        "blocked": sorted(blocked),
        "broken": sorted(broken),
        "unavailable_shelves": sorted(unavailable),
    }

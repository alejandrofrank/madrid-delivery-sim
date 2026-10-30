"""Read-only MCP access to public simulation facts; no operational capabilities."""

from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from delivery.db import connect


def create_mcp_server(url: str | None = None) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer("Madrid simulation data", version="1.0.0")
    read_only = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

    def query(sql: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
        with connect(url) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return list(conn.execute(sql, parameters).fetchall())

    @server.tool(annotations=read_only)
    def order_status(run_id: UUID, order_id: str) -> list[dict[str, Any]]:
        """Read one order's public status and measured delivery time."""
        return query(
            "SELECT id,status,courier,ready_sim,due_sim,delivered_sim "
            "FROM orders WHERE run_id=%s AND id=%s",
            (run_id, order_id),
        )

    @server.tool(annotations=read_only)
    def courier_positions(run_id: UUID) -> list[dict[str, Any]]:
        """Read courier positions, mode and availability in a run."""
        return query(
            "SELECT id,mode,status,fleet_id,ST_X(point) lon,ST_Y(point) lat "
            "FROM couriers WHERE run_id=%s ORDER BY id LIMIT 500",
            (run_id,),
        )

    @server.tool(annotations=read_only)
    def menus() -> dict[str, Any]:
        """Read public restaurant menus; no pantry, private memories or credentials."""
        from delivery.meal_snapshot import load_meal_snapshot
        from delivery.supply import blueprint

        config, _ = blueprint(url)
        return {
            "restaurants": [
                {"id": e.id, "name": e.name, "recipe_ids": e.recipe_ids}
                for e in config.entities
                if e.kind == "restaurant"
            ],
            "recipes": [r.model_dump(mode="json") for r in load_meal_snapshot().recipes],
        }

    @server.tool(annotations=read_only)
    def active_disruptions(run_id: UUID) -> list[dict[str, Any]]:
        """Read active disruptions and their affected districts in a run."""
        if not query("SELECT to_regclass('public.chaos_events') AS name", ())[0]["name"]:
            return []
        return query(
            "SELECT id,kind,district,target,start_sim,end_sim,severity "
            "FROM chaos_events WHERE run_id=%s AND state='active' ORDER BY id",
            (run_id,),
        )

    return server


if __name__ == "__main__":
    create_mcp_server().run(transport="stdio")

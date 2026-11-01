"""Madrid's existing physical tick behind the shared environment contract."""

from typing import Any

from delivery.agents import Courier
from delivery.chaos import observe, physical_tick
from delivery.db import Connection
from delivery.environment import RunEnvironment
from delivery.world import World


class MadridCity(RunEnvironment):
    name = "madrid_city"

    def __init__(self, world: World, courier: Courier | None = None) -> None:
        self.world = world
        self.courier = courier or Courier()

    def read(self, conn: Connection, run: str) -> dict[str, Any]:
        return {
            "environment": self.name,
            "sim_time": self.clock(conn, run),
            "orders": list(conn.execute(
                "SELECT id,store,customer,status,courier,ready_sim,route FROM orders "
                "WHERE run_id=%s ORDER BY id", (run,)
            ).fetchall()),
            "couriers": list(conn.execute(
                "SELECT id,node,status,ST_X(point) lon,ST_Y(point) lat FROM couriers "
                "WHERE run_id=%s ORDER BY id", (run,)
            ).fetchall()),
        }

    def advance(
        self, conn: Connection, run: str, sim: int, *,
        seed: int | None = None, duration: int | None = None,
    ) -> dict[str, Any]:
        # Keep the exact legacy ordering: clock, courier, disruption, demand, observation.
        # The scheduler holds the per-run lock around this whole transaction.
        from delivery.simulation import generate

        row = conn.execute(
            "SELECT seed,duration,sim_time,chaos_config,store_config FROM runs WHERE id=%s", (run,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown run")
        if sim < row["sim_time"]:
            raise ValueError("Environment clock cannot move backwards")
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (sim, run))
        self.courier.advance(conn, run, sim)
        chaos = row["chaos_config"] is not None
        if chaos:
            physical_tick(conn, run, sim)
        if not row.get("store_config") or sim % 60 == 0:
            generate(conn, run, sim, row["seed"] if seed is None else seed,
                     row["duration"] if duration is None else duration)
        if chaos:
            observe(conn, run, sim)
        return {"environment": self.name, "sim_time": sim, "chaos": chaos}

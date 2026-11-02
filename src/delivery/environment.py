"""Transactional physical worlds; agents decide, environments apply physical effects.

All implementations share the run clock and durable event log. A caller owns the
transaction so time, motion and emitted facts commit or roll back together.
"""

from typing import Any, Protocol, runtime_checkable

from delivery.db import Connection


@runtime_checkable
class Environment(Protocol):
    name: str

    def clock(self, conn: Connection, run: str) -> int: ...

    def events(self, conn: Connection, run: str, after: int = 0) -> list[dict[str, Any]]: ...

    def read(self, conn: Connection, run: str) -> dict[str, Any]: ...

    def advance(self, conn: Connection, run: str, sim: int) -> dict[str, Any]: ...


class RunEnvironment:
    """Read-only common clock/event boundary; never uses wall time for physics."""

    name = "run"

    def clock(self, conn: Connection, run: str) -> int:
        row = conn.execute("SELECT sim_time FROM runs WHERE id=%s", (run,)).fetchone()
        if row is None:
            raise ValueError("Unknown run")
        return int(row["sim_time"])

    def events(self, conn: Connection, run: str, after: int = 0) -> list[dict[str, Any]]:
        if after < 0:
            raise ValueError("Event cursor must be nonnegative")
        return list(conn.execute(
            "SELECT id,topic,payload,trace_id,due_sim,producer FROM events "
            "WHERE run_id=%s AND id>%s ORDER BY id LIMIT 500", (run, after)
        ).fetchall())

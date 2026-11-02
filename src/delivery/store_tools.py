"""Bounded tools for existing inventory/fulfillment roles in the dark-store service.

The trusted A2A worker owns the DB connection. Tool callers get an immutable
run/store/order scope; scope arguments and tools outside role.json are rejected.
Legacy lab workers retain their stronger per-login SQL boundary unchanged.
"""

import json
from types import SimpleNamespace
from typing import Any

from psycopg.types.json import Jsonb

from delivery import inventory
from delivery.agent_specs import load_role
from delivery.db import Connection
from delivery.queue import Event, publish
from delivery.telemetry import trace_span


class StoreTools:
    def __init__(self, conn: Connection, event: Event, role: str, order: dict[str, Any]) -> None:
        self._conn, self.event, self.order = conn, event, order
        self.run, self.store = str(event.run_id), order["store"]
        self.role = load_role(role)
        self.scope = SimpleNamespace(
            run=self.run, store=self.store, definition_hash=self.role.digest
        )
        clock = conn.execute("SELECT sim_time FROM runs WHERE id=%s", (self.run,)).fetchone()
        if clock is None:
            raise ValueError("Unknown store run")
        self.sim = int(clock["sim_time"])
        self.calls: list[str] = []
        self.limits = self.role.environment_limits.get("dark_store", self.role.limits)
        budget = conn.execute(
            "SELECT * FROM store_agent_budgets WHERE run_id=%s AND store=%s AND role=%s FOR UPDATE",
            (self.run, self.store, role),
        ).fetchone()
        if budget is None or budget["events"] >= self.limits.events_per_run:
            raise ValueError("Store agent event budget exhausted")
        if budget["tools"] + self.limits.tool_calls_per_event > self.limits.tool_calls_per_run:
            raise ValueError("Store agent tool budget exhausted")
        conn.execute(
            "UPDATE store_agent_budgets SET events=events+1 "
            "WHERE run_id=%s AND store=%s AND role=%s",
            (self.run, self.store, role),
        )

    def invoke(self, name: str, **args: Any) -> Any:
        granted = self.role.tool_profiles.get("dark_store", self.role.tools)
        if name not in granted or any(
            k in args for k in ("run", "run_id", "store", "owner", "namespace", "agent_id")
        ):
            raise PermissionError("Tool exceeds bound store authority")
        if len(self.calls) >= self.limits.tool_calls_per_event:
            raise ValueError("Store agent turn budget exhausted")
        self.calls.append(name)
        with trace_span(
            "agent.tool",
            attributes={
                "delivery.agent": self.role.name,
                "delivery.tool": name,
                "delivery.environment": "dark_store",
            },
        ):
            result = self._invoke(name, args)
        self._conn.execute(
            "UPDATE store_agent_budgets SET tools=tools+1 WHERE run_id=%s AND store=%s AND role=%s",
            (self.run, self.store, self.role.name),
        )
        return result

    def _invoke(self, name: str, args: dict[str, Any]) -> Any:
        conn, run, store = self._conn, self.run, self.store
        if name == "inventory.read":
            return list(
                conn.execute(
                    "SELECT sku,on_hand,reserved FROM lab_stock "
                    "WHERE run_id=%s AND store=%s ORDER BY sku",
                    (run, store),
                )
            )
        if name == "inventory.reserve":
            expected = reservation_key(self.order["order_id"], args["sku"])
            if args["basket"] != expected or args["sku"] not in self.order["lines"]:
                raise PermissionError("Reservation outside bound order")
            if args["quantity"] != self.order["lines"][args["sku"]]:
                raise PermissionError("Reservation quantity differs from order")
            return inventory.reserve(
                conn,
                run,
                expected,
                store,
                args["sku"],
                args["quantity"],
                self.sim,
                args["expires_sim"],
            )
        if name == "inventory.receive":
            shipment = conn.execute(
                "SELECT * FROM lab_shipments WHERE run_id=%s AND id=%s AND store=%s",
                (run, args["shipment"], store),
            ).fetchone()
            if shipment is None:
                raise PermissionError("Shipment outside bound store")
            changed = inventory.receive(conn, run, args["shipment"], self.sim)
            if changed:
                conn.execute(
                    "INSERT INTO store_shelves(run_id,store,slot,sku,quantity) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(run_id,store,slot) "
                    "DO UPDATE SET quantity=store_shelves.quantity+excluded.quantity",
                    (
                        run,
                        store,
                        "backstock:" + shipment["sku"],
                        shipment["sku"],
                        shipment["quantity"],
                    ),
                )
            return {"shipment": args["shipment"], "received": changed}
        if name.startswith("memory."):
            return self._memory(name, args)
        if name == "queue.publish":
            topic = args["topic"]
            if topic not in self.role.service_events.get("emits", self.role.emits):
                raise PermissionError("Event exceeds role manifest")
            return publish(
                conn,
                run_id=run,
                producer=self.role.name,
                topic=topic,
                payload=args["payload"],
                key=str(args["key"]),
                trace_id=self.order["order_id"],
                due_sim=args.get("due_sim", self.sim),
                parent_id=self.event.id,
                target_store=store,
            )
        from delivery.store_actions import execute

        return execute(self, name, args)

    def _memory(self, name: str, args: dict[str, Any]) -> Any:
        row = self._conn.execute(
            "SELECT memories FROM store_agent_budgets WHERE run_id=%s AND store=%s AND role=%s",
            (self.run, self.store, self.role.name),
        ).fetchone()
        assert row
        memories = [m for m in row["memories"] if m["expires_sim"] > self.sim]
        if name == "memory.read":
            return [m for m in memories if m["order"] == self.order["order_id"]]
        # Existing InventoryPolicy supplies a typed outcome; keep the same validator.
        from delivery.typed_memory import validate_fact

        body = validate_fact(
            args["kind"],
            args["body"],
            self.role.name,
            "basket.requested"
            if self.event.topic == "store.order.requested"
            else "shipment.received",
        )
        memories.append(
            {
                "order": self.order["order_id"],
                "kind": args["kind"],
                "body": body,
                "event": self.event.id,
                "observed_sim": self.sim,
                "expires_sim": self.sim + 3600,
            }
        )
        memories = memories[-self.limits.memory_entries :]
        while len(json.dumps(memories).encode()) > self.limits.memory_bytes:
            memories.pop(0)
        self._conn.execute(
            "UPDATE store_agent_budgets SET memories=%s WHERE run_id=%s AND store=%s AND role=%s",
            (Jsonb(memories), self.run, self.store, self.role.name),
        )
        return {"stored": True}


def reservation_key(order: str, sku: str) -> str:
    import hashlib

    return f"store:{order}:" + hashlib.sha256(sku.encode()).hexdigest()[:12]

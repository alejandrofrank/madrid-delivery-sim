"""Shared local worker: authenticated scope, fixed tools, private memory and budgets.

Policies receive tools and a typed event, never an operator connection or city snapshot.
There are deliberately no file, SQL, network, code-execution or direct-agent tools.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from delivery.agent_specs import RoleSpec
from delivery.db import Connection, connect
from delivery.inventory import receive, release, reserve
from delivery.queue import Event, Queue, publish


class BasketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    basket: str = Field(min_length=1, max_length=100)
    store: str = Field(pattern=r"^store-([1-9]|1[0-2])$")
    sku: str = Field(min_length=1, max_length=512)
    quantity: int = Field(gt=0)
    expires_sim: int = Field(ge=0)
    deliver: bool = False


class ShipmentDelay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    shipment: str = Field(min_length=1, max_length=100)
    expected_sim: int = Field(ge=0)


class ShipmentRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    shipment: str = Field(min_length=1, max_length=100)


class BasketRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    basket: str = Field(min_length=1, max_length=100)


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentScope:
    run: str
    store: str
    agent_id: str
    definition_hash: str


class ScopedTools:
    """A fixed capability registry; all scope comes from authenticated session_user."""

    def __init__(self, conn: Connection, scope: AgentScope, role: RoleSpec, event: Event) -> None:
        self.__conn = conn
        self.scope = scope
        self.role = role
        self.event = event
        self.calls: list[str] = []
        self.memory_writes: list[dict[str, Any]] = []
        self.cloud_endpoint: str | None = None
        self.cloud_dsn: str | None = None
        ticket = conn.execute(
            """SELECT b.slots FROM agent_event_budgets b JOIN events e
            ON e.id=b.event_id WHERE b.event_id=%s AND b.attempt=%s AND e.state='leased'
            AND e.lease_token=%s AND e.lease_until>clock_timestamp()""",
            (event.id, event.attempts, event.token),
        ).fetchone()
        if not ticket:
            raise BudgetExceeded("Active event lease and durable budget required")
        row = conn.execute("SELECT public.agent_clock() AS sim").fetchone()
        assert row
        self.sim = int(row["sim"])

    def invoke(self, name: str, **arguments: Any) -> Any:
        if name not in self.role.tools:
            raise PermissionError("Tool is not granted to this role")
        for key in ("run", "run_id", "store", "owner", "namespace", "agent_id"):
            if key in arguments:
                raise PermissionError("Tool scope is bound to authenticated identity")
        if len(self.calls) >= self.role.limits.tool_calls_per_event:
            raise BudgetExceeded("Per-event tool limit exhausted")
        registry: dict[str, Callable[..., Any]] = {
            "inventory.read": self._read,
            "inventory.reserve": self._reserve,
            "inventory.release": self._release,
            "inventory.delay": self._delay,
            "inventory.receive": self._receive,
            "memory.read": self._recall,
            "memory.write": self._remember,
            "queue.publish": self._publish,
            "fulfillment.read": self._workflow_read,
            "fulfillment.pick": self._workflow_pick,
            "dispatch.read": self._workflow_read,
            "dispatch.assign": self._workflow_assign,
            "dispatch.complete": self._workflow_complete,
            "dispatch.recover": self._recover,
            "dispatch.defer": self._defer,
            "courier.read": self._courier_read,
            "courier.accept": self._courier_accept,
            "judge.read": self._judge_read,
            "judge.review": self._judge_review,
            "supply.read": self._supply_read,
            "supply.command": self._supply_command,
        }
        if name not in registry:
            raise PermissionError("Unknown tool")
        consumed = self.__conn.execute(
            """UPDATE agent_event_budgets
            SET observed_tools=observed_tools+1 WHERE event_id=%s AND attempt=%s
            AND observed_tools<slots AND EXISTS (SELECT 1 FROM events e
                WHERE e.id=agent_event_budgets.event_id AND e.state='leased'
                AND e.lease_token=%s AND e.lease_until>clock_timestamp())
            RETURNING observed_tools""",
            (self.event.id, self.event.attempts, self.event.token),
        ).fetchone()
        if not consumed:
            raise BudgetExceeded("Reserved tool slots exhausted")
        self.calls.append(name)
        return registry[name](**arguments)

    def _json_command(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
        row = self.__conn.execute(query, parameters).fetchone()
        assert row
        return dict(row["data"])

    def _supply_read(self, order: str) -> dict[str, Any]:
        return self._json_command("SELECT public.supply_context(%s) AS data", (order,))

    def _supply_command(self) -> dict[str, Any]:
        return self._json_command(
            "SELECT public.supply_command(%s,%s,%s) AS data",
            (self.event.id, self.event.token, self.event.attempts),
        )

    def _recover(self, basket: str, attempt: int) -> dict[str, Any]:
        return self._json_command("SELECT dispatch_recover(%s,%s) AS data", (basket, attempt))

    def _defer(self, basket: str) -> dict[str, Any]:
        return self._json_command("SELECT dispatch_defer(%s) AS data", (basket,))

    def _courier_read(self, basket: str, attempt: int) -> dict[str, Any]:
        return self._json_command("SELECT courier_context(%s,%s) AS data", (basket, attempt))

    def _courier_accept(self, basket: str, attempt: int) -> dict[str, Any]:
        return self._json_command("SELECT courier_accept(%s,%s) AS data", (basket, attempt))

    def _judge_read(self, basket: str, attempt: int) -> dict[str, Any]:
        return self._json_command("SELECT judge_context(%s,%s) AS data", (basket, attempt))

    def _judge_review(
        self, basket: str, attempt: int, courier: str | None, route: list[int] | None
    ) -> dict[str, Any]:
        return self._json_command(
            "SELECT judge_review(%s,%s,%s,%s) AS data",
            (basket, attempt, courier, Jsonb(route) if route is not None else None),
        )

    def _workflow_read(self, basket: str) -> dict[str, Any]:
        row = self.__conn.execute(
            "SELECT public.workflow_context(%s) AS data", (basket,)
        ).fetchone()
        assert row
        return dict(row["data"])

    def _workflow_pick(self, basket: str) -> dict[str, Any]:
        row = self.__conn.execute(
            "SELECT public.fulfillment_pick(%s) AS data", (basket,)
        ).fetchone()
        assert row
        return dict(row["data"])

    def _workflow_assign(self, basket: str, courier: str, route: list[int]) -> dict[str, Any]:
        row = self.__conn.execute(
            "SELECT public.dispatch_assign(%s,%s,%s) AS data", (basket, courier, Jsonb(route))
        ).fetchone()
        assert row
        return dict(row["data"])

    def _workflow_complete(self, basket: str) -> dict[str, Any]:
        row = self.__conn.execute(
            "SELECT public.dispatch_complete(%s) AS data", (basket,)
        ).fetchone()
        assert row
        return dict(row["data"])

    def _read(self, sku: str | None = None) -> dict[str, Any]:
        stock = self.__conn.execute(
            """SELECT sku,on_hand,reserved,on_hand-reserved AS available_now,
            version FROM lab_stock WHERE run_id=%s AND store=%s AND (%s::text IS NULL OR sku=%s)
            ORDER BY sku""",
            (self.scope.run, self.scope.store, sku, sku),
        ).fetchall()
        row = self.__conn.execute("SELECT public.agent_catalogue() AS products").fetchone()
        assert row
        products = [
            p for p in row["products"] if sku is None or f"{p['source']}:{p['listing_id']}" == sku
        ]
        return {
            "as_of_sim": self.sim,
            "store": self.scope.store,
            "products": products,
            "stock": stock,
        }

    def _reserve(self, basket: str, sku: str, quantity: int, expires_sim: int) -> str:
        return reserve(
            self.__conn,
            self.scope.run,
            basket,
            self.scope.store,
            sku,
            quantity,
            self.sim,
            expires_sim,
        )

    def _release(self, basket: str) -> str:
        return release(self.__conn, self.scope.run, basket, self.sim)

    def _delay(self, shipment: str, expected_sim: int) -> dict[str, Any]:
        if expected_sim < self.sim:
            raise ValueError("Shipment ETA cannot precede current time")
        row = self.__conn.execute(
            """UPDATE lab_shipments SET expected_sim=%s,status='delayed'
            WHERE run_id=%s AND id=%s AND status!='received' AND expected_sim<=%s RETURNING id""",
            (expected_sim, self.scope.run, shipment, expected_sim),
        ).fetchone()
        if not row:
            raise ValueError("Unknown shipment or outdated delay")
        return {"shipment": shipment, "expected_sim": expected_sim}

    def _receive(self, shipment: str) -> dict[str, Any]:
        row = self.__conn.execute(
            "SELECT expected_sim,status FROM lab_shipments WHERE run_id=%s AND id=%s",
            (self.scope.run, shipment),
        ).fetchone()
        if not row:
            raise ValueError("Unknown shipment")
        deferred = row["status"] != "received" and self.sim < row["expected_sim"]
        return {
            "shipment": shipment,
            "deferred": deferred,
            "received": False
            if deferred
            else receive(self.__conn, self.scope.run, shipment, self.sim),
        }

    def _recall(self) -> list[dict[str, Any]]:
        return self.__conn.execute(
            """SELECT key,body,observed_sim,expires_sim,event_id
            FROM agent_memories WHERE run_id=%s AND store=%s AND expires_sim>%s ORDER BY key""",
            (self.scope.run, self.scope.store, self.sim),
        ).fetchall()

    def _remember(self, key: str, body: dict[str, Any], ttl_seconds: int = 3600) -> None:
        if not 1 <= len(key) <= 100 or not 1 <= ttl_seconds <= 86400:
            raise ValueError("Invalid memory key or TTL")
        if len(json.dumps(body, ensure_ascii=False).encode()) > 2048:
            raise ValueError("Memory entry exceeds byte limit")
        # Read through the same authenticated connection and transaction as the write.
        # Expired entries are not an active baseline, but retain that distinction for audit.
        self.__conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"memory:{self.scope.run}:{self.scope.store}:{key}",),
        )
        previous = self.__conn.execute(
            "SELECT body,observed_sim,expires_sim,event_id FROM agent_memories "
            "WHERE run_id=%s AND store=%s AND key=%s FOR UPDATE",
            (self.scope.run, self.scope.store, key),
        ).fetchone()
        self.__conn.execute(
            "DELETE FROM agent_memories WHERE run_id=%s AND store=%s AND expires_sim<=%s",
            (self.scope.run, self.scope.store, self.sim),
        )
        self.__conn.execute(
            """INSERT INTO agent_memories VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(run_id,store,key) DO UPDATE SET body=excluded.body,
            observed_sim=excluded.observed_sim,expires_sim=excluded.expires_sim,event_id=excluded.event_id""",
            (
                self.scope.run,
                self.scope.store,
                key,
                Jsonb(body),
                self.sim,
                self.sim + ttl_seconds,
                self.event.id,
            ),
        )

        self.memory_writes.append(
            {
                "key": key,
                "body": json.loads(json.dumps(body)),
                "observed_sim": self.sim,
                "expires_sim": self.sim + ttl_seconds,
                "previous": previous,
            }
        )

    def _publish(
        self, topic: str, payload: dict[str, Any], key: str, due_sim: int | None = None
    ) -> int:
        if topic not in self.role.emits:
            raise PermissionError("Event topic is not granted to this role")
        if any(k in payload for k in ("run", "run_id", "store", "owner", "namespace", "agent_id")):
            raise PermissionError("Outbound scope cannot be supplied by policy")
        return publish(
            self.__conn,
            run_id=self.scope.run,
            producer=self.role.name,
            topic=topic,
            payload=payload,
            key=key,
            trace_id=self.event.trace_id,
            parent_id=self.event.id,
            target_store=None,
            due_sim=self.sim if due_sim is None else due_sim,
        )


class InventoryPolicy:
    """Deterministic baseline policy; the runtime also supports future decision adapters."""

    def decide(self, event: Event, tools: ScopedTools) -> dict[str, Any]:
        body = event.payload
        context = tools.invoke("inventory.read", sku=body.get("sku"))
        memory = tools.invoke("memory.read")
        if event.topic == "basket.requested":
            request = BasketRequest.model_validate(body)
            if request.store != tools.scope.store:
                raise PermissionError("Basket is outside this store")
            status = tools.invoke(
                "inventory.reserve",
                basket=request.basket,
                sku=request.sku,
                quantity=request.quantity,
                expires_sim=request.expires_sim,
            )
            if request.deliver and status == "reserved":
                tools.invoke(
                    "queue.publish",
                    topic="basket.reserved",
                    payload={"basket": request.basket},
                    key=request.basket,
                )
            detail = {
                "basket": request.basket,
                "status": status,
                "rule": "reserve only confirmed available units; reject insufficient stock",
            }
        elif event.topic == "reservation.expire":
            basket = BasketRef.model_validate(body).basket
            detail = {
                "basket": basket,
                "status": tools.invoke("inventory.release", basket=basket),
                "rule": "release unused reservation once at simulation deadline",
            }
        elif event.topic == "shipment.delayed":
            delay = ShipmentDelay.model_validate(body)
            detail = tools.invoke(
                "inventory.delay", shipment=delay.shipment, expected_sim=delay.expected_sim
            )
            tools.invoke(
                "queue.publish",
                topic="shipment.received",
                payload={"shipment": delay.shipment},
                key=f"{delay.shipment}:{delay.expected_sim}",
                due_sim=delay.expected_sim,
            )
            detail["rule"] = "expected supply is a forecast, not sellable stock"
        elif event.topic == "shipment.received":
            shipment = ShipmentRef.model_validate(body).shipment
            detail = tools.invoke("inventory.receive", shipment=shipment)
            detail["rule"] = "ignore obsolete receipt; add units once at confirmed arrival"
        else:
            raise PermissionError("Unsupported event")
        tools.invoke(
            "memory.write",
            key=f"last:{event.topic}",
            body={"topic": event.topic, "outcome": detail},
        )
        tools.invoke("queue.publish", topic="inventory.decided", payload=detail, key=str(event.id))
        return {
            **detail,
            "scope": {"run": tools.scope.run, "store": tools.scope.store},
            "role_hash": tools.scope.definition_hash,
            "policy": tools.role.policy,
            "memory_hits": len(memory),
            "observed_state": context,
            "tools": tools.calls,
        }


@dataclass(frozen=True)
class LocalAgent:
    scope: AgentScope
    role: RoleSpec
    dsn: str = field(repr=False)
    cloud_endpoint: str | None = None

    def claim(self, *, lease_seconds: float = 45) -> Event | None:
        with connect(self.dsn) as conn:
            row = conn.execute("SELECT public.agent_clock() AS sim").fetchone()
            assert row
        return Queue(self.dsn, lease_seconds).claim(
            self.role.name, self.scope.run, row["sim"], accepted_topics=self.role.accepts
        )

    def reserve_budget(self, event: Event) -> bool:
        self._validate(event)
        with connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT public.agent_reserve_budget(%s,%s,%s) AS reservation",
                (event.id, event.token, event.attempts),
            ).fetchone()
        return bool(row and row["reservation"]["status"] == "reserved")

    def _validate(self, event: Event) -> None:
        if str(event.run_id) != self.scope.run or event.target_store != self.scope.store:
            raise PermissionError("Event is outside authenticated scope")
        if event.topic not in self.role.accepts:
            raise PermissionError("Event is outside role subscriptions")

    def handle(self, conn: Connection, event: Event) -> None:
        self._validate(event)
        ticket = conn.execute(
            "SELECT slots FROM agent_event_budgets WHERE event_id=%s AND attempt=%s",
            (event.id, event.attempts),
        ).fetchone()
        if not ticket:
            raise BudgetExceeded("A durable budget reservation is required")
        tools = ScopedTools(conn, self.scope, self.role, event)
        if self.role.policy == "gcp_ai":
            model_ticket = conn.execute(
                "SELECT public.agent_model_reserved(%s,%s,%s) AS reserved",
                (event.id, event.token, event.attempts),
            ).fetchone()
            if not model_ticket or not model_ticket["reserved"]:
                raise BudgetExceeded("A durable model reservation is required")
            tools.cloud_endpoint = self.cloud_endpoint
            tools.cloud_dsn = self.dsn
        if self.role.name in {"household", "restaurant", "market"}:
            from delivery.supply_policy import SupplyPolicy

            detail = SupplyPolicy().decide(event, tools)
        elif self.role.name == "inventory":
            detail = InventoryPolicy().decide(event, tools)
        else:
            from delivery.workflow_policy import WorkflowPolicy

            detail = WorkflowPolicy().decide(event, tools)
        detail["reserved_tool_slots"] = ticket["slots"]
        # Persist actual writes with the decision/ACK transaction, so order
        # inspection survives TTL cleanup without changing agent recall access.
        detail["memory_writes"] = tools.memory_writes
        conn.execute(
            """INSERT INTO decisions(run_id,sim_time,agent,order_id,event_id,action,detail)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                self.scope.run,
                tools.sim,
                self.scope.agent_id,
                event.payload.get("basket"),
                event.id,
                event.topic,
                Jsonb(detail),
            ),
        )

    def process(self, event: Event) -> bool:
        if not self.reserve_budget(event):
            Queue(self.dsn).fail(event, "BudgetExceeded")
            return False
        if self.role.policy == "gcp_ai":
            with connect(self.dsn) as conn:
                row = conn.execute(
                    "SELECT public.agent_reserve_model(%s,%s,%s) AS reserved",
                    (event.id, event.token, event.attempts),
                ).fetchone()
            if not row or not row["reserved"]:
                Queue(self.dsn).fail(event, "ModelBudgetExceeded")
                return False
        return Queue(self.dsn).process(event, self.handle)


def create_agent(
    dsn: str, *, agent_mode: str = "local", cloud_endpoint: str | None = None
) -> LocalAgent:
    """Scope is read from the authenticated database login, never from a prompt/event."""
    with connect(dsn) as conn:
        row = conn.execute(
            "SELECT public.agent_scope() AS scope,public.agent_definition() AS definition"
        ).fetchone()
    if not row or not row["scope"] or not row["definition"]:
        raise PermissionError("Authenticated agent binding required")
    if agent_mode not in {"local", "gcp_ai"}:
        raise ValueError("Unknown agent mode")
    data = row["scope"]
    role = RoleSpec.model_validate(row["definition"])
    if role.digest != data["definition_hash"]:
        raise PermissionError("Role definition hash mismatch")
    if role.name == "judge":
        expected = "gcp_ai" if agent_mode == "gcp_ai" else "deterministic"
        if role.policy != expected:
            raise ValueError("Agent mode differs from frozen role")
        if role.policy == "gcp_ai" and not cloud_endpoint:
            raise ValueError("Cloud judge endpoint required")
    return LocalAgent(
        AgentScope(data["run_id"], data["store"], data["agent_id"], data["definition_hash"]),
        role,
        dsn,
        cloud_endpoint,
    )


# Compatibility for existing inventory workers; both use the same authenticated factory.
create_inventory_agent = create_agent

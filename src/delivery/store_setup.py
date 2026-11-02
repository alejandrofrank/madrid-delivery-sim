"""Trusted operator setup for real Madrid stores using the existing stock ledger."""

import hashlib
import random
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from delivery.catalogue import load_catalogue
from delivery.db import Connection
from delivery.inventory import movement
from delivery.queue import publish
from delivery.store_layout import StoreConfig, generate_layout, stock_to_shelves


def store_products() -> list[dict[str, Any]]:
    return [
        {
            "sku": f"{p.source}:{p.listing_id}",
            "name": p.name,
            "category": p.category,
            "cold": p.category in {"dairy", "protein", "frozen"},
            "provenance": p.provenance,
        }
        for p in load_catalogue(Path("data/expanded-catalogue.json")).products
        if p.domain == "supermarket"
    ]


def initialize_stores(conn: Connection, run: str, config: StoreConfig) -> None:
    products = store_products()
    layout = generate_layout(config.layout, products)
    if config.stores:
        stores = conn.execute(
            "SELECT id FROM locations WHERE kind='store' AND id=ANY(%s) ORDER BY id",
            (list(config.stores),),
        ).fetchall()
        if len(stores) != len(config.stores):
            raise ValueError("Unknown Madrid store")
    else:
        stores = conn.execute(
            "SELECT DISTINCT ON (district) id FROM locations WHERE kind='store' "
            "ORDER BY district,CASE WHEN lower(name) IN ('mercadona','lidl','dia') "
            "THEN 0 ELSE 1 END,id"
        ).fetchall()
    for store in stores:
        key = store["id"]
        conn.execute(
            "INSERT INTO store_environments(run_id,store,layout,catalogue) VALUES (%s,%s,%s,%s)",
            (run, key, Jsonb(layout), Jsonb(products)),
        )
        for product in products:
            sku = product["sku"]
            conn.execute(
                "INSERT INTO lab_stock(run_id,store,sku,on_hand) VALUES (%s,%s,%s,%s)",
                (run, key, sku, config.opening_units),
            )
            movement(
                conn, run, f"opening:{key}:{sku}", key, sku, 0, "opening", config.opening_units, 0
            )
        for slot in stock_to_shelves(layout, {p["sku"]: config.opening_units for p in products}):
            conn.execute(
                "INSERT INTO store_shelves VALUES (%s,%s,%s,%s,%s)",
                (run, key, slot["id"], slot["sku"], slot["quantity"]),
            )
        for index in range(config.layout.picker_count):
            conn.execute(
                "INSERT INTO store_workers(run_id,store,id,kind,node) VALUES (%s,%s,%s,%s,%s)",
                (
                    run,
                    key,
                    f"picker-{index + 1}",
                    config.layout.picker_kind,
                    layout["packing"]["node"],
                ),
            )
        conn.execute(
            "INSERT INTO store_workers(run_id,store,id,kind,node) "
            "VALUES (%s,%s,'forklift-1','forklift',%s)",
            (run, key, layout["dock"]["node"]),
        )
        for role in ("inventory", "fulfillment"):
            conn.execute(
                "INSERT INTO store_agent_budgets(run_id,store,role) VALUES (%s,%s,%s)",
                (run, key, role),
            )
        # An actual expected shipment; the ledger receives nothing until dock arrival.
        sku = products[0]["sku"]
        shipment = "truck-" + hashlib.sha256(key.encode()).hexdigest()[:12]
        conn.execute(
            "INSERT INTO lab_shipments(run_id,id,store,sku,quantity,expected_sim) "
            "VALUES (%s,%s,%s,%s,12,300)",
            (run, shipment, key, sku),
        )


def attach_store_order(conn: Connection, run: str, order: str, sim: int, seed: int) -> bool:
    row = conn.execute(
        "SELECT o.store,e.catalogue,r.store_config FROM orders o "
        "JOIN store_environments e ON e.run_id=o.run_id AND e.store=o.store "
        "JOIN runs r ON r.id=o.run_id WHERE o.run_id=%s AND o.id=%s",
        (run, order),
    ).fetchone()
    if row is None:
        return False
    entropy = int(hashlib.sha256(f"{seed}:{order}".encode()).hexdigest()[:16], 16)
    rng = random.Random(entropy)
    products = sorted(row["catalogue"], key=lambda p: p["sku"])
    selected = rng.sample(products, min(row["store_config"]["products_per_order"], len(products)))
    lines = {p["sku"]: 1 for p in sorted(selected, key=lambda p: p["sku"])}
    inserted = conn.execute(
        "INSERT INTO store_orders(run_id,order_id,store,lines) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT DO NOTHING RETURNING order_id",
        (run, order, row["store"], Jsonb(lines)),
    ).fetchone()
    if inserted:
        for sku, quantity in lines.items():
            publish(
                conn,
                run_id=run,
                producer="store_world",
                topic="store.order.requested",
                payload={"order_id": order, "sku": sku, "quantity": quantity},
                key=order + ":" + sku,
                trace_id=order,
                due_sim=sim,
            )
    return True

"""Transactional inventory tools. Only confirmed receipts create sellable units."""

from typing import Any

from delivery.db import Connection


def lock_stock(conn: Connection, run: str, store: str, sku: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM lab_stock WHERE run_id=%s AND store=%s AND sku=%s FOR UPDATE",
        (run, store, sku),
    ).fetchone()
    if not row:
        raise ValueError("Unknown store/product")
    return row


def movement(
    conn: Connection,
    run: str,
    key: str,
    store: str,
    sku: str,
    sim: int,
    kind: str,
    hand: int,
    reserved: int,
) -> None:
    conn.execute(
        """INSERT INTO lab_movements VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (run, key, store, sku, sim, kind, hand, reserved),
    )


def reserve(
    conn: Connection,
    run: str,
    basket: str,
    store: str,
    sku: str,
    quantity: int,
    sim: int,
    expires: int,
) -> str:
    if quantity <= 0 or expires <= sim:
        raise ValueError("Positive quantity and future expiry required")
    stock = lock_stock(conn, run, store, sku)
    prior = conn.execute(
        "SELECT * FROM lab_baskets WHERE run_id=%s AND id=%s", (run, basket)
    ).fetchone()
    if prior:
        if (prior["store"], prior["sku"], prior["quantity"], prior["expires_sim"]) != (
            store,
            sku,
            quantity,
            expires,
        ):
            raise ValueError("Idempotency key reused with different request")
        return str(prior["status"])
    status = "reserved" if stock["on_hand"] - stock["reserved"] >= quantity else "rejected"
    conn.execute(
        "INSERT INTO lab_baskets VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (run, basket, store, sku, quantity, status, expires),
    )
    if status == "reserved":
        conn.execute(
            """UPDATE lab_stock SET reserved=reserved+%s,version=version+1
                     WHERE run_id=%s AND store=%s AND sku=%s""",
            (quantity, run, store, sku),
        )
        movement(conn, run, f"reserve:{basket}", store, sku, sim, "reserved", 0, quantity)
    return status


def release(conn: Connection, run: str, basket: str, sim: int, *, cancel: bool = False) -> str:
    row = conn.execute(
        "SELECT * FROM lab_baskets WHERE run_id=%s AND id=%s", (run, basket)
    ).fetchone()
    if not row:
        raise ValueError("Unknown basket")
    lock_stock(conn, run, row["store"], row["sku"])
    row = conn.execute(
        "SELECT * FROM lab_baskets WHERE run_id=%s AND id=%s FOR UPDATE", (run, basket)
    ).fetchone()
    assert row
    if row["status"] != "reserved":
        return str(row["status"])
    if not cancel and sim < row["expires_sim"]:
        raise ValueError("Reservation has not expired")
    status = "cancelled" if cancel else "expired"
    conn.execute(
        "UPDATE lab_baskets SET status=%s WHERE run_id=%s AND id=%s", (status, run, basket)
    )
    conn.execute(
        """UPDATE lab_stock SET reserved=reserved-%s,version=version+1
                 WHERE run_id=%s AND store=%s AND sku=%s""",
        (row["quantity"], run, row["store"], row["sku"]),
    )
    movement(
        conn, run, f"release:{basket}", row["store"], row["sku"], sim, status, 0, -row["quantity"]
    )
    return status


def receive(conn: Connection, run: str, shipment: str, sim: int) -> bool:
    row = conn.execute(
        "SELECT * FROM lab_shipments WHERE run_id=%s AND id=%s", (run, shipment)
    ).fetchone()
    if not row:
        raise ValueError("Unknown shipment")
    lock_stock(conn, run, row["store"], row["sku"])
    row = conn.execute(
        "SELECT * FROM lab_shipments WHERE run_id=%s AND id=%s FOR UPDATE", (run, shipment)
    ).fetchone()
    assert row
    if row["status"] == "received":
        return False
    if sim < row["expected_sim"]:
        raise ValueError("Shipment has not arrived")
    conn.execute(
        "UPDATE lab_shipments SET status='received' WHERE run_id=%s AND id=%s", (run, shipment)
    )
    conn.execute(
        """UPDATE lab_stock SET on_hand=on_hand+%s,version=version+1
                 WHERE run_id=%s AND store=%s AND sku=%s""",
        (row["quantity"], run, row["store"], row["sku"]),
    )
    movement(
        conn,
        run,
        f"receipt:{shipment}",
        row["store"],
        row["sku"],
        sim,
        "received",
        row["quantity"],
        0,
    )
    return True


def availability(conn: Connection, run: str) -> list[dict[str, Any]]:
    return conn.execute(
        """SELECT s.*,s.on_hand-s.reserved AS available_now,
        r.sim_time AS as_of_sim, COALESCE((SELECT jsonb_agg(jsonb_build_object(
            'shipment',p.id,'quantity',p.quantity,'expected_sim',p.expected_sim,
            'status',p.status,'certainty','simulated forecast, not sellable stock'))
            FROM lab_shipments p WHERE p.run_id=s.run_id AND p.store=s.store
            AND p.sku=s.sku AND p.status!='received'),'[]'::jsonb) AS incoming
        FROM lab_stock s JOIN runs r ON r.id=s.run_id WHERE s.run_id=%s
        ORDER BY s.store,s.sku""",
        (run,),
    ).fetchall()

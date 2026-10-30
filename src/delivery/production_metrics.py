"""Allowlisted terminal evidence for production dashboards, separate from tracing."""

import os
import re
from datetime import UTC, datetime
from typing import Any

from delivery.chaos import evidence
from delivery.db import Connection, connect


def collect_run(conn: Connection, run: str) -> dict[str, list[dict[str, Any]]]:
    row = conn.execute("SELECT status FROM runs WHERE id=%s", (run,)).fetchone()
    if not row or row["status"] != "complete":
        raise ValueError("Export terminal runs only")
    observed = datetime.now(UTC).isoformat()
    orders = [{"event_id": f"order:{run}:{r['id']}", "observed_at": observed,
               "run_id": run, "order_id": r["id"], "status": r["status"],
               "delivered": r["status"] == "delivered",
               "late": (r["delivered_sim"] > r["due_sim"]
                        if r["delivered_sim"] is not None else None),
               "delivery_cost_eur": float(r["cost_eur"])}
              for r in conn.execute(
                  "SELECT id,status,delivered_sim,due_sim,cost_eur FROM orders WHERE run_id=%s",
                  (run,),
              )]
    disruptions = [{"event_id": f"disruption:{run}:{m['id']}", "observed_at": observed,
                    "run_id": run, "disruption_id": m["id"],
                    **{k: m[k] for k in ["time_to_recover_seconds", "orders_saved", "orders_lost",
                                        "late_deliveries", "refund_cost_eur", "extra_tokens",
                                        "extra_token_cost_usd", "failed_replans"]}}
                   for m in evidence(conn, run)["metrics"]]
    return {"operational_orders": orders, "disruptions": disruptions}


def export_run(run: str, *, client: Any = None) -> None:
    if os.environ.get("MDS_PRODUCTION_METRICS", "0") != "1":
        return
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not re.fullmatch(r"madrid-delivery-sim-[a-z0-9-]+", project):
        raise ValueError("Metrics require the dedicated application project")
    if client is None:
        from google.cloud import bigquery

        client = bigquery.Client(project=project)
    with connect() as conn:
        tables = collect_run(conn, run)
    for table, rows in tables.items():
        for offset in range(0, len(rows), 200):
            batch = rows[offset:offset + 200]
            errors = client.insert_rows_json(
                f"{project}.mds_analytics.{table}", batch,
                row_ids=[r["event_id"] for r in batch],
            )
            if errors:
                raise RuntimeError("Metrics export failed; retry the completed run export")

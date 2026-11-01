"""Run long simulations as durable Cloud Run Jobs, outside HTTP request CPU leases."""

import os
import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException

KINDS = frozenset({"orders", "city", "delivery", "inventory", "supply"})


def submit_job(kind: str, run: str, seconds: int = 0, *, session: Any = None) -> str:
    run = str(UUID(run))
    job = os.environ.get("DELIVERY_CLOUD_RUN_JOB", "")
    pattern = r"projects/[a-z][a-z0-9-]+/locations/[a-z0-9-]+/jobs/mds-shift"
    if (kind not in KINDS or type(seconds) is not int or not 0 <= seconds <= 120
            or not re.fullmatch(pattern, job)):
        raise ValueError("Invalid configured job or simulation request")
    if session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(credentials)
    response = session.post(
        f"https://run.googleapis.com/v2/{job}:run",
        json={"overrides": {"containerOverrides": [{"env": [
            {"name": "DELIVERY_JOB_KIND", "value": kind},
            {"name": "DELIVERY_JOB_RUN", "value": run},
            {"name": "DELIVERY_JOB_PLAYBACK", "value": str(seconds)},
        ]}]}}, timeout=30,
    )
    response.raise_for_status()
    operation = response.json().get("name")
    if not isinstance(operation, str) or not operation.startswith("projects/"):
        raise ValueError("Cloud Run did not acknowledge the execution")
    return operation


def schedule(tasks: BackgroundTasks, callback: Callable[..., Any], kind: str,
             run: str, *args: int) -> None:
    if os.environ.get("DELIVERY_RUNTIME", "local") != "live":
        tasks.add_task(callback, run, *args)
        return
    try:
        submit_job(kind, run, args[0] if args else 0)
    except Exception:
        # The created run remains inspectable and can be explicitly resumed.
        raise HTTPException(503, {"message": "Execution not acknowledged", "run_id": run}) from None


def execute(kind: str, run: str, seconds: int = 0) -> None:
    if kind not in KINDS or not 0 <= seconds <= 120:
        raise ValueError("Invalid job parameters")
    run = str(UUID(run))
    from delivery.db import connect

    # One job per run, including duplicate HTTP submissions. Never share API process memory.
    with connect() as guard:
        locked = guard.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 771)) ok", (run,)
        ).fetchone()
        guard.commit()
        if not locked or not locked["ok"]:
            raise RuntimeError("A job already owns this run")
        row = guard.execute("SELECT status FROM runs WHERE id=%s", (run,)).fetchone()
        guard.commit()
        if not row:
            raise ValueError("Unknown run")
        if row["status"] == "complete":
            if kind == "orders":
                from delivery.production_metrics import export_run

                export_run(run)
            return
        if kind == "orders":
            from delivery.simulation import Simulation
            from delivery.world import World

            Simulation(World()).run(run, export=False)
            from delivery.production_metrics import export_run

            export_run(run)
        elif kind == "city":
            from delivery.running_city import run_city

            run_city(run)
        elif kind == "delivery":
            from delivery.delivery_flow import run_delivery

            run_delivery(run, playback_seconds=seconds)
        elif kind == "inventory":
            from delivery.lab import run_slice

            run_slice(run, playback_seconds=seconds)
        else:
            from delivery.supply import run_supply

            run_supply(run)


if __name__ == "__main__":
    execute(os.environ["DELIVERY_JOB_KIND"], os.environ["DELIVERY_JOB_RUN"],
            int(os.environ.get("DELIVERY_JOB_PLAYBACK", "0")))

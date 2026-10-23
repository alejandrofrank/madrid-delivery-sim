"""One independently executable inventory worker, with explicit crash injection."""

import argparse
import os

from delivery.agent_runtime import create_inventory_agent
from delivery.db import Connection
from delivery.queue import Event, Queue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--crash", choices=["after-write", "after-commit"])
    args = parser.parse_args()
    agent = create_inventory_agent(os.environ["DATABASE_URL"])
    if agent.scope.run != args.run:
        raise PermissionError("Worker run does not match authenticated identity")
    queue = Queue(agent.dsn)
    event = agent.claim(lease_seconds=2)
    if not event:
        raise RuntimeError("No inventory work")
    if not agent.reserve_budget(event):
        raise RuntimeError("Worker budget exhausted")

    def handler(conn: Connection, message: Event) -> None:
        agent.handle(conn, message)
        if args.crash == "after-write":
            # Intentional abrupt exit: no exception cleanup, no ACK, transaction rolls back.
            os._exit(73)

    if not queue.process(event, handler):
        raise RuntimeError("Worker processing failed")
    if args.crash == "after-commit":
        os._exit(74)


if __name__ == "__main__":
    main()

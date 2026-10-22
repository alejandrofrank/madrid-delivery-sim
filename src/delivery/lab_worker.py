"""One independently executable inventory worker, with explicit crash injection."""

import argparse
import os

from delivery.db import Connection
from delivery.inventory_agent import handle_inventory
from delivery.queue import Event, Queue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--crash", choices=["after-write", "after-commit"])
    args = parser.parse_args()
    queue = Queue(lease_seconds=1)
    event = queue.claim("inventory", args.run, 0)
    if not event:
        raise RuntimeError("No inventory work")

    def handler(conn: Connection, message: Event) -> None:
        handle_inventory(conn, message)
        if args.crash == "after-write":
            # Intentional abrupt exit: no exception cleanup, no ACK, transaction rolls back.
            os._exit(73)

    if not queue.process(event, handler):
        raise RuntimeError("Worker processing failed")
    if args.crash == "after-commit":
        os._exit(74)


if __name__ == "__main__":
    main()

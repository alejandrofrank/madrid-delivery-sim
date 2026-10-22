import argparse
import json

from delivery.config import settings
from delivery.queue import Queue
from delivery.simulation import Simulation, create_run, initialize


def main() -> None:
    parser = argparse.ArgumentParser(description="Madrid Delivery Sim")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    demo = sub.add_parser("demo")
    demo.add_argument("--wall-seconds", type=float, default=600)
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--resume", type=str)
    replay = sub.add_parser("replay")
    replay.add_argument("event_id", type=int)
    args = parser.parse_args()
    if args.command == "replay":
        print(json.dumps({"replayed": Queue().replay(args.event_id)}))
        return
    world = initialize()
    if args.command == "init":
        print(f"Loaded Madrid: {len(world.nodes)} road nodes; hubs, shops and customers seeded")
        return
    if args.wall_seconds < 0:
        parser.error("--wall-seconds must be nonnegative")
    run = args.resume or create_run(world, seed=args.seed, wall_seconds=args.wall_seconds)
    print(f"Run {run}. Live map: http://localhost:{settings().app_port}", flush=True)
    result = Simulation(world).run(run)
    print(
        json.dumps(
            {"run": result["run"], "metrics": result["metrics"], "queue": result["queue"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()

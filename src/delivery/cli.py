import argparse
import json
from datetime import date
from pathlib import Path

from delivery.config import settings
from delivery.queue import Queue
from delivery.simulation import Simulation, create_run, initialize


def main() -> None:
    parser = argparse.ArgumentParser(description="madrid-delivery-sim")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    lab = sub.add_parser("lab-demo")
    lab.add_argument("--seed", type=int, default=42)
    lab.add_argument("--catalogue", type=Path, default=Path("data/lab-catalogue.json"))
    lab.add_argument("--sample-date", type=date.fromisoformat)
    lab.add_argument("--role-dir", type=Path, default=Path("config/agents/inventory"))
    catalogue = sub.add_parser("import-catalogue")
    catalogue.add_argument("input", type=Path)
    catalogue.add_argument("output", type=Path)
    catalogue.add_argument("--source", required=True)
    catalogue.add_argument("--limit", type=int, default=50)
    catalogue.add_argument("--domain", choices=["supermarket", "retail"], default="retail")
    catalogue.add_argument(
        "--confirmed-usd",
        action="store_true",
        required=True,
        help="Confirm raw vendor prices are genuinely USD",
    )
    flow = sub.add_parser("delivery-demo")
    flow.add_argument("--seed", type=int, default=42)
    demo = sub.add_parser("demo")
    demo.add_argument("--wall-seconds", type=float, default=600)
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--resume", type=str)
    replay = sub.add_parser("replay")
    replay.add_argument("event_id", type=int)
    args = parser.parse_args()
    if args.command == "delivery-demo":
        from delivery.delivery_flow import new_delivery, run_delivery

        run = new_delivery(args.seed)
        result = run_delivery(run)
        output = Path(f"artifacts/delivery-{run}.json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "run": run,
                    "artifact": str(output),
                    "jobs": result["jobs"],
                    "invariants": result["invariants"],
                }
            )
        )
        return
    if args.command == "lab-demo":
        from delivery.agent_specs import load_inventory_role
        from delivery.lab import create_lab, run_slice

        store_sources = None
        if args.sample_date:
            from delivery.history import history_catalogue, history_manifest

            args.catalogue = history_catalogue(args.sample_date)
            store_sources = history_manifest()["sources"]
        run = create_lab(seed=args.seed, catalogue_path=args.catalogue, store_sources=store_sources)
        result = run_slice(run, role=load_inventory_role(args.role_dir))
        Path("artifacts").mkdir(exist_ok=True)
        output = Path(f"artifacts/lab-{run}.json")
        output.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "run": run,
                    "artifact": str(output),
                    "crash": result["crash"],
                    "invariants": result["invariants"],
                }
            )
        )
        return
    if args.command == "import-catalogue":
        from delivery.catalogue import import_bakiano_csv

        if args.output.exists():
            parser.error("Output already exists; choose a new snapshot path")
        snapshot = import_bakiano_csv(args.input, args.source, args.limit, args.domain)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        print(json.dumps({"products": len(snapshot.products), "sha256": snapshot.digest()}))
        return
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

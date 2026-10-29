"""Promote one operator trace into an immutable version; references require human review."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delivery.golden_evals import artifact_trace, promote  # noqa: E402
from delivery.trajectory_evals import read_trace  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--receipt", type=Path)
    source.add_argument("--stored-trace", action="store_true")
    parser.add_argument("--pointer", default="", help="JSON path, e.g. /arms/3/evidence")
    parser.add_argument("--event-id", type=int)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--expect-category", action="append", default=[],
                        choices=["schema", "length", "invented_tool"])
    args = parser.parse_args()
    if args.stored_trace and args.event_id is None:
        parser.error("--stored-trace requires --event-id")
    trace = (artifact_trace(args.receipt, args.pointer, args.event_id) if args.receipt else
             read_trace(os.environ["DATABASE_URL"], args.event_id))
    path = promote(
        trace, json.loads(args.reference.read_text(encoding="utf-8")),
        root=ROOT / "data/evals/golden", case_id=args.id, description=args.description,
        source=args.receipt.name if args.receipt else f"migration-019:event:{args.event_id}",
        expected_categories=args.expect_category,
    )
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()

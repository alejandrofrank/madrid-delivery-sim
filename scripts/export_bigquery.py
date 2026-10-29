"""Prepare a free local analytics bundle, or explicitly upload a reviewed bundle."""

import argparse
import json
from pathlib import Path

from delivery.bigquery_export import prepare_bundle, upload_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Local files only; no credentials or cloud calls")
    prepare.add_argument("--receipt", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    upload = commands.add_parser("upload", help="Explicitly opt in to loading a reviewed bundle")
    upload.add_argument("--bundle", type=Path, required=True)
    upload.add_argument("--project", required=True)
    upload.add_argument("--dataset", default="delivery_analytics")
    upload.add_argument("--location", default="EU")
    upload.add_argument("--service-account", required=True)
    upload.add_argument("--confirm-upload", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_bundle(args.receipt, args.output)
    else:
        result = upload_bundle(
            args.bundle,
            project=args.project,
            dataset=args.dataset,
            location=args.location,
            service_account=args.service_account,
            confirm_upload=args.confirm_upload,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

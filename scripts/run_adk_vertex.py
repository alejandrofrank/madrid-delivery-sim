"""Bash-friendly, one-shot paid experiment using a temporary impersonated ADC.

Requires `python3 scripts/gcp_demo.py vertex-start` first. The source ADC and Jev
key are never printed, committed, copied into an image or mounted in the UI app.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from gcp_demo import Demo, DemoError


def docker_path(path: Path) -> str:
    value = str(path.resolve())
    if value.startswith("/mnt/") and len(value) > 7 and value[6] == "/":
        return value[5].upper() + ":" + value[6:]
    return value


def routing_continuation_flags(args: argparse.Namespace) -> list[str]:
    if (args.continue_planned or args.reviewed_failure) and not args.routing_comparison:
        raise DemoError("Planned-arm continuation is available only for the routing comparison")
    if args.continue_planned != args.reviewed_failure:
        raise DemoError(
            "Use both --continue-planned and --reviewed-failure after reviewing evidence"
        )
    if args.routing_comparison and (args.resume or args.after_review):
        raise DemoError("Routing comparisons cannot resume failed runs or replace the experiment")
    return ["--continue-planned", "--reviewed-failure"] if args.continue_planned else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true", required=True)
    parser.add_argument("--after-review", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--routing-comparison", action="store_true")
    parser.add_argument("--continue-planned", action="store_true")
    parser.add_argument("--reviewed-failure", action="store_true")
    args = parser.parse_args()
    continuation_flags = routing_continuation_flags(args)
    demo = Demo()
    state = demo.state()
    account = state.get("google_service_account.restaurant", {}).get("email")
    if account != f"restaurant-adk@{demo.project}.iam.gserviceaccount.com":
        raise DemoError("Dedicated Terraform restaurant identity is missing")
    if not demo.billing():
        raise DemoError("Run vertex-start before this explicit paid test")
    if (
        not args.routing_comparison
        and (demo.root / "artifacts/.adk-live-comparison.lock").exists()
        and not (args.after_review or args.resume)
    ):
        raise DemoError("A previous paid experiment is retained; inspect it before another test")
    experiment_dir = demo.root / ".env.adk-experiments"
    if args.routing_comparison:
        experiment_dir.mkdir(exist_ok=True)
        original_claim = experiment_dir / "route-comparison.execution.json"
        continuation_claim = experiment_dir / "route-comparison.continuation.execution.json"
        if args.continue_planned:
            if (
                not original_claim.is_file()
                or not (demo.root / "artifacts/adk-route-comparison.json").is_file()
                or continuation_claim.exists()
                or (experiment_dir / "route-comparison.operation.lock").exists()
            ):
                raise DemoError(
                    "Original stopped evidence is required; continuation is claimed once"
                )
        elif original_claim.exists() or continuation_claim.exists():
            raise DemoError(
                "Routing experiment already claimed; inspect receipts before any new spend"
            )
    profile = {
        "project": demo.project,
        "location": "global",
        "model": "gemini-3.5-flash-lite",
        "input_usd_per_million": 0.30,
        "output_usd_per_million": 2.50,
        "cached_input_usd_per_million": 0.03,
    }
    source = json.loads((demo.adc() / "application_default_credentials.json").read_text())
    if source.get("type") != "authorized_user":
        raise DemoError(
            "This local launcher requires user ADC to impersonate the restricted identity"
        )
    credentials = {
        "type": "impersonated_service_account",
        "service_account_impersonation_url": (
            f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{account}"
            ":generateAccessToken"
        ),
        "source_credentials": {
            k: source[k] for k in ("type", "client_id", "client_secret", "refresh_token")
        },
    }
    # This ignored directory is outside every UI bind mount and excluded from the
    # build context. Only the one-shot worker receives this read-only mount.
    with tempfile.TemporaryDirectory(prefix=".env.adk-adc-", dir=demo.root) as folder:
        adc = Path(folder) / "adc.json"
        adc.write_text(json.dumps(credentials))
        adc.chmod(0o600)
        env = dict(
            os.environ,
            DELIVERY_ADK_VERTEX_ENABLED="1",
            DELIVERY_ADK_VERTEX_PROFILE=json.dumps(profile),
        )
        print(
            (
                "Continuing reviewed unstarted arms; original cumulative caps unchanged."
                if args.continue_planned
                else "Running six matched routing arms; shared ceiling $0.60 "
                "(Vertex ≤ $0.54, Jev ≤ $0.01)."
                if args.routing_comparison
                else "Running two synthetic restaurant SOULs; "
                "Vertex admission ≤ $0.40, Jev ≤ $0.002016."
            ),
            flush=True,
        )
        print(
            demo.run(
                "docker.exe" if shutil.which("docker.exe") else "docker",
                "compose",
                "run",
                "--rm",
                "--no-deps",
                "--build",
                "--env-from-file",
                docker_path(demo.root / ".env.jev"),
                "-e",
                "DELIVERY_ADK_VERTEX_ENABLED=1",
                "-e",
                "DELIVERY_ADK_VERTEX_PROFILE=" + json.dumps(profile),
                "-e",
                "GOOGLE_APPLICATION_CREDENTIALS=/adk-credentials/adc.json",
                "-e",
                "DELIVERY_JEV_ENABLED=1",
                "-e",
                "TYPESAFE_MODEL=jev-1.14.0",
                "-v",
                f"{docker_path(Path(folder))}:/adk-credentials:ro",
                *(
                    [
                        "-v",
                        f"{docker_path(experiment_dir)}:/adk-experiments:rw",
                        "-e",
                        "DELIVERY_ADK_EXPERIMENT_DIRECTORY=/adk-experiments",
                    ]
                    if args.routing_comparison
                    else []
                ),
                "app",
                "python",
                "scripts/compare_agent_routing.py"
                if args.routing_comparison
                else "scripts/demo_adk_vertex.py",
                "--paid",
                *(["--after-review"] if args.after_review else []),
                *(["--resume"] if args.resume else []),
                *continuation_flags,
                env=env,
            )
        )


if __name__ == "__main__":
    main()

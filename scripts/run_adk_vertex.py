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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true", required=True)
    parser.add_argument("--after-review", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    demo = Demo()
    state = demo.state()
    account = state.get("google_service_account.restaurant", {}).get("email")
    if account != f"restaurant-adk@{demo.project}.iam.gserviceaccount.com":
        raise DemoError("Dedicated Terraform restaurant identity is missing")
    if not demo.billing():
        raise DemoError("Run vertex-start before this explicit paid test")
    if (demo.root / "artifacts/.adk-live-comparison.lock").exists() and not (
        args.after_review or args.resume
    ):
        raise DemoError("A previous paid experiment is retained; inspect it before another test")
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
            "Running two synthetic restaurant SOULs; Vertex admission ≤ $0.40, Jev ≤ $0.002016.",
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
                "app",
                "python",
                "scripts/demo_adk_vertex.py",
                "--paid",
                *(["--after-review"] if args.after_review else []),
                *(["--resume"] if args.resume else []),
                env=env,
            )
        )


if __name__ == "__main__":
    main()

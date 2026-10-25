"""Local city by default; explicitly start/stop the optional paid GCP judge.

Stdlib only: python scripts/gcp_demo.py start|stop|status
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = {
    "google_artifact_registry_repository.images[0]",
    "google_cloud_run_v2_service.judge[0]",
    "google_cloud_run_v2_service_iam_binding.invoker[0]",
}


class DemoError(RuntimeError):
    pass


class Demo:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.infra = root / "infra/gcp-ai"
        self.env = dict(os.environ)
        # A host venv can break gcloud's bundled interpreter.
        self.env.pop("PYTHONPATH", None)
        self.config = json.loads((self.infra / "deploy.auto.tfvars.json").read_text())
        self.project = self.config["project_id"]
        self.region = self.config["region"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.project):
            raise DemoError("Invalid dedicated project ID.")
        if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]", self.region):
            raise DemoError("Invalid Cloud Run region.")

    def run(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        cwd: Path | None = None,
    ) -> str:
        executable = shutil.which(args[0])
        if executable is None:
            raise DemoError(f"{args[0]} is required.")
        result = subprocess.run(
            [executable, *args[1:]],
            cwd=cwd or self.root,
            env=env or self.env,
            input=stdin,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=900,
        )
        if result.returncode:
            detail = result.stderr.strip()[-2000:]
            for secret in (self.env.get("GOOGLE_OAUTH_ACCESS_TOKEN"), stdin):
                if secret:
                    detail = detail.replace(secret.strip(), "[redacted]")
            raise DemoError(f"{args[0]} {args[1]} failed: {detail}")
        return result.stdout.strip()

    def tf(self, *args: str) -> str:
        return self.run("terraform", *args, cwd=self.infra)

    def cloud(self, *args: str) -> Any:
        return json.loads(
            self.run("gcloud", *args, f"--project={self.project}", "--format=json", "--quiet")
        )

    def state(self) -> dict[str, dict[str, Any]]:
        data = json.loads(self.tf("show", "-json"))
        resources = data.get("values", {}).get("root_module", {}).get("resources", [])
        result = {r["address"]: r["values"] for r in resources}
        project = result.get("google_project.ai", {})
        if (
            project.get("project_id") != self.project
            or project.get("labels", {}).get("application") != "madrid-delivery-sim"
            or project.get("deletion_policy") != "PREVENT"
        ):
            raise DemoError(
                "Expected the existing, protected dedicated simulation project in state."
            )
        return result

    def billing(self) -> bool:
        return bool(self.cloud("billing", "projects", "describe", self.project)["billingEnabled"])

    def local(self) -> dict[str, Any]:
        port = self.env.get("APP_PORT", "8010")
        if not port.isdigit():
            raise DemoError("APP_PORT must be numeric.")
        with urlopen(f"http://127.0.0.1:{port}/api/lab/city-config", timeout=10) as response:
            return json.load(response)["agent_modes"]

    def compose(
        self, cloud: bool, endpoint: str = "", caller: str = "", adc: Path | None = None
    ) -> None:
        env = dict(self.env)
        args = ["docker", "compose", "-f", "compose.yaml"]
        if cloud:
            env.update(
                DELIVERY_GCP_AI_ENDPOINT=endpoint,
                DELIVERY_GCP_AI_CALLER_SERVICE_ACCOUNT=caller,
                GCP_ADC_DIRECTORY=str(adc),
            )
            args += ["-f", "compose.gcp-ai.yaml"]
        args += ["up", "-d", "--force-recreate", "--wait", "app"]
        self.run(*args, env=env)
        if bool(self.local()["gcp_ai"]) != cloud:
            raise DemoError("Local app provider availability did not match the requested mode.")

    def apply(
        self, phase: str, *, billing: bool, runtime: bool, gateway: bool, image: str = ""
    ) -> None:
        print(f"{phase}: checking Terraform plan...", flush=True)
        settings = dict(
            enable_billing=billing,
            enable_runtime=runtime,
            enable_gateway=gateway,
            gateway_image=image,
        )
        # Saved plans/private override stay in the ignored Terraform directory.
        plan = "demo-command.tfplan"
        flags = [
            f"-var={k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in settings.items()
        ]
        self.tf("plan", "-input=false", "-no-color", f"-out={plan}", *flags)
        validate_plan(json.loads(self.tf("show", "-json", plan)), self.project, phase)
        self.tf("apply", "-input=false", "-no-color", plan)
        target = self.infra / "zz-demo.auto.tfvars.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, indent=2) + "\n")
        temporary.replace(target)
        print(f"{phase}: complete.", flush=True)

    def adc(self) -> Path:
        configured = self.env.get("GCP_ADC_DIRECTORY")
        if configured:
            directory = Path(configured)
        elif os.name == "nt":
            directory = Path(self.env["APPDATA"]) / "gcloud"
        else:
            directory = Path(self.env.get("CLOUDSDK_CONFIG", str(Path.home() / ".config/gcloud")))
        directory = directory.resolve()
        if not (directory / "application_default_credentials.json").is_file():
            raise DemoError("Set up local ADC first: gcloud auth application-default login.")
        return directory

    def image(self) -> str:
        registry = f"{self.region}-docker.pkg.dev"
        image = f"{registry}/{self.project}/judgement/gateway:demo"
        print("Building the small judge image locally...", flush=True)
        self.run(
            "docker",
            "build",
            "--platform=linux/amd64",
            "-f",
            "infra/gcp-ai/Dockerfile",
            "-t",
            image,
            ".",
        )
        # Isolate temporary registry credentials from the user's Docker config.
        docker_host = self.run(
            "docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
        )
        with tempfile.TemporaryDirectory(prefix="delivery-registry-") as config:
            env = dict(self.env, DOCKER_CONFIG=config, DOCKER_HOST=docker_host)
            env.pop("DOCKER_CONTEXT", None)
            token = self.run("gcloud", "auth", "print-access-token", "--quiet")
            self.run(
                "docker",
                "login",
                "-u",
                "oauth2accesstoken",
                "--password-stdin",
                registry,
                stdin=token + "\n",
                env=env,
            )
            print("Pushing the judge image...", flush=True)
            self.run("docker", "push", image, env=env)
        digests = json.loads(
            self.run("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image)
        )
        prefix = image.rsplit(":", 1)[0] + "@sha256:"
        matches = [
            d
            for d in digests
            if d.startswith(prefix) and re.fullmatch(r"[a-f0-9]{64}", d[len(prefix) :])
        ]
        if len(matches) != 1:
            raise DemoError("Could not verify the pushed immutable image digest.")
        return matches[0]

    def start(self) -> None:
        adc = self.adc()  # Fail before linking billing if local credentials are missing.
        self.run("docker", "info", "--format", "{{.ServerVersion}}")
        state = self.state()
        if "google_cloud_run_v2_service.judge[0]" not in state:
            self.apply("bootstrap", billing=True, runtime=True, gateway=False)
            image = self.image()
            self.apply("deploy", billing=True, runtime=True, gateway=True, image=image)
        state = self.state()
        service = state["google_cloud_run_v2_service.judge[0]"]
        if not self.billing():
            raise DemoError(
                "Gateway exists but billing is disabled; inspect status before retrying."
            )
        self.compose(True, service["uri"], state["google_service_account.caller[0]"]["email"], adc)
        print(
            "GCP judge is available. City stays local; choose GCP AI for a new test run. "
            "Startup makes no model inference calls.",
            flush=True,
        )

    def stop(self) -> None:
        # Remove ADC mount and prevent new cloud calls before deleting the runtime.
        local_error = None
        try:
            self.compose(False)
        except (DemoError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            local_error = str(exc)
            print("Local app reset failed; continuing cloud cleanup.", flush=True)
        state = self.state()
        if RUNTIME.intersection(state):
            if not self.billing():
                raise DemoError(
                    "Runtime remains with billing disabled. Inspect status; "
                    "restore billing to finish resource deletion before parking."
                )
            self.apply("remove-runtime", billing=True, runtime=False, gateway=False)
        self.apply("unlink-billing", billing=False, runtime=False, gateway=False)
        state = self.state()
        if RUNTIME.intersection(state) or self.billing():
            raise DemoError("Shutdown verification failed; inspect status.")
        print(
            "Parked: project, APIs and IAM retained; runtime removed and billing disabled.",
            flush=True,
        )
        if local_error:
            raise DemoError(
                "Cloud cleanup succeeded, but the local app needs attention: " + local_error
            )

    def status(self) -> dict[str, Any]:
        state = self.state()
        enabled = self.billing()
        project = self.cloud("projects", "describe", self.project)
        services = self.cloud("run", "services", "list", f"--region={self.region}")
        # Listing artifacts requires billing; never enable billing just for status.
        repositories = (
            self.cloud("artifacts", "repositories", "list", "--location=all") if enabled else None
        )
        try:
            modes = self.local()
        except (OSError, ValueError):
            modes = None
        runtime = sorted(RUNTIME.intersection(state))
        return dict(
            project=self.project,
            lifecycle=project["lifecycleState"],
            billing_enabled=enabled,
            runtime_in_state=runtime,
            cloud_run_services=len(services),
            artifact_repositories=len(repositories) if repositories is not None else None,
            artifact_check="live" if enabled else "unavailable_without_billing",
            foundation_resources=len(set(state) - RUNTIME),
            agent_modes=modes,
            mode="parked" if not enabled and not runtime and not services else "cloud-enabled",
            lifecycle_command_running=(self.infra / ".demo-command.lock").exists(),
            inference_calls_from_lifecycle_commands=0,
        )


# An automated lifecycle command may change billable resources, not the free foundation.
def validate_plan(plan: dict[str, Any], project: str, phase: str) -> None:
    allowed = {
        "bootstrap": {"create"},
        "deploy": {"create", "update"},
        "remove-runtime": {"delete"},
        "unlink-billing": set(),
    }[phase]
    for change in plan.get("resource_changes", []):
        actions = change["change"]["actions"]
        if actions == ["no-op"]:
            continue
        address = change["address"]
        before = change["change"].get("before") or {}
        after = change["change"].get("after") or {}
        if address == "google_project.ai" and actions == ["update"]:
            keys = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
            if keys <= {"billing_account"} and after.get("project_id") == project:
                continue
        if (
            address not in RUNTIME
            or len(actions) != 1
            or actions[0] not in allowed
            or (after or before).get("project") != project
        ):
            raise DemoError(
                f"Plan rejected: unexpected {actions} on {address}. "
                "Review this change manually; no apply was performed."
            )


@contextmanager
def lifecycle_lock(directory: Path):
    path = directory / ".demo-command.lock"
    try:
        handle = path.open("x")
    except FileExistsError as exc:
        raise DemoError(
            "Another lifecycle command holds .demo-command.lock. "
            "If it crashed, confirm it stopped before removing the lock."
        ) from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    try:
        demo = Demo()
        if args.action == "status":
            print(json.dumps(demo.status(), indent=2))
        else:
            with lifecycle_lock(demo.infra):
                demo.env["GOOGLE_OAUTH_ACCESS_TOKEN"] = demo.run(
                    "gcloud", "auth", "print-access-token", "--quiet"
                )
                getattr(demo, args.action)()
            print(json.dumps(demo.status(), indent=2))
        return 0
    except (DemoError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"{args.action} failed: {exc}", file=sys.stderr)
        if args.action == "start":
            print(
                "Partial resources may remain. Run status, then stop to clean up.", file=sys.stderr
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

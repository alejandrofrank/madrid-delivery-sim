"""Exercise the real Bash lifecycle with command substitutes, without cloud access."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="Bash is required")


def session(tmp_path: Path, failure: str = "") -> tuple[subprocess.CompletedProcess[str], str]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts/production_session.sh", scripts / "production_session.sh")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    stub = r'''#!/usr/bin/env bash
set -eu
command="${0##*/}"
printf '%s %s\n' "$command" "$*" >> "$CALL_LOG"
case "$command $*" in
  *"output -raw project_id") echo madrid-delivery-sim-test ;;
  *"output -raw region") echo europe-west1 ;;
  *"output -raw image_repository") echo europe-west1-docker.pkg.dev/test/app ;;
  *"output -raw replay_url") echo https://replay.example ;;
  *"state list")
    if [[ "$FAIL_STEP" == active ]]; then echo 'google_cloud_run_v2_service.replay[0]'; fi ;;
  "python3 scripts/cloud_run_cap.py"*) [[ "$FAIL_STEP" != cap ]] ;;
  "python3 scripts/verify_replay.py"*) [[ "$FAIL_STEP" != smoke ]] ;;
  "docker build"*) [[ "$FAIL_STEP" != build ]] ;;
  "docker login"*) cat >/dev/null ;;
  "gcloud auth print-access-token") echo synthetic-token ;;
  "gcloud artifacts docker images describe"*) printf 'sha256:%064d\n' 1 ;;
  *"apply"*"active=false"*) [[ "$FAIL_STEP" != teardown ]] ;;
esac
'''
    for name in ("terraform", "gcloud", "docker", "python3"):
        target = binaries / name
        target.write_text(stub)
        target.chmod(0o755)
    log = tmp_path / "calls.txt"
    result = subprocess.run(
        ["bash", str(scripts / "production_session.sh"), "1"],
        input="\n", text=True, capture_output=True, timeout=20,
        env={**os.environ, "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
             "CALL_LOG": str(log), "FAIL_STEP": failure, "MDS_BILLING_ACCOUNT": "test"},
    )
    return result, log.read_text()


def test_session_verifies_cap_and_removes_runtime_after_smoke(tmp_path):
    result, calls = session(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls.index("cloud_run_cap.py") < calls.index("active=true")
    assert calls.index("verify_replay.py") < calls.index("active=false")
    assert calls.count("active=false") == 1
    assert "docker logout https://europe-west1-docker.pkg.dev" in calls


@pytest.mark.parametrize("failure", ["build", "smoke"])
def test_failed_session_still_tears_down(tmp_path, failure):
    result, calls = session(tmp_path, failure)
    assert result.returncode != 0
    assert calls.count("active=false") == 1


@pytest.mark.parametrize("failure", ["cap", "active"])
def test_rejected_session_never_changes_infrastructure(tmp_path, failure):
    result, calls = session(tmp_path, failure)
    assert result.returncode != 0
    assert "apply" not in calls
    assert "docker build" not in calls


def test_teardown_failure_is_visible_and_nonzero(tmp_path):
    result, _ = session(tmp_path, "teardown")
    assert result.returncode == 1
    assert "TEARDOWN FAILED" in result.stderr

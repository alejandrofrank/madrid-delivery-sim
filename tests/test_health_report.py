"""Safe report evidence uses real tiny pytest sessions, without report recursion."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from delivery.health_report import HealthReport, apply_phase, atomic_write_json, source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def sample_run(tmp_path, source, *args, enabled=True):
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8"
    )
    (tmp_path / "tests/test_sample.py").write_text(source, encoding="utf-8")
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "PYTEST_ADDOPTS": "",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "LLM_PROVIDER": "disabled",
        "DELIVERY_SOURCE_REVISION": "a" * 40,
    }
    command = [sys.executable, "-m", "pytest", "-p", "delivery.health_report"]
    if enabled:
        command.append("--health-report=artifacts/health")
    result = subprocess.run(
        [*command, *args],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
    )
    path = tmp_path / "artifacts/health/latest-tests.json"
    return result, json.loads(path.read_text()) if path.is_file() else None


def test_report_covers_parameter_cases_phases_and_safe_metadata(tmp_path):
    result, report = sample_run(
        tmp_path,
        '''
import pytest

@pytest.fixture
def secret_fixture():
    raise RuntimeError("private-fixture-value")

@pytest.fixture
def cleanup_failure():
    yield
    raise RuntimeError("private-cleanup-value")

@pytest.mark.parametrize("value", [1, 2], ids=["one", "two"])
def test_parameter(value):
    """An actual descriptive docstring."""
    assert value == 1, "private-assertion-value"

def test_setup(secret_fixture):
    pass

def test_teardown(cleanup_failure):
    pass

@pytest.mark.skip(reason="private-skip-reason")
def test_skipped():
    pass

@pytest.mark.xfail
def test_expected_failure():
    assert False

@pytest.mark.xfail
def test_unexpected_pass():
    pass

@pytest.mark.xfail(strict=True)
def test_strict_unexpected_pass():
    pass
''',
    )
    assert result.returncode == 1
    assert report["schema_version"] == 1
    assert report["source_revision"] == "a" * 40
    assert report["state"] == "completed" and report["scope"] == "partial"
    assert report["completed_at"] and report["duration_seconds"] >= 0
    assert not report["source_changed"]
    rows = {row["name"]: row for row in report["tests"]}
    assert len(rows) == 8
    assert rows["test_parameter[one]"]["status"] == "passed"
    assert rows["test_parameter[two]"]["failure_phase"] == "call"
    assert rows["test_parameter[one]"]["description"] == "An actual descriptive docstring."
    assert rows["test_parameter[one]"]["markers"] == ["parametrize"]
    assert rows["test_parameter[one]"]["line"] == 13
    assert rows["test_parameter[one]"]["file"] == "tests/test_sample.py"
    assert rows["test_setup"]["failure_phase"] == "setup"
    assert rows["test_teardown"]["failure_phase"] == "teardown"
    assert rows["test_teardown"]["status"] == "failed"
    assert rows["test_skipped"]["status"] == "skipped"
    assert rows["test_expected_failure"]["status"] == "xfailed"
    assert rows["test_unexpected_pass"]["status"] == "xpassed"
    assert rows["test_strict_unexpected_pass"]["status"] == "xpassed"
    encoded = json.dumps(report)
    assert "private-" not in encoded and "traceback" not in encoded
    assert "captured" not in encoded and "longrepr" not in encoded


@pytest.mark.parametrize(
    "arguments,scope,exit_code",
    [
        (("-k", "first"), "partial", 0),
        (("--collect-only",), "collection", 0),
        (("tests/test_sample.py",), "partial", 0),
        (("--ignore", "tests/absent.py"), "partial", 0),
    ],
)
def test_collection_and_filters_keep_unrun_cases(tmp_path, arguments, scope, exit_code):
    result, report = sample_run(
        tmp_path,
        "def test_first(): pass\ndef test_second(): pass\n",
        *arguments,
    )
    assert result.returncode == exit_code
    assert report["scope"] == scope and len(report["tests"]) == 2
    if arguments[0] in {"-k", "--collect-only"}:
        assert report["tests"][1]["status"] == "not_run"


def test_full_run_publishes_initial_and_periodic_snapshots(tmp_path):
    result, report = sample_run(
        tmp_path,
        """
import json
from pathlib import Path
import pytest

@pytest.mark.parametrize("index", range(11))
def test_periodic(index):
    report = json.loads(Path("artifacts/health/latest-tests.json").read_text())
    assert report["state"] == "running"
    assert len(report["tests"]) == 11
    completed = sum(row["status"] == "passed" for row in report["tests"])
    assert completed == (10 if index == 10 else 0)
""",
    )
    assert result.returncode == 0, result.stdout.decode()
    assert report["scope"] == "full" and report["exit_code"] == 0
    assert all(row["status"] == "passed" for row in report["tests"])


def test_collection_failure_is_completed_partial_evidence(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_broken.py").write_text("raise RuntimeError('private-import-error')")
    result, report = sample_run(tmp_path, "def test_ok(): pass\n")
    assert result.returncode == 2
    assert report["collection_errors"] == 1 and report["scope"] == "partial"
    assert report["tests"][0]["status"] == "not_run"
    assert "private-import-error" not in json.dumps(report)


def test_interrupted_run_retains_unrun_tests(tmp_path):
    result, report = sample_run(
        tmp_path,
        "def test_interrupt(): raise KeyboardInterrupt\ndef test_later(): pass\n",
    )
    assert result.returncode == 2
    assert report["scope"] == "partial" and report["state"] == "completed"
    assert report["tests"][1]["status"] == "not_run"


def test_plugin_is_disabled_without_option(tmp_path):
    result, report = sample_run(tmp_path, "def test_ok(): pass\n", enabled=False)
    assert result.returncode == 0 and report is None
    assert not (tmp_path / "artifacts").exists()


def test_run_detects_source_changes(tmp_path):
    result, report = sample_run(
        tmp_path,
        """
from pathlib import Path
def test_change_source():
    Path("src").mkdir()
    Path("src/new.py").write_text("VALUE = 1")
""",
    )
    assert result.returncode == 0 and report["source_changed"]


def test_fingerprint_covers_sources_and_ignores_runtime_private_and_cache_files(tmp_path):
    initial = source_fingerprint(tmp_path)
    ignored = [
        "data/local/private.json",
        "data/cache/private.json",
        "artifacts/health/latest-tests.json",
        "docs/guide.md",
        "src/__pycache__/cached.py",
        "src/.env",
        "src/.env.private.json",
        "web/node_modules/vendor.js",
        "src/module.pyc",
        "scripts/private.txt",
    ]
    for name in ignored:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ignored")
    assert source_fingerprint(tmp_path) == initial
    for name in (
        "src/module.py",
        "tests/test_module.py",
        "sql/init.sql",
        "web/app.js",
        "config/agents/courier/SOUL.md",
        "data/evals/fixed.json",
        "data/meal-snapshot.json",
        "data/madrid.graphml.gz",
        "infra/gcp-ai/gateway.py",
        "scripts/check.py",
        ".github/workflows/check.yml",
        "Makefile",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("included")
        updated = source_fingerprint(tmp_path)
        assert updated != initial
        assert updated == source_fingerprint(tmp_path)
        initial = updated


def test_atomic_replacement_preserves_previous_report_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "latest-tests.json"
    atomic_write_json(path, {"version": 1})

    def refuse_replace(*args):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("delivery.health_report.os.replace", refuse_replace)
    with pytest.raises(OSError, match="simulated"):
        atomic_write_json(path, {"version": 2})
    assert json.loads(path.read_text()) == {"version": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_fingerprint_does_not_follow_symlinks(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "unrelated.txt").write_text("unrelated file")
    initial = source_fingerprint(tmp_path)
    (tmp_path / "src/alias.py").symlink_to(tmp_path / "unrelated.txt")
    (tmp_path / "Makefile").symlink_to(tmp_path / "unrelated.txt")
    assert source_fingerprint(tmp_path) == initial


def test_history_retains_twelve_finished_uuid_reports_and_validates_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("DELIVERY_SOURCE_REVISION", "private-invalid-revision")
    config = SimpleNamespace(
        rootpath=tmp_path,
        args=["tests"],
        getoption=lambda name, default=None: False,
    )
    directory = tmp_path / "artifacts/health"
    identifiers = []
    for _ in range(14):
        reporter = HealthReport(config, directory)
        assert reporter.payload["source_revision"] is None
        assert json.loads((directory / "latest-tests.json").read_text())["state"] == "running"
        reporter.pytest_sessionfinish(0)
        identifiers.append(reporter.payload["id"])
    history = list((directory / "runs").glob("*.json"))
    assert len(history) == 12
    assert {path.stem for path in history} == set(identifiers[-12:])
    for path in history:
        UUID(path.stem)
        assert json.loads(path.read_text())["state"] == "completed"
    assert not list(directory.rglob("*.tmp"))


def test_teardown_failure_overrides_pass_and_accumulates_duration():
    row = {"status": "not_run", "duration_seconds": 0.0, "failure_phase": None}
    for phase, outcome in (("setup", "passed"), ("call", "passed"), ("teardown", "failed")):
        report = pytest.TestReport(
            nodeid="tests/test_sample.py::test_ok",
            location=("tests/test_sample.py", 0, "test_ok"),
            keywords={},
            outcome=outcome,
            longrepr=None,
            when=phase,
            duration=0.1,
        )
        apply_phase(row, report)
    assert row["status"] == "failed" and row["failure_phase"] == "teardown"
    assert row["duration_seconds"] == pytest.approx(0.3)


@pytest.mark.parametrize(
    "pytest_exit,write_eval,expected_exit,source_changed",
    [
        (1, True, 1, False),
        (0, True, 0, False),
        (0, False, 1, False),
        (0, True, 1, True),
    ],
)
def test_runner_keeps_fixed_offline_commands_and_publishes_after_failure(
    tmp_path,
    monkeypatch,
    pytest_exit,
    write_eval,
    expected_exit,
    source_changed,
):
    spec = importlib.util.spec_from_file_location("health_check", ROOT / "scripts/health_check.py")
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "REPORT_DIRECTORY", tmp_path / "artifacts/health")
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://example.invalid/delivery_test")
    monkeypatch.setattr(sys, "argv", ["health_check.py"])
    commands = []

    def run(command, *, cwd, env, check):
        assert env["LLM_PROVIDER"] == "disabled"
        assert env["DATABASE_URL"] == "postgresql://example.invalid/delivery_test"
        assert env["PYTEST_ADDOPTS"] == ""
        assert cwd == tmp_path and check is False
        assert "--endpoint" not in command
        commands.append(command)
        if source_changed and "ruff" in command:
            changed = tmp_path / "src/changed.py"
            changed.parent.mkdir(parents=True, exist_ok=True)
            changed.write_text("modified = True")
        if "--output" in command and write_eval:
            Path(command[-1]).write_text(
                json.dumps(
                    {
                        "mode": "offline-baseline",
                        "summary": {"passed": 6, "cases": 6},
                    }
                )
            )
        return SimpleNamespace(returncode=pytest_exit if "pytest" in command else 0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.main() == expected_exit
    assert len(commands) == 5
    checks = json.loads((tmp_path / "artifacts/health/latest-checks.json").read_text())
    assert checks["source_changed"] is source_changed
    assert [row["id"] for row in checks["checks"]] == [
        "pytest",
        "ruff",
        "mypy",
        "agent-scenarios",
        "javascript",
        "evals",
    ]
    assert checks["checks"][0]["status"] == ("failed" if pytest_exit else "passed")
    assert checks["checks"][4]["status"] == "unavailable"
    if write_eval:
        evaluations = json.loads((tmp_path / "artifacts/health/latest-evals.json").read_text())
        assert evaluations["report"]["mode"] == "offline-baseline"
        assert evaluations["source_fingerprint"] == checks["source_fingerprint"]
    else:
        assert checks["checks"][-1]["status"] == "failed"


@pytest.mark.parametrize("test_url", ["", "postgresql://example.invalid/delivery", "invalid"])
def test_runner_rejects_missing_or_non_test_database_before_any_command(
    tmp_path, monkeypatch, test_url
):
    spec = importlib.util.spec_from_file_location("health_scope", ROOT / "scripts/health_check.py")
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "REPORT_DIRECTORY", tmp_path / "artifacts/health")
    monkeypatch.setenv("TEST_DATABASE_URL", test_url)
    monkeypatch.setattr(sys, "argv", ["health_check.py"])
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("No command allowed"))
    assert runner.main() == 2
    value = json.loads((tmp_path / "artifacts/health/latest-checks.json").read_text())
    assert value["checks"][0]["status"] == "failed"

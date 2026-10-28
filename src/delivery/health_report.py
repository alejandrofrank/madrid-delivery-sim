"""Opt-in pytest evidence without captured output, tracebacks, or fixture values."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import tempfile
import time
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

SOURCE_DIRECTORIES = (
    "src",
    "tests",
    "sql",
    "config",
    "web",
    "scripts",
    "data",
    ".github/workflows",
)
SOURCE_FILES = (
    "pyproject.toml",
    "requirements.lock",
    "Makefile",
    "Dockerfile",
    "infra/gcp-ai/gateway.py",
)
SOURCE_SUFFIXES = {
    ".py",
    ".sql",
    ".json",
    ".html",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".yml",
    ".yaml",
    ".toml",
    ".lock",
    ".md",
    ".svg",
    ".d2",
    ".gz",
}
EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "artifacts",
    "docs",
    "cache",
    "local",
}


def source_fingerprint(root: Path) -> str:
    """Hash only code, configuration, and fixed evaluation fixtures in stable order."""
    root = root.resolve()
    paths = {
        root / name
        for name in SOURCE_FILES
        if (root / name).is_file() and not (root / name).is_symlink()
    }
    for directory in SOURCE_DIRECTORIES:
        base = root / directory
        if base.is_dir() and not base.is_symlink():
            paths.update(
                path
                for path in base.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and path.suffix in SOURCE_SUFFIXES
                and not any(
                    part in EXCLUDED_PARTS or part.startswith(".env")
                    for part in path.relative_to(root).parts
                )
                and not any(parent.is_symlink() for parent in path.parents if parent != root)
            )
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda candidate: candidate.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode("utf-8")
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            # A source may disappear between enumeration and reading during an edit.
            continue
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace one fixed report file without exposing partially written JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def apply_phase(row: dict[str, Any], report: pytest.TestReport) -> None:
    """Aggregate setup/call/teardown; a later failure cannot erase an earlier one."""
    row["duration_seconds"] += report.duration
    expected_failure = hasattr(report, "wasxfail")
    strict_xpass = (
        report.failed
        and isinstance(report.longrepr, str)
        and report.longrepr.startswith("[XPASS(strict)]")
    )
    if report.failed:
        if strict_xpass:
            row["status"] = "xpassed"
        else:
            row.update(status="failed", failure_phase=report.when)
    elif row["status"] != "failed":
        if report.skipped:
            row["status"] = "xfailed" if expected_failure else "skipped"
        elif report.when == "call":
            row["status"] = "xpassed" if expected_failure else "passed"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--health-report",
        metavar="DIRECTORY",
        default=None,
        help="Write safe local test evidence to DIRECTORY (opt-in).",
    )


def pytest_configure(config: pytest.Config) -> None:
    directory = config.getoption("health_report")
    if directory is not None:
        config.pluginmanager.register(HealthReport(config, Path(directory)), "health-evidence")


class HealthReport:
    def __init__(self, config: pytest.Config, directory: Path) -> None:
        self.config = config
        self.root = config.rootpath
        self.directory = directory
        self.started = time.perf_counter()
        self.rows: dict[str, dict[str, Any]] = {}
        self.selected: set[str] = set()
        self.completed: set[str] = set()
        self.deselected = False
        revision = os.environ.get("DELIVERY_SOURCE_REVISION", "")
        self.payload: dict[str, Any] = {
            "schema_version": 1,
            "id": str(uuid4()),
            "kind": "tests",
            "state": "running",
            "started_at": utc_now(),
            "completed_at": None,
            "duration_seconds": 0.0,
            "exit_code": None,
            "scope": "partial",
            "source_fingerprint": source_fingerprint(self.root),
            "source_revision": revision
            if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision)
            else None,
            "source_changed": False,
            "collection_errors": 0,
            "tests": [],
        }
        self.publish()

    def publish(self) -> None:
        self.payload["duration_seconds"] = round(time.perf_counter() - self.started, 6)
        self.payload["tests"] = list(self.rows.values())
        atomic_write_json(self.directory / "latest-tests.json", self.payload)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> Generator[None]:
        # Capture before pytest applies -k/-m, retaining every collected parameter case.
        for item in items:
            relative = item.path.relative_to(self.root).as_posix()
            docstring = inspect.getdoc(getattr(item, "obj", None))
            line = item.location[1]
            self.rows[item.nodeid] = {
                "id": item.nodeid,
                "file": relative,
                "line": line + 1 if line is not None else 1,
                "name": item.name,
                "description": docstring or re.sub(r"^test_", "", item.name).replace("_", " "),
                "markers": sorted({marker.name for marker in item.iter_markers()}),
                "status": "not_run",
                "duration_seconds": 0.0,
                "failure_phase": None,
            }
        yield
        self.selected = {item.nodeid for item in items}
        self.publish()

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.deselected = self.deselected or bool(items)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.payload["collection_errors"] += 1

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        row = self.rows.get(report.nodeid)
        if row is None:
            return
        apply_phase(row, report)
        if report.when == "teardown":
            self.completed.add(report.nodeid)
            if len(self.completed) % 10 == 0:
                self.publish()

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        collection_only = self.config.getoption("collectonly")
        partial = (
            self.config.args != ["tests"]
            or self.config.getoption("keyword")
            or self.config.getoption("markexpr")
            or self.config.getoption("ignore")
            or self.config.getoption("ignore_glob")
            or self.config.getoption("lf", default=False)
            or self.deselected
            or self.selected != self.completed
            or not self.rows
            or self.payload["collection_errors"]
            or int(exitstatus) not in (0, 1)
            or any(row["status"] in {"not_run", "skipped"} for row in self.rows.values())
        )
        self.payload.update(
            state="completed",
            completed_at=utc_now(),
            exit_code=int(exitstatus),
            scope="collection" if collection_only else ("partial" if partial else "full"),
            source_changed=source_fingerprint(self.root) != self.payload["source_fingerprint"],
        )
        self.publish()
        history = self.directory / "runs"
        atomic_write_json(history / f"{self.payload['id']}.json", self.payload)
        reports = sorted(
            history.glob("*.json"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        for expired in reports[12:]:
            expired.unlink()

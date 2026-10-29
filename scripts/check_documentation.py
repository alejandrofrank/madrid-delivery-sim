#!/usr/bin/env python3
"""Validate the local documentation catalogue; --update refreshes public source links."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/documentation.json"
LINK = re.compile(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
PUBLIC_PREFIXES = ("src/", "tests/", "sql/", "config/", "scripts/", "docs/evidence/")
PUBLIC_FILES = {
    "compose.yaml",
    "compose.yml",
    "compose.gcp-ai.yml",
    "compose.jev.yml",
    "compose.jev.yaml",
    "compose.tracing.yaml",
    "compose.tracing-gcp.yaml",
    "Dockerfile",
    "Makefile",
    "pyproject.toml",
    "requirements.lock",
    "AGENTS.md",
    "infra/gcp-ai/main.tf",
    "infra/gcp-ai/variables.tf",
    "infra/gcp-ai/bigquery.tf",
    "infra/gcp-ai/telemetry.tf",
    "infra/gcp-ai/sql/run_dashboard.sql",
    "infra/gcp-ai/tests/bigquery.tftest.hcl",
    "infra/gcp-ai/tests/telemetry.tftest.hcl",
    "infra/gcp-ai/gateway.py",
    "infra/gcp-ai/Dockerfile",
    "infra/gcp-ai/requirements.lock",
    "infra/gcp-ai/requirements.txt",
    "infra/gcp-ai/tests/lifecycle.tftest.hcl",
}


def public_source(path: str) -> bool:
    parts = Path(path).parts
    return (
        not any(part.startswith(".") or part in {"local", "artifacts"} for part in parts)
        and not any(word in path for word in ("tfstate", "tfvars", "tfplan"))
        and (path in PUBLIC_FILES or path.startswith(PUBLIC_PREFIXES))
    )


def linked_sources(manifest: dict) -> set[str]:
    documents = {page["file"] for page in manifest["pages"]} | set(manifest["supplementary"])
    # The component explorer also links these exact implementation sources.
    sources = {"src/delivery/supply.py", "src/delivery/running_city.py"}
    for page in manifest["pages"]:
        body = (ROOT / page["file"]).read_text(encoding="utf-8-sig")
        for match in LINK.finditer(body):
            link = urlsplit(match.group(1))
            if link.scheme or link.netloc or not link.path or link.path.startswith("/"):
                continue
            path = posixpath.normpath(
                posixpath.join(posixpath.dirname(page["file"]), unquote(link.path))
            )
            target = ROOT / path
            if not target.exists():
                raise ValueError(f"Broken reference in {page['file']}: {path}")
            if path not in documents and target.is_file() and public_source(path):
                sources.add(path)
    return sources


def check(update: bool = False) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = [page["id"] for page in manifest["pages"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate documentation topic ID")
    sources = linked_sources(manifest)
    if update:
        manifest["sources"] = sorted(sources)
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    elif set(manifest["sources"]) != sources:
        raise ValueError("Source catalogue drift; run with --update and review the diff")
    for path in manifest["sources"]:
        if not public_source(path) or not (ROOT / path).is_file():
            raise ValueError(f"Not a public documentation source: {path}")
    print(
        f"Documentation: {len(ids)} chapters, {len(sources)} catalogued source files; links resolve"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    check(parser.parse_args().update)

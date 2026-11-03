"""Read-only, fixed-catalogue documentation. No database, cloud or execution access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "config/documentation.json"
router = APIRouter(tags=["documentation"])
MAX_SOURCE_BYTES = 512 * 1024


def catalogue() -> dict[str, Any]:
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def read_public_file(relative: str) -> str:
    """Defence in depth after exact catalogue membership; reject symlink escapes."""
    root = ROOT.resolve()
    path = root / relative
    if path.resolve() != path or not path.resolve().is_relative_to(root):
        raise HTTPException(404, "Source unavailable")
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise HTTPException(404, "Source unavailable")
    return path.read_text(encoding="utf-8-sig")


@router.get("/api/documentation")
def documentation_catalogue() -> dict[str, Any]:
    manifest = catalogue()
    return {
        "schema_version": manifest["schema_version"],
        "reviewed_at": manifest["reviewed_at"],
        "pages": [{**page, "body": read_public_file(page["file"])} for page in manifest["pages"]],
        "sources": manifest["sources"] + manifest["supplementary"],
    }


@router.get("/api/agent-anatomy")
def agent_anatomy() -> dict[str, Any]:
    from delivery.agent_anatomy import anatomy_data

    return anatomy_data()


@router.get("/api/documentation/source")
def documentation_source(path: str = Query(max_length=240)) -> dict[str, str]:
    manifest = catalogue()
    allowed = {
        *manifest["sources"],
        *manifest["supplementary"],
        *(page["file"] for page in manifest["pages"]),
    }
    if path not in allowed:
        raise HTTPException(404, "Unknown documentation source")
    return {"path": path, "text": read_public_file(path)}

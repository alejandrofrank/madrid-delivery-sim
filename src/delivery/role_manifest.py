"""Fixed, repository-owned capability manifests; no caller-selected file paths."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2] / "config/agents"


def manifest_names() -> tuple[str, ...]:
    return tuple(sorted(path.parent.name for path in ROOT.glob("*/role.json")))


def manifest_data(name: str) -> dict[str, Any]:
    if name not in manifest_names():
        raise ValueError("Unknown role")
    path = ROOT / name / "role.json"
    if path.resolve() != path or not path.is_file():
        raise ValueError("Manifest must remain inside its role directory")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def restaurant_capabilities(profile: str) -> frozenset[str]:
    return frozenset(manifest_data("restaurant")["tool_profiles"][profile])

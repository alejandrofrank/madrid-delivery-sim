"""Read-only examples captured from synthetic runs, with no live-service imports."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_EXAMPLE_BYTES = 12 * 1024 * 1024
EXAMPLE_KINDS = {"inventory", "restaurant", "store"}


def load_example(kind: str, directory: Path = Path("web/data/examples")) -> dict[str, Any]:
    if kind not in EXAMPLE_KINDS:
        raise ValueError("Unknown recorded example")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported recorded example manifest")
    entry = manifest["examples"][kind]
    filename = entry["file"]
    if not re.fullmatch(r"[a-z0-9-]+\.json", filename):
        raise ValueError("Invalid recorded example filename")
    path = directory / filename
    if path.is_symlink() or path.stat().st_size > MAX_EXAMPLE_BYTES:
        raise ValueError("Recorded example exceeds its file boundary")
    raw = path.read_bytes()
    if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("Recorded example hash mismatch")
    payload = json.loads(raw)
    recording = payload.get("recording", {})
    if (recording.get("schema_version") != 1 or recording.get("kind") != kind
            or recording.get("paid_model_calls") != 0
            or recording.get("read_only") is not True
            or recording.get("synthetic") is not True):
        raise ValueError("Expected a read-only, zero-paid-call synthetic example")
    if kind == "inventory":
        state = payload["data"]
    elif kind == "restaurant":
        state = payload["data"]["snapshot"]
    else:
        state = payload["data"]["frames"][-1]["city"]
    if state.get("run", {}).get("status") != "complete":
        raise ValueError("Recorded examples must be completed runs")
    return dict(payload)

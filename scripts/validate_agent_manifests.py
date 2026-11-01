#!/usr/bin/env python3
"""Validate every trusted manifest; --write-schema refreshes its published JSON Schema."""

import argparse
import json
from pathlib import Path

from delivery.agent_specs import load_role, role_schema
from delivery.role_manifest import ROOT, manifest_names


def validate(write_schema: bool = False) -> None:
    schema = role_schema()
    path = ROOT / "role.schema.json"
    if write_schema:
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    if json.loads(path.read_text(encoding="utf-8")) != schema:
        raise ValueError(
            "Role schema drift: run scripts/validate_agent_manifests.py --write-schema"
        )
    for name in manifest_names():
        role = load_role(name)
        if not all((role.display_name, role.mission, role.why_it_exists,
                    role.design_decisions, role.known_limits)):
            raise ValueError(f"{name}: missing plain-language explanation")
        if set(role.tools) != set(role.tool_descriptions):
            raise ValueError(f"{name}: every granted tool needs an explanation")
        if not (Path(ROOT) / name / role.soul_file).is_file():
            raise ValueError(f"{name}: missing SOUL")
    print(f"Validated {len(manifest_names())} manifests against the runtime schema")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-schema", action="store_true")
    validate(parser.parse_args().write_schema)

"""Export only the actual role decoration needed by the lightweight landing."""
import argparse
import json
from pathlib import Path

from delivery.agent_anatomy import anatomy_data


def build() -> bytes:
    agents = anatomy_data()["agents"]
    roles = [
        {key: agent[key] for key in ("id", "visual", "badge", "budget", "tool_badges")}
        for role in ("fulfillment", "courier")
        for agent in agents if agent["id"] == role
    ]
    if len(roles) != 2:
        raise ValueError("The landing handoff needs the fulfillment and courier manifests")
    return (json.dumps(roles, ensure_ascii=False, indent=2) + "\n").encode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path("web/data/story-agents.json")
    expected = build()
    if args.check:
        if not path.is_file() or path.read_bytes() != expected:
            raise SystemExit("Story agent decorations drifted; run scripts/build_story_agents.py")
    else:
        path.write_bytes(expected)

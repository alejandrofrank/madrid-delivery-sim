#!/usr/bin/env python3
"""Check or refresh content versions for the local workspaces' CSS and JavaScript."""

import argparse
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ASSET = re.compile(r'(?P<path>/static/[^"?]+\.(?:css|js))(?:\?v=[^" ]+)?(?=")')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update HTML asset versions")
    args = parser.parse_args()
    changed = []
    # The lazy renderer must change URL before its controller and HTML are hashed.
    for controller_name, renderer_name in (
        ("store-view.js", "store-3d.js"),
        ("agent-anatomy.js", "agent-anatomy-3d.js"),
        ("agent-story.js", "agent-delivery-scene.js"),
        ("landing.js", "landing-robots.js"),
    ):
        controller = WEB / controller_name
        renderer = WEB / renderer_name
        if controller.is_file() and renderer.is_file():
            original = controller.read_text(encoding="utf-8")
            digest = hashlib.sha256(renderer.read_bytes()).hexdigest()[:12]
            updated = re.sub(
                r"import\('\./" + re.escape(renderer_name) + r"(?:\?v=[^']+)?'\)",
                f"import('./{renderer_name}?v={digest}')",
                original,
            )
            if updated != original:
                changed.append(controller.name)
                if args.write:
                    controller.write_text(updated, encoding="utf-8")
    for page in sorted(WEB.glob("*.html")):
        original = page.read_text(encoding="utf-8")

        def version(match: re.Match[str]) -> str:
            asset = (WEB / match["path"].removeprefix("/static/")).resolve()
            if not asset.is_relative_to(WEB.resolve()) or not asset.is_file():
                raise ValueError(f'Invalid local asset: {match["path"]}')
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:12]
            return f'{match["path"]}?v={digest}'

        updated = ASSET.sub(version, original)
        if updated != original:
            changed.append(page.name)
            if args.write:
                page.write_text(updated, encoding="utf-8")
    if changed and not args.write:
        raise SystemExit("Stale web asset versions: " + ", ".join(changed))
    print(f"Web asset versions: {len(list(WEB.glob('*.html')))} workspaces checked")


if __name__ == "__main__":
    main()

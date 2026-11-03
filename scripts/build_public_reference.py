"""Freeze the reviewed agent documentation for the thin, read-only replay image."""
import argparse
import json
from pathlib import Path
from typing import Any

from delivery.agent_anatomy import anatomy_data
from delivery.documentation import catalogue, documentation_catalogue, read_public_file


def exports() -> dict[str, Any]:
    manifest = catalogue()
    paths = sorted(set(manifest['sources'] + manifest['supplementary']
                       + [page['file'] for page in manifest['pages']]))
    return {
        'anatomy.json': anatomy_data(),
        'chapters.json': documentation_catalogue(),
        'sources.json': {path: read_public_file(path) for path in paths},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    directory = Path('web/data/reference')
    directory.mkdir(exist_ok=True)
    for filename, payload in exports().items():
        raw = (json.dumps(payload, ensure_ascii=False, separators=(',', ':'),
                          sort_keys=True) + '\n').encode()
        path = directory / filename
        if args.check:
            if not path.exists() or path.read_bytes() != raw:
                raise SystemExit('Public reference drifted: ' + filename)
        else:
            path.write_bytes(raw)
    print('Public reference matches the reviewed source catalogue and agent manifests')


if __name__ == '__main__':
    main()

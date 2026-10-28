#!/usr/bin/env python3
"""Rebuild the documentation browser assets from integrity-pinned npm tarballs.

Run from any directory with ``python3 scripts/vendor_documentation.py``.
Use ``--check`` to verify the checked-in files without making network requests.
Only the Python standard library is required; no npm install scripts run.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "web" / "vendor" / "documentation"
REGISTRY = "https://registry.npmjs.org"
PACKAGES = (
    {
        "name": "marked",
        "version": "18.1.2",
        "integrity": (
            "sha512-DfOnvLAQ6WYeWxWO1u4RyFOeqyHup6dks5PPqnoFiooU7ipRvidO/2j8plhAHIiZg"
            "574E9ZlzSjUiPMLAzFkgg=="
        ),
        "tarball_url": f"{REGISTRY}/marked/-/marked-18.1.2.tgz",
        "browser_global": "marked",
        "files": {
            "package/lib/marked.umd.js": "marked.umd.js",
            "package/LICENSE": "marked.LICENSE",
        },
    },
    {
        "name": "dompurify",
        "version": "3.4.17",
        "integrity": (
            "sha512-B/pSlYVHQ58kqISD/yDjuJ1yfzI34m1gF4lAod2bwSRhiN4K5Cl3H8Af7hqB2PmT"
            "L911tdEudnnXn5FnhRoz0w=="
        ),
        "tarball_url": f"{REGISTRY}/dompurify/-/dompurify-3.4.17.tgz",
        "browser_global": "DOMPurify",
        "files": {
            "package/dist/purify.min.js": "purify.min.js",
            "package/LICENSE": "dompurify.LICENSE",
            "package/LICENSE-MPL": "dompurify.LICENSE-MPL",
        },
    },
    {
        "name": "@mermaid-js/tiny",
        "version": "12.2.0",
        "integrity": (
            "sha512-9bEE+R974NTh1YJlfc6ztgwhy6+9sE+wAFiFrqvSdtlJHdxGfLytQmHYHNpFKmj9"
            "4+Z+uMicYrQeGXnTTjILAQ=="
        ),
        "tarball_url": f"{REGISTRY}/@mermaid-js/tiny/-/tiny-12.2.0.tgz",
        "browser_global": "mermaid",
        "files": {
            "package/dist/mermaid.tiny.js": "mermaid.tiny.js",
            "package/LICENSE": "mermaid.LICENSE",
        },
    },
)
BUNDLED_LICENSE = "mermaid.BUNDLED-LICENSES.txt"


def download(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": "madrid-delivery-sim/vendor-documentation"})
    with urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Download exceeds size limit: {url}")
    return data


def file_record(path: str, source: str, data: bytes) -> dict:
    return {
        "path": path,
        "source": source,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def build_assets() -> dict[str, bytes]:
    assets = {}
    manifest = {
        "schema_version": 1,
        "generated_by": "scripts/vendor_documentation.py",
        "packages": [],
    }
    for package in PACKAGES:
        metadata_url = f"{REGISTRY}/{quote(package['name'], safe='')}/{package['version']}"
        metadata = json.loads(download(metadata_url, 1_000_000))
        if (metadata.get("name"), metadata.get("version")) != (package["name"], package["version"]):
            raise ValueError(f"Unexpected package metadata: {metadata_url}")
        distribution = metadata["dist"]
        for field, expected in (
            ("integrity", package["integrity"]),
            ("tarball", package["tarball_url"]),
        ):
            if distribution.get(field) != expected:
                raise ValueError(f"Pinned {field} changed for {package['name']}")
        tarball = download(distribution["tarball"], 16_000_000)
        digest = base64.b64encode(hashlib.sha512(tarball).digest()).decode("ascii")
        if not hmac.compare_digest(f"sha512-{digest}", distribution["integrity"]):
            raise ValueError(f"Tarball integrity mismatch for {package['name']}")

        records = []
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
            # Read only explicit regular members; never extract archive paths to disk.
            for source, local in package["files"].items():
                member = archive.getmember(source)
                if not member.isfile() or member.size > 12_000_000:
                    raise ValueError(f"Unexpected archive member: {source}")
                with archive.extractfile(member) as stream:
                    data = stream.read()
                assets[local] = data
                records.append(file_record(local, source, data))

        if package["name"] == "@mermaid-js/tiny":
            # The tiny package supplies dependency notices inline, not as a file.
            # Keep them in the original bundle and make them easy to inspect here.
            source = assets["mermaid.tiny.js"].decode("utf-8")
            marker = "/*! Bundled license information:"
            start = source.index(marker)
            end = source.index("*/", start) + 2
            notices = (source[start:end] + "\n").encode("utf-8")
            assets[BUNDLED_LICENSE] = notices
            records.append(
                file_record(
                    BUNDLED_LICENSE,
                    "package/dist/mermaid.tiny.js#bundled-license-information",
                    notices,
                )
            )

        manifest["packages"].append(
            {
                "name": package["name"],
                "version": package["version"],
                "metadata_url": metadata_url,
                "tarball_url": distribution["tarball"],
                "integrity": distribution["integrity"],
                "license": metadata["license"],
                "browser_global": package["browser_global"],
                "files": records,
            }
        )
    assets["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    return assets


def verify_assets() -> None:
    manifest = json.loads((DESTINATION / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported vendor manifest schema")
    if len(manifest["packages"]) != len(PACKAGES):
        raise ValueError("Unexpected package count in vendor manifest")
    expected_paths = {"manifest.json"}
    for package, record in zip(PACKAGES, manifest["packages"], strict=True):
        for key in ("name", "version", "integrity", "tarball_url", "browser_global"):
            if record[key] != package[key]:
                raise ValueError(f"Vendor manifest does not match pinned {key}")
        package_paths = set(package["files"].values())
        if package["name"] == "@mermaid-js/tiny":
            package_paths.add(BUNDLED_LICENSE)
        if {entry["path"] for entry in record["files"]} != package_paths:
            raise ValueError(f"Unexpected files for {package['name']}")
        expected_paths.update(package_paths)
        for entry in record["files"]:
            data = (DESTINATION / entry["path"]).read_bytes()
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"Vendor file differs from manifest: {entry['path']}")
    actual_paths = {path.relative_to(DESTINATION).as_posix() for path in DESTINATION.rglob("*")}
    if actual_paths != expected_paths:
        raise ValueError("Vendor directory has missing or unexpected files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Verify local assets without downloads"
    )
    options = parser.parse_args()
    if not options.check:
        assets = build_assets()
        DESTINATION.mkdir(parents=True, exist_ok=True)
        unexpected = {path.name for path in DESTINATION.iterdir()} - assets.keys()
        if unexpected:
            raise ValueError(f"Refusing to overwrite unexpected vendor files: {sorted(unexpected)}")
        # Complete all downloads and validations before replacing any checked-in file.
        with tempfile.TemporaryDirectory(
            prefix=".documentation-", dir=DESTINATION.parent
        ) as staging:
            for name, data in assets.items():
                staged_path = Path(staging) / name
                staged_path.write_bytes(data)
                staged_path.replace(DESTINATION / name)
    verify_assets()
    for path in sorted(DESTINATION.iterdir()):
        print(f"{path.relative_to(ROOT).as_posix()} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(f"Documentation assets: {error}", file=sys.stderr)
        sys.exit(1)

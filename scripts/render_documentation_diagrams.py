#!/usr/bin/env python3
"""Build the documentation's local SVGs with pinned D2 and ELK.

No application, database or cloud service is required. --check is fully offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "docs/diagrams"
OUTPUT = ROOT / "web/diagrams"
VERSION = "0.9.0"
CACHE = ROOT / "artifacts/.cache/d2" / VERSION
# Official v0.9.0 release asset digests, published by d2lang/d2.
DIGESTS = {
    ("Linux", "x86_64"): (
        "linux-amd64",
        "5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9",
    ),
    ("Linux", "aarch64"): (
        "linux-arm64",
        "ac2c028697199479acb321db1e3d68caee9f2ba492ed73caa3cd13f3829bf913",
    ),
    ("Darwin", "x86_64"): (
        "macos-amd64",
        "cad39576a480d6bb02ea142fef1726647914b0d2da51ccc9b30b660a2b1babf0",
    ),
    ("Darwin", "arm64"): (
        "macos-arm64",
        "eaf6c0c143e56dd9fa97bfb6df25ea9c1ebce40245f056a0768cf1a6c15d3064",
    ),
    ("Windows", "AMD64"): (
        "windows-amd64",
        "5f63b643de8f5a6dfb922d172e1b5496e4caf47497c33c4427cf1127f28c340f",
    ),
    ("Windows", "ARM64"): (
        "windows-arm64",
        "dd05cab459410c287d7ca3eb9cf78145a071742ee8e1b81a0122f84f471883e1",
    ),
}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def install() -> Path:
    target, expected = DIGESTS[(platform.system(), platform.machine())]
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / f"d2-v{VERSION}-{target}.tar.gz"
    url = f"https://github.com/d2lang/d2/releases/download/v{VERSION}/{archive.name}"
    if not archive.exists():
        urllib.request.urlretrieve(url, archive)
    if digest(archive.read_bytes()) != expected:
        raise ValueError(f"Official release checksum mismatch: {archive}")
    executable = "d2.exe" if platform.system() == "Windows" else "d2"
    binary = CACHE / executable
    # Extract only the executable's bytes; never extract archive paths.
    with tarfile.open(archive) as package:
        members = [
            m for m in package.getmembers() if m.isfile() and m.name.endswith(f"/bin/{executable}")
        ]
        if len(members) != 1:
            raise ValueError("Release does not contain exactly one expected D2 binary")
        stream = package.extractfile(members[0])
        assert stream is not None
        binary.write_bytes(stream.read())
    binary.chmod(binary.stat().st_mode | 0o111)
    return binary


def find_d2(args: argparse.Namespace) -> Path:
    binary = Path(args.d2) if args.d2 else CACHE / ("d2.exe" if os.name == "nt" else "d2")
    if args.install:
        binary = install()
    if not binary.is_file():
        found = shutil.which("d2")
        if not found:
            raise ValueError(
                "D2 is unavailable. Run with --install to fetch the verified "
                "official development binary."
            )
        binary = Path(found)
    actual = subprocess.check_output([str(binary), "--version"], text=True).strip()
    if actual != f"v{VERSION}":
        raise ValueError(f"Expected D2 v{VERSION}; found {actual}. Use --install.")
    return binary


def reference(entry: dict, allow_pending: bool) -> str | None:
    path = ROOT / entry["document"]
    if not path.is_file() and allow_pending:
        return None
    fences = re.findall(
        r"^" + chr(96) * 3 + r"mermaid\s*\n(.*?)^" + chr(96) * 3 + r"\s*$", read(path), re.M | re.S
    )
    try:
        return fences[entry["index"]].strip()
    except IndexError as error:
        raise ValueError(f"No Mermaid fence {entry['index']} in {entry['document']}") from error


def inspect_svg(path: Path) -> dict:
    payload = path.read_bytes()
    root = ET.fromstring(payload)
    labels = []
    forbidden = {"foreignObject", "script", "image", "a"}
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in forbidden:
            raise ValueError(f"Unexpected SVG element {tag}: {path}")
        for name, value in node.attrib.items():
            if name.lower().startswith("on") or (
                name.endswith("href") and not value.startswith(("#", "data:"))
            ):
                raise ValueError(f"Unexpected active/external SVG attribute: {path}")
        if tag == "text":
            text = " ".join(" ".join(node.itertext()).split())
            if text:
                labels.append(text)
    if len(labels) < 3:
        raise ValueError(f"Missing visible native SVG labels: {path}")
    for resource in re.findall(r"url\((.*?)\)", payload.decode("utf-8")):
        if not resource.strip(" \"'").startswith(("data:", "#")):
            raise ValueError(f"Unexpected external SVG resource: {path}")
    if "@import" in payload.decode("utf-8"):
        raise ValueError(f"Unexpected SVG stylesheet import: {path}")
    viewbox = root.attrib["viewBox"].split()
    return {
        "width": float(viewbox[2]),
        "height": float(viewbox[3]),
        "native_text_count": len(labels),
        "labels": labels,
    }


def validate_mapping(entries: list[dict], allow_pending: bool) -> None:
    expected = {
        (entry["document"], entry["index"])
        for entry in entries
        if (ROOT / entry["document"]).exists()
    }
    actual = set()
    pages = json.loads(read(ROOT / "config/documentation.json"))["pages"]
    for page in pages:
        fences = re.findall(
            r"^" + chr(96) * 3 + r"mermaid\s*\n(.*?)^" + chr(96) * 3 + r"\s*$",
            read(ROOT / page["file"]),
            re.M | re.S,
        )
        actual.update((page["file"], index) for index in range(len(fences)))
    if actual - expected or (expected - actual and not allow_pending):
        raise ValueError(
            f"Diagram mapping differs from chapter fences: missing={actual - expected}, "
            f"extra={expected - actual}"
        )
    if not allow_pending and any(not (ROOT / entry["document"]).is_file() for entry in entries):
        raise ValueError("A diagram's reference chapter is missing")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        action="store_true",
        help="download checksum-verified official D2 into ignored artifacts/.cache",
    )
    parser.add_argument("--d2", help="explicit path to pinned D2 binary")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify published assets and source/reference fingerprints offline",
    )
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="development only: permit a not-yet-written reference chapter",
    )
    args = parser.parse_args()
    entries = json.loads(read(SOURCES / "catalogue.json"))
    validate_mapping(entries, args.allow_pending)
    common = read(SOURCES / "common.d2")
    if args.check:
        manifest = json.loads(read(OUTPUT / "manifest.json"))
        if manifest["generator"] != {"name": "D2", "version": VERSION, "layout": "elk"}:
            raise ValueError("Unexpected diagram generator")
        if len(manifest["diagrams"]) != len(entries):
            raise ValueError("Diagram manifest has a different number of entries")
        for entry, published in zip(entries, manifest["diagrams"], strict=True):
            source = read(SOURCES / f"{entry['id']}.d2")
            ref = reference(entry, args.allow_pending)
            if any(published[key] != value for key, value in entry.items()):
                raise ValueError(f"Stale diagram metadata: {entry['id']}")
            if (
                published["source"] != source
                or published["common_source"] != common
                or published["reference"] != ref
            ):
                raise ValueError(
                    f"Stale diagram source/reference: {entry['id']}. Rebuild the diagrams."
                )
            if published["source_sha256"] != digest((source + "\0" + common).encode()) or published[
                "reference_sha256"
            ] != (digest(ref.encode()) if ref is not None else None):
                raise ValueError(f"Stale diagram fingerprints: {entry['id']}")
            for name, content in ((f"{entry['id']}.d2", source), ("common.d2", common)):
                if read(OUTPUT / name) != content:
                    raise ValueError(f"Stale published D2 source: {name}")
            artifact = OUTPUT / f"{entry['id']}.svg"
            if (
                digest(artifact.read_bytes()) != published["svg_sha256"]
                or inspect_svg(artifact) != published["svg"]
            ):
                raise ValueError(f"Stale or invalid SVG: {entry['id']}")
        print(
            f"Verified {len(entries)} local diagrams; native SVG labels, "
            "source fingerprints and chapter mappings match."
        )
        return
    binary = find_d2(args)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    published = []
    with tempfile.TemporaryDirectory(prefix="bakiano-diagrams-") as temp:
        for entry in entries:
            name = entry["id"]
            source = read(SOURCES / f"{name}.d2")
            artifact = Path(temp) / f"{name}.svg"
            subprocess.run(
                [
                    str(binary.resolve()),
                    "--layout=elk",
                    "--elk-nodeNodeBetweenLayers=45",
                    "--elk-edgeNodeBetweenLayers=24",
                    "--elk-padding=[top=36,left=28,bottom=28,right=28]",
                    "--theme=0",
                    "--pad=24",
                    "--omit-version",
                    "--salt",
                    name,
                    str(SOURCES / f"{name}.d2"),
                    str(artifact),
                ],
                check=True,
                cwd=ROOT,
            )
            info = inspect_svg(artifact)
            payload = artifact.read_bytes()
            (OUTPUT / artifact.name).write_bytes(payload)
            (OUTPUT / f"{name}.d2").write_text(source, encoding="utf-8")
            ref = reference(entry, args.allow_pending)
            published.append(
                {
                    **entry,
                    "asset": f"/static/diagrams/{name}.svg",
                    "source_asset": f"/static/diagrams/{name}.d2",
                    "source": source,
                    "common_source": common,
                    "reference": ref,
                    "source_sha256": digest((source + "\0" + common).encode()),
                    "reference_sha256": digest(ref.encode()) if ref is not None else None,
                    "svg_sha256": digest(payload),
                    "svg": info,
                }
            )
            print(f"{name}: {len(payload):,} bytes, {info['native_text_count']} native SVG labels")
    (OUTPUT / "common.d2").write_text(common, encoding="utf-8")
    (OUTPUT / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generator": {"name": "D2", "version": VERSION, "layout": "elk"},
                "diagrams": published,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error

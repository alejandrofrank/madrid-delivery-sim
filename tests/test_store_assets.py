"""The browser's curated assets are local, pinned, credited and byte-budgeted."""

import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path("web/vendor/simready")


def test_simready_assets_are_pinned_and_under_first_view_budget() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["author"] == "NVIDIA" and manifest["license"] == "CC-BY-4.0"
    assert len(manifest["revision"]) == 40
    assert {a["role"] for a in manifest["assets"]} == {
        "shelving",
        "pallet",
        "cart",
        "forklift",
        "robot",
        "produce",
        "packaged",
    }
    total = 0
    for asset in manifest["assets"]:
        content = (ROOT / (asset["role"] + ".glb")).read_bytes()
        assert len(content) == asset["bytes"]
        assert hashlib.sha256(content).hexdigest() == asset["sha256"]
        assert struct.unpack_from("<III", content) == (0x46546C67, 2, len(content))
        size, kind = struct.unpack_from("<II", content, 12)
        assert kind == 0x4E4F534A
        gltf = json.loads(content[20 : 20 + size])
        assert gltf["meshes"]
        assert not any("uri" in image for image in gltf.get("images", []))
        assert not any("uri" in buffer for buffer in gltf.get("buffers", []))
        total += len(content)
    assert total == manifest["total_bytes"] < 1_000_000
    runtime = sum(p.stat().st_size for p in Path("web/vendor/three").glob("*.js"))
    assert total + runtime < 4_000_000
    notice = (ROOT / "NOTICE.txt").read_text()
    assert manifest["dataset"] in notice and manifest["license_url"] in notice


def test_three_loader_uses_local_modules_only() -> None:
    root = Path("web/vendor/three")
    assert json.loads((root / "version.json").read_text())["version"] == "0.187.0"
    assert "MIT" in (root / "LICENSE").read_text()
    for name in ("GLTFLoader.js", "OrbitControls.js", "BufferGeometryUtils.js"):
        source = (root / name).read_text()
        assert "from './three.module.js'" in source
        assert "from 'three'" not in source
    assert (root / "meshopt_decoder.module.js").stat().st_size > 1000


def test_local_module_import_graph_is_complete():
    renderer = Path("web/store-3d.js")
    digest = hashlib.sha256(renderer.read_bytes()).hexdigest()[:12]
    assert f"import('./store-3d.js?v={digest}')" in Path("web/store-view.js").read_text()
    root = Path("web/vendor/three")
    for module in root.glob("*.js"):
        for relative in re.findall(
            r"^.*(?:from|import) ['\"]([.][^'\"]+)['\"];?$", module.read_text(), re.MULTILINE
        ):
            assert (module.parent / relative).is_file(), (module.name, relative)

"""Vendor pinned map renderer and a bounded, free offline Madrid map. Dev only."""

import base64, hashlib, io, json, math, tarfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "Bakiano-Madrid-Delivery-Sim/1.0 (local portfolio map; bounded offline pack)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def package(name, version, members):
    meta = json.loads(fetch("https://registry.npmjs.org/" + name + "/" + version))
    blob = fetch(meta["dist"]["tarball"])
    algorithm, expected = meta["dist"]["integrity"].split("-", 1)
    assert base64.b64encode(hashlib.new(algorithm, blob).digest()).decode() == expected
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member, target in members.items():
            save(ROOT / target, archive.extractfile("package/" + member).read())
    return {
        "package": name,
        "version": version,
        "url": meta["dist"]["tarball"],
        "integrity": meta["dist"]["integrity"],
    }


vendors = [
    package(
        "maplibre-gl",
        "5.15.0",
        {
            "dist/maplibre-gl.js": "web/vendor/maplibre/maplibre-gl.js",
            "dist/maplibre-gl.css": "web/vendor/maplibre/maplibre-gl.css",
            "LICENSE.txt": "web/vendor/maplibre/LICENSE.txt",
        },
    ),
    package(
        "@maplibre/maplibre-gl-leaflet",
        "0.1.3",
        {
            "leaflet-maplibre-gl.js": "web/vendor/maplibre/leaflet-maplibre-gl.js",
            "LICENSE": "web/vendor/maplibre/leaflet-LICENSE",
        },
    ),
]
root = ROOT / "web/map"
source_url = "https://tiles.openfreemap.org/styles/dark"
style = json.loads(fetch(source_url))
tilejson = json.loads(fetch("https://tiles.openfreemap.org/planet"))
bounds = [-3.85, 40.30, -3.52, 40.54]
items = []
for z in range(11, 15):
    x = lambda lon: math.floor((lon + 180) / 360 * 2**z)
    y = lambda lat: math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**z)
    for tx in range(x(bounds[0]), x(bounds[2]) + 1):
        for ty in range(y(bounds[3]), y(bounds[1]) + 1):
            items.append((z, tx, ty))
assert len(items) < 3000


def tile(item):
    z, x, y = item
    path = root / f"tiles/{z}/{x}/{y}.pbf"
    url = tilejson["tiles"][0].format(z=z, x=x, y=y)
    data = path.read_bytes() if path.exists() else fetch(url)
    if not path.exists():
        save(path, data)
    return {
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


# At most four connections and 50MB, per OpenFreeMap's published offline allowance.
with ThreadPoolExecutor(max_workers=4) as pool:
    tiles = list(pool.map(tile, items))
assert sum(t["bytes"] for t in tiles) < 50_000_000, (
    "Offline pack exceeds published download allowance"
)
for start in (0, 256, 8192):
    span = f"{start}-{start + 255}"
    url = f"https://tiles.openfreemap.org/fonts/Noto%20Sans%20Regular/{span}.pbf"
    save(root / f"fonts/Noto Sans Regular/{span}.pbf", fetch(url))
style["name"] = "Bakiano · Madrid"
style["sources"] = {
    "openmaptiles": {
        "type": "vector",
        "tiles": ["/static/map/tiles/{z}/{x}/{y}.pbf"],
        "minzoom": 11,
        "maxzoom": 14,
        "bounds": bounds,
        "attribution": tilejson["attribution"],
    }
}
style["glyphs"] = "/static/map/fonts/{fontstack}/{range}.pbf"
style.pop("sprite", None)
style["layers"] = [
    l for l in style["layers"] if l["id"] not in ("road_oneway", "road_oneway_opposite")
]
for layer in style["layers"]:
    paint = layer.setdefault("paint", {})
    layout = layer.get("layout", {})
    key = layer["id"]
    for name in list(paint):
        if "pattern" in name:
            paint.pop(name)
    for name in list(layout):
        if name.startswith("icon-"):
            layout.pop(name)
    if layer["type"] == "background":
        paint["background-color"] = "#14212e"
    if layer["type"] == "fill":
        paint["fill-color"] = (
            "#182b34"
            if any(word in key for word in ("wood", "park"))
            else "#15384c"
            if key == "water"
            else "#182633"
        )
        if key == "building":
            paint.update({"fill-color": "#1b2c3b", "fill-outline-color": "#273c4c"})
    if layer["type"] == "line":
        paint["line-color"] = (
            "#205875"
            if key == "waterway"
            else "#39546b"
            if any(word in key for word in ("inner", "major", "motorway"))
            else "#294155"
        )
        if "casing" in key:
            paint["line-color"] = "#1a2c3b"
        if key == "highway_minor":
            paint["line-width"] = [
                "interpolate",
                ["linear"],
                ["zoom"],
                11,
                0.45,
                13,
                0.85,
                16,
                2.5,
                20,
                10,
            ]
    if layer["type"] == "symbol":
        paint["text-color"] = "#9eb5c9" if key.startswith("place") else "#829caf"
        paint["text-halo-color"] = "#14212e"
        paint["text-halo-width"] = 1
        layout["text-field"] = [
            "coalesce",
            ["get", "name:es"],
            ["get", "name:latin"],
            ["get", "name"],
        ]
# Keep arterials subordinate to the selected route at city scale.
for layer in style["layers"]:
    paint = layer.get("paint", {})
    if layer["type"] == "line" and "line-width" in paint:
        width = paint["line-width"]
        if isinstance(width, (int, float)):
            paint["line-width"] = width * 0.4
        elif isinstance(width, dict):
            width["stops"] = [[a, b * 0.4] for a, b in width["stops"]]
        elif width[0] in ("interpolate", "step"):
            first = 3 if width[0] == "interpolate" else 2
            for i in range(first + 1, len(width), 2):
                if isinstance(width[i], (int, float)):
                    width[i] *= 0.4
    if layer["id"] == "park":
        paint["fill-color"] = "#193435"
for target, url in {
    "LICENSE-styles.md": "https://raw.githubusercontent.com/hyperknot/openfreemap-styles/main/LICENSE.md",
    "fonts/OFL.txt": "https://raw.githubusercontent.com/notofonts/NotoSans/main/LICENSE",
}.items():
    save(root / target, fetch(url))
save(root / "style.json", (json.dumps(style, separators=(",", ":")) + "\n").encode())
manifest = {
    "source_style": source_url,
    "tile_source": tilejson["tiles"][0],
    "bounds": bounds,
    "zoom": [11, 14],
    "tiles": tiles,
    "total_bytes": sum(t["bytes"] for t in tiles),
    "attribution": tilejson["attribution"],
    "offline_policy": "https://openfreemap.org/tos/",
    "renderer": vendors,
}
save(root / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
print(f"Vendored renderer and {len(tiles)} map tiles, {manifest['total_bytes'] / 1e6:.2f} MB")

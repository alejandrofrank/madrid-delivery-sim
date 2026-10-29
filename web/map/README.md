# Madrid basemap
This is a bounded, local OpenFreeMap / OpenMapTiles / OpenStreetMap map pack.
No API key, external runtime request, or paid service is required.

- 332 vector tiles, 36.51 MB, zoom 10–14, covering [-3.85, 40.30, -3.52, 40.54].
- Source version, SHA-256 hashes and exact byte counts: manifest.json.
- Acquisition stayed below the published 3,000-tile / 50 MB allowance, with
  four concurrent requests and an identifying User-Agent: https://openfreemap.org/tos/
- Style derived from OpenFreeMap Dark. Local changes: blue graphite palette,
  fine arterial lines, Spanish names, no sprites, local tile and glyph URLs.
  The simulator's cached street graph provides fine service-area detail.
- Map data: © OpenStreetMap contributors, ODbL:
  https://www.openstreetmap.org/copyright
- OpenMapTiles: https://openmaptiles.org/
- Style license and third-party notices: LICENSE-styles.md.
- Noto Sans cartographic glyphs: fonts/OFL.txt. The interface uses IBM Plex.
- Renderer: MapLibre GL JS 5.15.0 and Leaflet adapter 0.1.3, BSD/MIT licenses
  alongside web/vendor/maplibre. Renderer archives have npm integrity checks.
- Rebuild with python3 scripts/vendor_ui_map.py. Existing tiles are reused.
  Refreshing the dataset requires removing only this pack's tiles and manifest.

The map is limited to Madrid. It does not promise worldwide offline coverage.
Attribution remains visible on the map and in exported screenshots.
